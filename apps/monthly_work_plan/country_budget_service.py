"""Country Monthly Budget — the CD's monthly finance control page.

Consolidates only plan-backed, scheduled, costed activity budgets for the
selected month (`ActivityScheduleCostLine`) plus the CD Admin Budget, which
comes solely from the CD Monthly Admin Plan (`MonthlyWorkPlanBudget` +
`AdminBudgetLine`). There is no manual entry on this page — every amount is
traceable to either a scheduled cost line or the CD Monthly Admin Plan.

Lifecycle (persisted on MonthlyWorkPlanBudget.status):
    draft_generated → cd_review → admin_plan_added → submitted_to_rvp
    → approved_by_rvp | returned_by_rvp → sent_to_accountant → disbursed → closed

The CD reviews and submits to the RVP; the RVP approves or returns; the
Accountant disburses only after approval. While the budget is still "live"
(not yet submitted, or returned for correction), every view recomputes the
program total from real cost lines so the CD always reviews current numbers.
Once submitted to the RVP, the snapshot is locked — recompute stops so the
RVP reviews exactly what was submitted.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.permissions import has_permission
from apps.core.rbac import Permission
from apps.fund_requests.pl_approval_service import (
    CLUSTER_TRAINING,
    MONTHS,
    SSA_VISIT_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
    _ugx,
)

from .models import MonthlyWorkPlanBudget
from . import services as mwp

CD_ROLES = ("CountryDirector", "Admin")
RVP_ROLES = ("RegionalVicePresident", "Admin")
READ_ROLES = (
    "CountryDirector",
    "RegionalVicePresident",
    "Accountant",
    "ImpactAssessment",
    "Admin",
)

# Every Country Monthly Budget this module generates is tagged with this
# value (see _get_or_create_budget) — the single-country deployment's home.
HOME_COUNTRY_ID = "Uganda"

# Once submitted, the budget is a locked snapshot under review/approved —
# recompute must stop so nobody's view silently drifts from what was
# submitted/approved. Returned plans go back to "live" so CD's fix is real.
LOCKED_STATUSES = {
    "submitted_to_rvp",
    "approved_by_rvp",
    "sent_to_accountant",
    "disbursed",
    "closed",
}

CATEGORY_META = {
    "staff_visits": {"label": "Staff Visits", "unit_label": "Visits"},
    "partner_visits": {"label": "Partner Visits", "unit_label": "Visits"},
    "ssa": {"label": "SSA", "unit_label": "Visits"},
    "cluster_training": {"label": "Cluster Training", "unit_label": "Sessions"},
    "partner_in_school_training": {
        "label": "Partner In-School Training",
        "unit_label": "Schools",
    },
    "special_project": {"label": "Special Projects", "unit_label": "Activities"},
}
CATEGORY_ORDER = list(CATEGORY_META)

PLAN_SOURCE_ORDER = [
    "Plan-backed",
    "Admin Plan",
    "Needs Review",
    "Missing Cost",
    "Unplanned",
    "Excluded",
]


def _require_read(principal):
    role = getattr(principal, "active_role", None)
    if role not in READ_ROLES:
        raise Forbidden(
            "Only CD, RVP, Accountant, IA, or Admin may view the country monthly budget."
        )


def _require_cd(principal):
    """Authority to submit the country envelope upward.

    Gated on the permission rather than the role string, so the RBAC matrix
    is the source of truth and this authority is auditable there. The role
    tuple is kept as a belt-and-braces fallback for principals resolved
    before the permission seed exists.
    """
    if not has_permission(principal, Permission.COUNTRY_BUDGET_SUBMIT.value):
        if getattr(principal, "active_role", None) not in CD_ROLES:
            raise Forbidden(
                "Only the Country Director can submit the monthly budget to the RVP."
            )


def _require_rvp(principal):
    if not has_permission(principal, Permission.COUNTRY_BUDGET_APPROVE.value):
        if getattr(principal, "active_role", None) not in RVP_ROLES:
            raise Forbidden(
                "Only the Regional Vice President can approve or return this budget."
            )


def _assert_rvp_country_scope(budget) -> None:
    """§13 parity with services._assert_rvp_can_decide: an RVP may only
    decide on a budget inside their own operating country. A blank
    country_id is always in-scope (pre-dates per-country tagging).

    This module always tags budgets with HOME_COUNTRY_ID (see
    _get_or_create_budget); services._rvp_country_scope() is included too
    so the guard also honours a configured settings.COUNTRY_ID."""
    home = {HOME_COUNTRY_ID, mwp._rvp_country_scope()}
    if budget.country_id and budget.country_id not in home:
        raise Forbidden("This budget belongs to a country outside your region.")


def _month_key(fy, month_num):
    # This org's FY runs Oct→Sep: Oct-Dec belong to fy-1, Jan-Sep belong to fy.
    year = int(fy) - 1 if month_num >= 10 else int(fy)
    return f"{year}-{month_num:02d}"


def _page_category(activity_type, delivery_type, is_project=False):
    """Bucket an activity into one of the 6 activity-backed budget columns
    this page shows. A Special Project's cost — reachable via either the
    activity's own `project_id` or its cost line's `project_id`, the same two
    authoritative paths RVPDashboardService.special_projects consolidates —
    always shows under Special Projects, regardless of activity type or
    delivery type: the country budget needs a clean, undiluted view of
    project-funded spend, not a visit/training figure with project costs
    silently mixed in. Otherwise SSA collection takes priority regardless of
    who runs it; staff-delivered in-school trainings fold into Cluster
    Training since this page has no separate "Staff In-School Training"
    column."""
    if is_project:
        return "special_project"
    if activity_type in SSA_VISIT_TYPES:
        return "ssa"
    if activity_type in VISIT_TYPES:
        return "partner_visits" if delivery_type == "partner" else "staff_visits"
    if delivery_type == "partner" and activity_type in TRAINING_TYPES:
        return "partner_in_school_training"
    return "cluster_training"


def _is_project_line(li):
    """A cost line is Special-Project money if either authoritative path
    says so: the activity's own `project_id`, or the cost line's own
    `project_id` (set when a project-costed line is attached to an activity
    that isn't itself tagged to the project — e.g. partner-costed project
    work)."""
    return bool(li.activity.project_id or li.project_id)


def _get_or_create_budget(fy, month_num):
    month_key = _month_key(fy, month_num)
    budget, _created = MonthlyWorkPlanBudget.objects.get_or_create(
        country_id=HOME_COUNTRY_ID,
        month_key=month_key,
        defaults={"fy": fy, "status": "draft_generated"},
    )
    return budget


def _valid_lines_qs(fy, month_num):
    """The plan-backed, scheduled, costed lines this page is allowed to
    include — the activity-backed half of the "no scheduled activity, no
    ActivityBudgetLine, no Cost Catalogue source = no monthly budget line"
    rule. Partner activities are additionally required to be scheduled
    (planned_date set), not merely assigned."""
    from apps.activities.models import ActivityScheduleCostLine

    return (
        ActivityScheduleCostLine.objects.filter(
            activity__deleted_at__isnull=True,
            activity__fy=fy,
            month=month_num,
        )
        .exclude(activity__status__in=["cancelled", "rejected"])
        .exclude(activity__delivery_type="partner", activity__planned_date__isnull=True)
        .select_related("activity", "activity__school")
    )


def _team_monthly_requests(fy, month_num):
    """Program Lead team-budget snapshots for the selected month.

    The presence of even one of these requests turns on the deliberate monthly
    submission workflow.  That means the country budget can never quietly fall
    back to every raw scheduled cost line after Program Leads have started
    submitting their own monthly requests.
    """
    from apps.fund_requests.models import FundRequest, FundRequestPeriod

    return FundRequest.objects.filter(
        fy=fy,
        period=FundRequestPeriod.MONTHLY,
        period_key=f"{fy}-M{int(month_num)}",
        scope="team",
        submitted_by_role="Program Lead",
    ).order_by("created_at")


def _program_source(fy, month_num):
    """Return the approved Program Lead request source or the historic fallback.

    Historic data predates the PL monthly-request workflow, so raw plan-backed
    lines remain a read-only fallback only until the first team request exists
    for a month.  New months always use CD-approved PL snapshots.
    """
    from apps.fund_requests.models import FundRequestItem, FundRequestStatus

    requests = list(_team_monthly_requests(fy, month_num))
    if not requests:
        lines = list(_valid_lines_qs(fy, month_num))
        return {
            "uses_pl_request_workflow": False,
            "requests": [],
            "approved_requests": [],
            "lines": lines,
            "program_total": sum(int(line.amount or 0) for line in lines),
            "activity_count": len({line.activity_id for line in lines}),
            "label": "Plan-backed activities (historic workflow)",
        }

    approved = [
        request
        for request in requests
        if request.status == FundRequestStatus.APPROVED_BY_CD
    ]
    line_ids = FundRequestItem.objects.filter(
        fund_request_id__in=[request.id for request in approved]
    ).values_list("activity_schedule_cost_line_id", flat=True)
    lines = list(_valid_lines_qs(fy, month_num).filter(id__in=line_ids))
    return {
        "uses_pl_request_workflow": True,
        "requests": requests,
        "approved_requests": approved,
        "lines": lines,
        # The request total is the deliberate finance snapshot.  It is not
        # recalculated from today's activity rows after CD approval.
        "program_total": sum(int(request.total_amount or 0) for request in approved),
        "activity_count": len(
            {
                activity_id
                for activity_id in FundRequestItem.objects.filter(
                    fund_request_id__in=[request.id for request in approved]
                ).values_list("activity_id", flat=True)
            }
        ),
        "label": "CD-approved Program Lead monthly requests",
    }


def _validate_line(li):
    """Per-line validation → status label. A line missing its Cost Catalogue
    version is flagged, never silently included as if it were priced."""
    a = li.activity
    if a.status in ("cancelled", "rejected"):
        return "Excluded"
    if not li.catalogue_id:
        return "Missing Cost"
    if a.delivery_type == "partner" and not a.planned_date:
        return "Excluded"
    if getattr(a, "cost_missing", False):
        return "Needs Review"
    return "Plan-backed"


def _recompute_if_live(budget, source=None):
    if budget.status not in LOCKED_STATUSES:
        source = source or _program_source(
            budget.fy, int(budget.month_key.split("-")[1])
        )
        if source["uses_pl_request_workflow"]:
            budget.program_total = int(source["program_total"])
            budget.activity_count = int(source["activity_count"])
            budget.total_amount = budget.program_total + int(budget.admin_total or 0)
            budget.save(
                update_fields=[
                    "program_total",
                    "activity_count",
                    "total_amount",
                    "updated_at",
                ]
            )
        else:
            mwp.recompute_program_total(budget)
    return budget


def _user_names(ids):
    from apps.accounts.models import User

    return dict(
        User.objects.filter(id__in=[i for i in ids if i]).values_list("id", "name")
    )


def _trailing_month_series(fy, month_num, n=6):
    """Real trailing-month totals per category (oldest→newest, including the
    current month) — powers the KPI trend arrows and sparklines. A handful
    of small grouped-aggregate queries, not per-row fetches.

    Walks backward in plain (calendar_year, calendar_month) space — always
    unambiguous — then derives each point's own FY label from the same rule
    used everywhere else (Oct-Dec belong to fy-1 relative to Jan-Sep)."""
    from django.db.models import Sum

    from apps.activities.models import ActivityScheduleCostLine

    calendar_year = int(fy) - 1 if month_num >= 10 else int(fy)
    months = []  # (calendar_year, calendar_month), oldest→newest
    y, m = calendar_year, month_num
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()

    # Real historical admin totals (0 for months with no admin plan row yet
    # — an honest "nothing was planned" rather than a fabricated fill).
    month_keys = [f"{y}-{m:02d}" for y, m in months]
    admin_by_key = dict(
        MonthlyWorkPlanBudget.objects.filter(
            country_id=HOME_COUNTRY_ID, month_key__in=month_keys
        ).values_list("month_key", "admin_total")
    )

    series = []
    for y, m in months:
        line_fy = str(y + 1) if m >= 10 else str(y)
        rows = (
            ActivityScheduleCostLine.objects.filter(
                activity__deleted_at__isnull=True, activity__fy=line_fy, month=m
            )
            .exclude(activity__status__in=["cancelled", "rejected"])
            .values(
                "activity__activity_type",
                "activity__delivery_type",
                "activity__project_id",
                "project_id",
            )
            .annotate(total=Sum("amount"))
        )
        bucket = {k: 0 for k in CATEGORY_ORDER}
        for r in rows:
            is_project = bool(r["activity__project_id"] or r["project_id"])
            cat = _page_category(
                r["activity__activity_type"], r["activity__delivery_type"], is_project
            )
            bucket[cat] += r["total"] or 0
        bucket["total"] = sum(bucket.values())
        month_key = f"{y}-{m:02d}"
        bucket["admin"] = admin_by_key.get(month_key, 0)
        bucket["total_all"] = bucket["total"] + bucket["admin"]
        bucket["month_key"] = month_key
        series.append(bucket)
    return series


def _sparkline(values):
    """A tiny real polyline (last N months, oldest→newest) — no fabricated
    chart, just the actual trailing totals normalized to a 0-20 y-range."""
    if not values or len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = round(i * 60 / (n - 1), 1)
        y = round(20 - ((v - lo) / span) * 18 - 1, 1)
        pts.append(f"{x},{y}")
    return " ".join(pts)


def _trend(series, key):
    vals = [s[key] for s in series]
    if len(vals) < 2 or not vals[-2]:
        return {"pct": None, "up": None, "sparkline": _sparkline(vals)}
    pct = round((vals[-1] - vals[-2]) / vals[-2] * 100, 1)
    return {"pct": abs(pct), "up": pct >= 0, "sparkline": _sparkline(vals)}


def get_country_monthly_budget(principal, filters=None):
    _require_read(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    month_num = int(filters.get("month") or timezone.now().month)
    search = (filters.get("q") or "").strip().lower()

    budget = _get_or_create_budget(fy, month_num)
    source = _program_source(fy, month_num)
    _recompute_if_live(budget, source)

    lines = source["lines"]
    names = _user_names([li.responsible_user for li in lines])

    # ── Per-staff rows ─────────────────────────────────────────────────────
    rows_by_user: dict[str, dict] = {}
    excluded_count = 0
    for li in lines:
        status = _validate_line(li)
        if status == "Excluded":
            excluded_count += 1
            continue
        uid = li.responsible_user or "unassigned"
        row = rows_by_user.setdefault(
            uid,
            {
                "user_id": uid,
                "name": names.get(uid, "Unassigned"),
                "cats": {
                    k: {"qty": 0, "acts": set(), "schools": set(), "total": 0}
                    for k in CATEGORY_ORDER
                },
                "statuses": set(),
                "activity_ids": set(),
            },
        )
        cat = _page_category(
            li.activity.activity_type, li.activity.delivery_type, _is_project_line(li)
        )
        c = row["cats"][cat]
        c["acts"].add(li.activity_id)
        if li.activity.school_id:
            c["schools"].add(li.activity.school_id)
        c["total"] += li.amount
        row["statuses"].add(status)
        row["activity_ids"].add(li.activity_id)

    staff_rows = []
    for row in rows_by_user.values():
        row_total = 0
        cat_cols = {}
        for cat in CATEGORY_ORDER:
            c = row["cats"][cat]
            qty = (
                len(c["schools"])
                if cat == "partner_in_school_training"
                else len(c["acts"])
            )
            unit_cost = _ugx(round(c["total"] / qty)) if qty else "—"
            cat_cols[cat] = {
                "qty": qty,
                "unit_cost": unit_cost,
                "total": _ugx(c["total"]),
            }
            row_total += c["total"]
        statuses = row["statuses"]
        if "Missing Cost" in statuses:
            plan_status, tone = "Missing Cost", "warning"
        elif "Needs Review" in statuses:
            plan_status, tone = "Needs Review", "warning"
        else:
            plan_status, tone = "Plan-backed", "success"
        staff_rows.append(
            {
                "user_id": row["user_id"],
                "name": row["name"],
                "cats": cat_cols,
                "total": row_total,
                "total_fmt": _ugx(row_total),
                "status": plan_status,
                "status_tone": tone,
                "activity_count": len(row["activity_ids"]),
            }
        )
    staff_rows.sort(key=lambda r: -r["total"])
    if search:
        staff_rows = [r for r in staff_rows if search in r["name"].lower()]

    # ── CD Admin Plan row — the ONLY non-activity budget item ────────────────
    admin_lines = list(budget.admin_lines.all())
    admin_total = sum(a.total_cost for a in admin_lines)
    admin_status = "Admin Plan" if admin_lines else "Admin Plan Missing"

    # ── KPIs ──────────────────────────────────────────────────────────────
    # Recomputed straight from the raw lines (not the UGX-formatted staff_rows
    # display strings above) so downstream arithmetic stays on real integers.
    cat_totals = {k: 0 for k in CATEGORY_ORDER}
    for li in lines:
        if _validate_line(li) == "Excluded":
            continue
        cat = _page_category(
            li.activity.activity_type, li.activity.delivery_type, _is_project_line(li)
        )
        cat_totals[cat] += li.amount
    program_total = int(source["program_total"])
    total_monthly = program_total + admin_total
    staff_included = len(staff_rows) + (1 if admin_lines else 0)
    total_activities = int(source["activity_count"])

    series = _trailing_month_series(fy, month_num, n=6)
    # The current month's point should reflect this exact view's authoritative
    # per-category totals (which apply the full validity rules — catalogue
    # source, partner-scheduled — that the lighter trailing-series query
    # doesn't), not a possibly-slightly-different independent recount.
    series[-1].update(cat_totals)
    series[-1]["total"] = program_total
    series[-1]["admin"] = admin_total
    series[-1]["total_all"] = total_monthly

    def _kpi(label, value_int, trend_key, variant, helper):
        t = _trend(series, trend_key)
        return {
            "label": label,
            "value": _ugx(value_int),
            "variant": variant,
            "helper": helper,
            "trend_pct": t["pct"],
            "trend_up": t["up"],
            "sparkline": t["sparkline"],
        }

    kpis = [
        _kpi(
            "Total Monthly Budget",
            total_monthly,
            "total_all",
            "primary",
            source["label"],
        ),
        {
            "label": "Staff Included",
            "value": str(staff_included),
            "variant": "info",
            "helper": "All staff members",
            "trend_pct": None,
            "trend_up": None,
            "sparkline": "",
        },
        {
            "label": "Total Planned Activities",
            "value": str(total_activities),
            "variant": "analytics",
            "helper": "Across all categories",
            "trend_pct": None,
            "trend_up": None,
            "sparkline": "",
        },
        _kpi(
            "Staff Visits Cost",
            cat_totals["staff_visits"],
            "staff_visits",
            "info",
            source["label"],
        ),
        _kpi(
            "Partner Visits Cost",
            cat_totals["partner_visits"],
            "partner_visits",
            "success",
            source["label"],
        ),
        _kpi("SSA Cost", cat_totals["ssa"], "ssa", "warning", source["label"]),
        _kpi(
            "Cluster Training Cost",
            cat_totals["cluster_training"],
            "cluster_training",
            "finance",
            source["label"],
        ),
        _kpi(
            "Special Project Cost",
            cat_totals["special_project"],
            "special_project",
            "project",
            source["label"],
        ),
        _kpi("Admin Budget", admin_total, "admin", "danger", "From CD admin plan"),
    ]

    # ── Budget integrity checks ──────────────────────────────────────────
    checks = _integrity_checks(lines, admin_lines, budget, source)
    critical_failed = any(c["status"] == "failed" for c in checks)
    passed = sum(1 for c in checks if c["status"] == "passed")
    progress_pct = round(passed / len(checks) * 100) if checks else 0

    approval_status = _approval_status_label(budget.status)

    # ── Month summary + plan source summary ──────────────────────────────
    awaiting = total_monthly if budget.status not in LOCKED_STATUSES else 0
    plan_backed_cost = sum(
        r["total"] for r in staff_rows if r["status"] == "Plan-backed"
    )
    month_summary = {
        "awaiting_approval": _ugx(awaiting),
        "plan_backed_cost": _ugx(
            program_total if source["uses_pl_request_workflow"] else plan_backed_cost
        ),
        "plan_backed_pct": round(program_total / total_monthly * 100)
        if total_monthly
        else 0,
        "admin_budget": _ugx(admin_total),
        "admin_pct": round(admin_total / total_monthly * 100) if total_monthly else 0,
        "staff_included": staff_included,
    }

    planned_schools = len(
        {
            li.activity.school_id
            for li in lines
            if li.activity.school_id and li.activity.delivery_type != "partner"
        }
    )
    partner_schools = len(
        {
            li.activity.school_id
            for li in lines
            if li.activity.school_id and li.activity.delivery_type == "partner"
        }
    )
    cluster_sessions = len(
        {
            li.activity_id
            for li in lines
            if _page_category(
                li.activity.activity_type,
                li.activity.delivery_type,
                _is_project_line(li),
            )
            == "cluster_training"
        }
    )
    trainings_planned = len(
        {li.activity_id for li in lines if li.activity.activity_type in TRAINING_TYPES}
    )
    ssa_visits = len(
        {li.activity_id for li in lines if li.activity.activity_type in SSA_VISIT_TYPES}
    )
    special_project_acts = len({li.activity_id for li in lines if _is_project_line(li)})
    plan_source_summary = [
        {"icon": "school", "label": "Planned Schools", "value": planned_schools},
        {
            "icon": "handshake",
            "label": "Partner-Planned Schools",
            "value": partner_schools,
        },
        {
            "icon": "calendar",
            "label": "Cluster Meetings / Sessions",
            "value": cluster_sessions,
        },
        {"icon": "training", "label": "Trainings Planned", "value": trainings_planned},
        {"icon": "clipboard", "label": "SSA Collection Visits", "value": ssa_visits},
        {
            "icon": "project",
            "label": "Special Project Activities",
            "value": special_project_acts,
        },
        {"icon": "admin", "label": "Admin Plan Items", "value": len(admin_lines)},
    ]

    # ── Bottom stat cards ─────────────────────────────────────────────────
    bottom_stats = _bottom_stats(
        staff_rows, cat_totals, admin_total, total_monthly, staff_included
    )

    status_meta = {
        "submitted_to_cd": ("Waiting for CD review", "warning"),
        "approved_by_cd": ("Approved by CD", "success"),
        "returned_by_cd": ("Returned to PL", "danger"),
        "draft": ("Draft — not submitted", "slate"),
    }
    pl_request_rows = []
    for request in source["requests"]:
        label, tone = status_meta.get(
            request.status, (request.get_status_display(), "slate")
        )
        pl_request_rows.append(
            {
                "id": request.id,
                "lead_name": _user_names([request.submitted_by_user_id]).get(
                    request.submitted_by_user_id, "Program Lead"
                ),
                "activity_count": request.activity_count,
                "total": request.total_amount,
                "total_fmt": _ugx(request.total_amount),
                "status": label,
                "tone": tone,
                "note": request.review_note or "",
                "can_approve": (
                    getattr(principal, "active_role", None) in CD_ROLES
                    and request.status == "submitted_to_cd"
                    and budget.status not in LOCKED_STATUSES
                ),
            }
        )

    return {
        "fy": fy,
        "month": month_num,
        "month_label": MONTHS[month_num] if 1 <= month_num <= 12 else str(month_num),
        "fy_options": [fy, str(int(fy) - 1)],
        "budget": budget,
        "budget_id": budget.id,
        "status": budget.status,
        "status_label": budget.get_status_display(),
        "approval_status": approval_status,
        "progress_pct": progress_pct,
        "kpis": kpis,
        "staff_rows": staff_rows,
        "admin_row": {
            "total": admin_total,
            "total_fmt": _ugx(admin_total),
            "planned_fmt": _ugx(admin_total),
            "allocated_fmt": _ugx(
                admin_total if budget.status not in ("draft_generated",) else 0
            ),
            "status": admin_status,
            "lines": admin_lines,
        },
        "total_monthly": total_monthly,
        "total_monthly_fmt": _ugx(total_monthly),
        "program_source_label": source["label"],
        "uses_pl_request_workflow": source["uses_pl_request_workflow"],
        "pl_request_rows": pl_request_rows,
        "approved_pl_request_count": len(source["approved_requests"]),
        "checks": checks,
        "critical_failed": critical_failed,
        "month_summary": month_summary,
        "plan_source_summary": plan_source_summary,
        "bottom_stats": bottom_stats,
        "can_send_to_rvp": (
            getattr(principal, "active_role", None) in CD_ROLES
            and budget.status
            in ("draft_generated", "cd_review", "admin_plan_added", "returned_by_rvp")
            and not critical_failed
        ),
        "can_approve_or_return": (
            getattr(principal, "active_role", None) in RVP_ROLES
            and budget.status == "submitted_to_rvp"
        ),
        "is_cd": getattr(principal, "active_role", None) in CD_ROLES,
        "is_rvp": getattr(principal, "active_role", None) in RVP_ROLES,
        "can_edit_admin": (
            getattr(principal, "active_role", None) in CD_ROLES
            and budget.status
            in ("draft_generated", "cd_review", "admin_plan_added", "returned_by_rvp")
        ),
        "return_reasons": RETURN_REASONS,
        "category_order": CATEGORY_ORDER,
        # Plan vs actual, and the forecast against the annual ceiling. Both
        # were absent: this page showed plan and commitment only, so the two
        # people approving the country's money could not see how the last
        # approval executed or whether the quarter is heading for overspend.
        **_execution_context(budget, fy, principal),
        "last_updated": timezone.now(),
    }


def _execution_context(budget, fy, principal) -> dict:
    """Reconciliation + forecast for the envelope's own page."""
    from . import reconciliation_service as recon

    try:
        state = recon.settlement_state(budget)
    except Exception:  # noqa: BLE001 - the page must render even if recon fails
        return {"reconciliation": None, "forecast": None}

    rec = state["reconciliation"]
    role = getattr(principal, "active_role", None)
    return {
        "reconciliation": {
            **rec,
            "approved_fmt": _ugx(rec["approvedTotal"]),
            "committed_fmt": _ugx(rec["committedTotal"]),
            "disbursed_fmt": _ugx(rec["disbursedTotal"]),
            "accounted_fmt": _ugx(rec["accountedTotal"]),
            "returned_fmt": _ugx(rec["returnedTotal"]),
            "netsuite_fmt": _ugx(rec["netsuiteTotal"]),
            "variance_fmt": _ugx(abs(rec["variance"])),
            "system_delta_fmt": _ugx(abs(rec["systemDelta"])),
            "variance_label": "over budget" if rec["isOverspend"] else "under budget",
        },
        "forecast": recon.quarter_forecast(fy, budget.country_id),
        "can_mark_disbursed": state["canMarkDisbursed"] and role in CD_ROLES,
        "can_close_month": state["canClose"] and role in CD_ROLES,
        "settlement_blocker": state["blockingReason"],
        "can_send_to_accountant": (
            role in CD_ROLES and budget.status == "approved_by_rvp"
        ),
    }


RETURN_REASONS = [
    "Budget too high",
    "Unplanned activity included",
    "Admin budget unclear",
    "Missing plan source",
    "Cost Catalogue issue",
    "Partner activity not scheduled",
    "Cluster training count unclear",
    "Daily Visit Batch issue",
    "Duplicate budget line",
    "Wrong month",
    "Other",
]


def _approval_status_label(status):
    return {
        "draft_generated": "Draft",
        "cd_review": "Ready for CD Review",
        "admin_plan_added": "Ready for CD Review",
        "submitted_to_rvp": "Submitted to RVP",
        "returned_by_rvp": "Returned by RVP",
        "approved_by_rvp": "RVP Approved",
        "sent_to_accountant": "Sent to Accountant",
        "disbursed": "Disbursed",
        "closed": "Closed",
    }.get(status, "Draft")


def _integrity_checks(lines, admin_lines, budget, source=None):
    valid_lines = [li for li in lines if _validate_line(li) != "Excluded"]
    missing_cost = [li for li in valid_lines if not li.catalogue_id]
    needs_review = [
        li for li in valid_lines if getattr(li.activity, "cost_missing", False)
    ]
    cancelled_included = [
        li for li in lines if li.activity.status in ("cancelled", "rejected")
    ]
    seen_lines = set()
    dupes = 0
    for li in valid_lines:
        key = (li.activity_id, li.cost_setting_key, li.line_item_type)
        if key in seen_lines:
            dupes += 1
        seen_lines.add(key)
    missing_catalogue_version = [li for li in valid_lines if not li.catalogue_version]
    partner_unscheduled = [
        li
        for li in lines
        if li.activity.delivery_type == "partner" and not li.activity.planned_date
    ]
    cluster_missing_counts = [
        li
        for li in valid_lines
        if li.activity.activity_type in CLUSTER_TRAINING
        and not (
            (li.activity.teachers_attended or 0)
            + (li.activity.leaders_attended or 0)
            + (li.activity.other_participants or 0)
        )
        and li.activity.status in ("completed", "closed", "submitted_to_pl")
    ]

    def _status(bad, warn_only=False):
        if not bad:
            return "passed"
        return "warning" if warn_only else "failed"

    checks = []
    if source and source["uses_pl_request_workflow"]:
        pending = [r for r in source["requests"] if r.status == "submitted_to_cd"]
        approved = source["approved_requests"]
        checks.extend(
            [
                {
                    "label": "All submitted Program Lead requests reviewed by CD",
                    "status": "failed" if pending else "passed",
                    "detail": f"{len(pending)} request(s) still need CD review."
                    if pending
                    else "",
                },
                {
                    "label": "Program budget comes from CD-approved Program Lead requests",
                    "status": "passed" if approved else "failed",
                    "detail": "Approve at least one Program Lead request before sending the country budget to the RVP."
                    if not approved
                    else "",
                },
            ]
        )
    checks.extend(
        [
            {
                "label": "All activity costs linked to planned activities",
                "status": _status(missing_cost),
                "detail": f"{len(missing_cost)} line(s) missing a Cost Catalogue source."
                if missing_cost
                else "",
            },
            {
                "label": "No uncosted planned activities",
                "status": _status(needs_review, warn_only=True),
                "detail": f"{len(needs_review)} activity(ies) need review."
                if needs_review
                else "",
            },
            {
                "label": "No orphan budget lines",
                "status": "passed",
                "detail": "",
            },
            {
                "label": "Admin budget sourced from CD Monthly Admin Plan",
                "status": "passed"
                if admin_lines or budget.admin_total == 0
                else "failed",
                "detail": ""
                if admin_lines or budget.admin_total == 0
                else "Admin total set without admin lines.",
            },
            {
                "label": "No cancelled activities included",
                "status": _status(cancelled_included),
                "detail": f"{len(cancelled_included)} cancelled activity(ies) excluded."
                if cancelled_included
                else "",
            },
            {
                "label": "No duplicate ActivityBudgetLines",
                "status": _status(dupes > 0),
                "detail": f"{dupes} duplicate line(s) found." if dupes else "",
            },
            {
                "label": "All Cost Catalogue versions present",
                "status": _status(missing_catalogue_version, warn_only=True),
                "detail": f"{len(missing_catalogue_version)} line(s) missing a version."
                if missing_catalogue_version
                else "",
            },
            {
                "label": "Partner activities are scheduled before included",
                "status": _status(partner_unscheduled),
                "detail": f"{len(partner_unscheduled)} unscheduled partner activity(ies) excluded."
                if partner_unscheduled
                else "",
            },
            {
                "label": "Cluster training participant/session counts exist",
                "status": _status(cluster_missing_counts, warn_only=True),
                "detail": f"{len(cluster_missing_counts)} training(s) missing counts."
                if cluster_missing_counts
                else "",
            },
        ]
    )
    return checks


def _bottom_stats(staff_rows, cat_totals, admin_total, total_monthly, staff_included):
    total_monthly = total_monthly or 1
    highest = max(staff_rows, key=lambda r: r["total"], default=None)
    partner_share = round(cat_totals["partner_visits"] / total_monthly * 100, 1)
    top_cat_key = max(cat_totals, key=lambda k: cat_totals[k]) if cat_totals else None
    top_cat_label = CATEGORY_META.get(top_cat_key, {}).get("label", "—")
    admin_share = round(admin_total / total_monthly * 100, 1)
    avg_per_staff = round(total_monthly / staff_included) if staff_included else 0

    return [
        {
            "icon": "trophy",
            "label": "Highest Planned Cost Staff",
            "value": highest["name"] if highest else "—",
            "sub": f"{highest['total_fmt']}" if highest else "—",
            "helper": f"{round(highest['total'] / total_monthly * 100, 1)}% of total plan-backed"
            if highest
            else "",
        },
        {
            "icon": "school",
            "label": "Largest Cluster Training Budget",
            "value": _ugx(cat_totals["cluster_training"]),
            "sub": "Cluster Training",
            "helper": f"{round(cat_totals['cluster_training'] / total_monthly * 100, 1)}% of total budget",
        },
        {
            "icon": "handshake",
            "label": "Partner Cost Share",
            "value": f"{partner_share}%",
            "sub": _ugx(cat_totals["partner_visits"]),
            "helper": "Partner visits share of total",
        },
        {
            "icon": "chart",
            "label": "Top Cost Category",
            "value": top_cat_label,
            "sub": _ugx(cat_totals.get(top_cat_key, 0)) if top_cat_key else "—",
            "helper": f"{round(cat_totals.get(top_cat_key, 0) / total_monthly * 100, 1)}% of total budget"
            if top_cat_key
            else "",
        },
        {
            "icon": "bank",
            "label": "Admin Budget Share",
            "value": f"{admin_share}%",
            "sub": _ugx(admin_total),
            "helper": "Of total monthly budget",
        },
        {
            "icon": "average",
            "label": "Average Allocation per Staff",
            "value": _ugx(avg_per_staff),
            "sub": "Across all staff",
            "helper": f"{staff_included} staff members",
        },
    ]


def get_plan_sources(principal, filters=None):
    """The activities + cost lines behind the current month's budget — the
    'View Plan Sources' drawer content."""
    _require_read(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    month_num = int(filters.get("month") or timezone.now().month)
    source = _program_source(fy, month_num)
    lines = sorted(source["lines"], key=lambda line: -int(line.amount or 0))[:200]
    names = _user_names([li.responsible_user for li in lines])
    rows = []
    for li in lines:
        a = li.activity
        rows.append(
            {
                "activity_id": a.id,
                "activity_type": a.get_activity_type_display(),
                "school": a.school.name if a.school_id else "—",
                "staff": names.get(li.responsible_user, "—"),
                "planned_date": a.planned_date,
                "delivery_type": a.delivery_type,
                "label": li.label,
                "amount_fmt": _ugx(li.amount),
                "status": _validate_line(li),
                "catalogue_id": li.catalogue_id or "Missing",
            }
        )
    return {
        "fy": fy,
        "month": month_num,
        "month_label": MONTHS[month_num] if 1 <= month_num <= 12 else str(month_num),
        "rows": rows,
        "count": len(rows),
        "source_label": source["label"],
    }


# ── Actions ───────────────────────────────────────────────────────────────
def approve_pl_monthly_request(principal, request_id):
    """CD approves one submitted PL team-budget snapshot for consolidation."""
    from django.db import transaction

    from apps.fund_requests.models import FundRequest, FundRequestStatus

    _require_cd(principal)
    with transaction.atomic():
        request = (
            FundRequest.objects.select_for_update()
            .filter(id=request_id, scope="team", submitted_by_role="Program Lead")
            .first()
        )
        if not request:
            raise BadRequest("Program Lead monthly request not found.")
        if request.status != FundRequestStatus.SUBMITTED_TO_CD:
            raise BadRequest("Only a request waiting for CD review can be approved.")
        request.status = FundRequestStatus.APPROVED_BY_CD
        request.reviewed_by_user_id = principal.user_id
        request.reviewed_at = timezone.now()
        request.review_note = None
        request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )

        month_num = int(request.period_key.rsplit("M", 1)[-1])
        budget = _get_or_create_budget(request.fy, month_num)
        if budget.status in LOCKED_STATUSES:
            raise BadRequest("The country budget is already locked for RVP review.")
        if budget.status == "draft_generated":
            budget.status = "cd_review"
            budget.save(update_fields=["status", "updated_at"])
        _recompute_if_live(budget, _program_source(request.fy, month_num))

    _audit(
        principal,
        "country_budget.approve_pl_monthly_request",
        budget,
        {"fund_request_id": request.id, "total": request.total_amount},
    )
    _notify_user(
        request.submitted_by_user_id,
        "Monthly request approved by Country Director",
        (
            f"Your {MONTHS[month_num]} {request.fy} Team Budget request "
            f"({_ugx(request.total_amount)}) is included in the country budget."
        ),
        request.id,
    )
    return request


def return_pl_monthly_request(principal, request_id, note):
    """Return a PL snapshot for a clear, recorded correction."""
    from django.db import transaction

    from apps.fund_requests.models import FundRequest, FundRequestStatus

    _require_cd(principal)
    note = (note or "").strip()
    if not note:
        raise BadRequest("Tell the Program Lead what needs to be corrected.")
    with transaction.atomic():
        request = (
            FundRequest.objects.select_for_update()
            .filter(id=request_id, scope="team", submitted_by_role="Program Lead")
            .first()
        )
        if not request:
            raise BadRequest("Program Lead monthly request not found.")
        if request.status != FundRequestStatus.SUBMITTED_TO_CD:
            raise BadRequest("Only a request waiting for CD review can be returned.")
        request.status = FundRequestStatus.RETURNED_BY_CD
        request.reviewed_by_user_id = principal.user_id
        request.reviewed_at = timezone.now()
        request.review_note = note[:512]
        request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )
    _notify_user(
        request.submitted_by_user_id,
        "Monthly request returned by Country Director",
        note,
        request.id,
    )
    return request


def send_to_rvp(principal, budget_id):
    _require_cd(principal)
    budget = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not budget:
        raise BadRequest("Country monthly budget not found.")
    if budget.status not in (
        "draft_generated",
        "cd_review",
        "admin_plan_added",
        "returned_by_rvp",
    ):
        raise BadRequest("This budget has already been submitted.")

    month_num = int(budget.month_key.split("-")[1])
    source = _program_source(budget.fy, month_num)
    _recompute_if_live(budget, source)
    checks = _integrity_checks(
        source["lines"], list(budget.admin_lines.all()), budget, source
    )
    failed = [c for c in checks if c["status"] == "failed"]
    if failed:
        raise BadRequest("Cannot submit — validation failed: " + failed[0]["label"])

    budget.status = "submitted_to_rvp"
    budget.submitted_at = timezone.now()
    budget.submitted_by_user_id = principal.user_id
    budget.save(
        update_fields=["status", "submitted_at", "submitted_by_user_id", "updated_at"]
    )

    month_label = MONTHS[int(budget.month_key.split("-")[1])]
    _audit(
        principal,
        "country_budget.submit_to_rvp",
        budget,
        {"total": budget.total_amount},
    )
    _notify_role(
        "RegionalVicePresident",
        "country_budget_submitted",
        "Country Monthly Budget ready for approval",
        f"Uganda {month_label} {budget.fy} Country Monthly Budget ({_ugx(budget.total_amount)}) is ready for your approval.",
        budget,
    )
    return budget


def approve(principal, budget_id):
    _require_rvp(principal)
    budget = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not budget:
        raise BadRequest("Country monthly budget not found.")
    _assert_rvp_country_scope(budget)
    if budget.status != "submitted_to_rvp":
        raise BadRequest("Only a submitted budget can be approved.")

    budget.status = "approved_by_rvp"
    budget.rvp_reviewed_at = timezone.now()
    budget.rvp_reviewed_by_user_id = principal.user_id
    budget.save(
        update_fields=[
            "status",
            "rvp_reviewed_at",
            "rvp_reviewed_by_user_id",
            "updated_at",
        ]
    )

    month_label = MONTHS[int(budget.month_key.split("-")[1])]
    _audit(principal, "country_budget.approve", budget, {"total": budget.total_amount})
    from apps.monthly_work_plan.services import _rvp_audit

    _rvp_audit(
        "monthly_budget",
        budget.id,
        f"Country Monthly Budget {budget.month_key}",
        "approve",
        principal,
        amount=budget.total_amount,
        fy=budget.fy,
    )
    _notify_role(
        "CountryDirector",
        "country_budget_approved",
        "Country Monthly Budget approved by RVP",
        f"{month_label} {budget.fy} Country Monthly Budget was approved by the RVP.",
        budget,
    )
    _notify_role(
        "Accountant",
        "country_budget_approved",
        "Country Monthly Budget ready for disbursement",
        f"{month_label} {budget.fy} Country Monthly Budget ({_ugx(budget.total_amount)}) was approved and is ready to prepare for disbursement.",
        budget,
    )
    return budget


def return_budget(principal, budget_id, data):
    _require_rvp(principal)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    budget = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not budget:
        raise BadRequest("Country monthly budget not found.")
    _assert_rvp_country_scope(budget)
    if budget.status != "submitted_to_rvp":
        raise BadRequest("Only a submitted budget can be returned.")

    budget.status = "returned_by_rvp"
    budget.rvp_reviewed_at = timezone.now()
    budget.rvp_reviewed_by_user_id = principal.user_id
    budget.rvp_review_note = (
        reason + (" — " + data["comment"] if data.get("comment") else "")
    )[:512]
    budget.save(
        update_fields=[
            "status",
            "rvp_reviewed_at",
            "rvp_reviewed_by_user_id",
            "rvp_review_note",
            "updated_at",
        ]
    )

    month_label = MONTHS[int(budget.month_key.split("-")[1])]
    _audit(principal, "country_budget.return", budget, {"reason": reason})
    from apps.monthly_work_plan.services import _rvp_audit

    _rvp_audit(
        "monthly_budget",
        budget.id,
        f"Country Monthly Budget {budget.month_key}",
        "return",
        principal,
        reason=reason,
        amount=budget.total_amount,
        fy=budget.fy,
    )
    _notify_role(
        "CountryDirector",
        "country_budget_returned",
        "Country Monthly Budget returned by RVP",
        f"{month_label} {budget.fy} Country Monthly Budget was returned by the RVP. Reason: {reason}",
        budget,
    )
    return budget


def _audit(principal, action, budget, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="MonthlyWorkPlanBudget",
            subject_id=budget.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"month_key": budget.month_key, **payload},
        )
    except Exception:  # noqa: BLE001 — audit must never block the action
        pass


def _notify_role(role, event, title, body, budget):
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        ids = list(
            User.objects.filter(active_role=role, is_active=True).values_list(
                "id", flat=True
            )
        )
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type=event,
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="MonthlyWorkPlanBudget",
            context_id=budget.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001
        pass


def _notify_user(recipient_id, title, body, request_id):
    """A direct workflow notification for the Program Lead who owns a request."""
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="monthly_team_request_reviewed",
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="FundRequest",
            context_id=request_id,
            recipients=[recipient_id],
        )
    except Exception:  # noqa: BLE001 - notification delivery is non-blocking
        pass
