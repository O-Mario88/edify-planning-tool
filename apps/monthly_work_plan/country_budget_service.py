"""General Budget — the CD's finance control page for a selected month.

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

from apps.core.metrics import (
    render_precomputed_metric_item,
    render_precomputed_metric_for_source,
)

from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
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

from .models import MonthlyBudgetSubmissionSnapshot, MonthlyWorkPlanBudget
from . import services as mwp

# Authority tuples, deliberately WITHOUT "Admin". The permission matrix
# withholds the country-budget authorities from the super-role
# (ADMIN_EXCLUDED_PERMISSIONS), and a role tuple that names Admin re-grants
# what the matrix just removed — the bypass the 2026-08 audit found on the
# disbursement and IA-verify doors. Admin still READS every country budget
# through READ_ROLES below; observing a control is not exercising it.
CD_ROLES = ("CountryDirector",)
RVP_ROLES = ("RegionalVicePresident",)
READ_ROLES = (
    "CountryDirector",
    "RegionalVicePresident",
    "Accountant",
    "ImpactAssessment",
    "Admin",
)

# Every General Budget period this module generates is tagged with this
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
            "Only CD, RVP, Accountant, IA, or Admin may view the General Budget."
        )


def _submitter_names(user_ids) -> dict[str, str]:
    """Display names for the people who submitted these budgets.

    ``submitted_by_user_id`` holds a User id, but the same field elsewhere in
    the platform has been written with a StaffProfile CUID, so both id spaces
    are resolved and an unmatched id simply falls back to itself rather than
    disappearing -- an unresolvable submitter is still better evidence than a
    blank cell on a page someone approves money from.
    """
    from apps.accounts.models import StaffProfile, User

    wanted = {uid for uid in user_ids if uid}
    if not wanted:
        return {}

    names = {u.id: u.name for u in User.objects.filter(id__in=wanted) if u.name}
    unresolved = wanted - set(names)
    if unresolved:
        names.update(
            {
                sp.id: sp.user.name
                for sp in StaffProfile.objects.filter(id__in=unresolved).select_related(
                    "user"
                )
                if sp.user_id and sp.user.name
            }
        )
    return names


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
    delivery type: the General Budget needs a clean, undiluted view of
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
        .exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .exclude(activity__delivery_type="partner", activity__planned_date__isnull=True)
        .select_related("activity", "activity__school")
    )


def _team_monthly_requests(fy, month_num):
    """Program Lead team-budget snapshots for the selected month.

    The presence of even one of these requests turns on the deliberate monthly
    submission workflow. That means the General Budget can never quietly fall
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
    """Return every valid scheduled planned-activity cost line for the month.

    Monthly fund requests remain workflow snapshots, but they are not a second
    budget source and cannot hide planned work from the General Budget. The
    activity schedule cost line is the authoritative amount everywhere.
    """
    lines = list(_valid_lines_qs(fy, month_num))
    return {
        "uses_pl_request_workflow": False,
        "requests": [],
        "approved_requests": [],
        "lines": lines,
        "program_total": sum(int(line.amount or 0) for line in lines),
        "activity_count": len({line.activity_id for line in lines}),
        "label": "Scheduled planned activities",
    }


def _envelope_from_source(source) -> dict:
    """Calculate the two governed funding layers for one calendar month.

    Staff schedule lines carry the Minimum Viable Cost. Each line also stamps
    the exact catalogue version that supplied it, so the matching Country
    Operational Cost can be reconstructed without changing what staff saw or
    retroactively applying today's rate to an older plan. The full country
    amount is submitted to the RVP; the difference remains controlled country
    capacity rather than staff spending authority.
    """
    country_by_line = _reference_amounts_for_lines(source["lines"])
    included_lines = [
        line for line in source["lines"] if _validate_line(line) != "Excluded"
    ]
    missing = sum(1 for line in included_lines if country_by_line.get(line.id) is None)
    country_operational_total = sum(
        int(country_by_line.get(line.id) or 0) for line in included_lines
    )
    minimum_viable_total = int(source["program_total"] or 0)
    reserve_capacity = (
        0 if missing else max(0, country_operational_total - minimum_viable_total)
    )
    shortfall = (
        max(0, minimum_viable_total - country_operational_total) if not missing else 0
    )
    return {
        # Legacy keys remain while stored model/JSON field names are migrated
        # separately. Their values now carry the explicitly named two-layer
        # country policy below.
        "regionalStandardCeiling": country_operational_total,
        "operationalActivityRequirement": minimum_viable_total,
        "countryOperationalTotal": country_operational_total,
        "minimumViableTotal": minimum_viable_total,
        "maximumReserveCapacity": reserve_capacity,
        "countryFundingShortfall": shortfall,
        "referenceConfigurationMissingCount": missing,
    }


def _reference_amounts_for_lines(lines) -> dict:
    """Convert Minimum Viable schedule lines to Country Operational amounts.

    The conversion uses the immutable catalogue id/key stamped on each line.
    Proportional conversion preserves month-split and largest-remainder amounts
    exactly; it does not reprice an old plan from the newest catalogue.
    """
    from apps.budget.models import ActivityCostSnapshot, CostSetting

    included = [line for line in lines if _validate_line(line) != "Excluded"]
    catalogue_ids = {line.catalogue_id for line in included if line.catalogue_id}
    country_rates = {
        (row["catalogue_id"], row["key"]): int(row["unit_cost"])
        for row in CostSetting.objects.filter(catalogue_id__in=catalogue_ids).values(
            "catalogue_id", "key", "unit_cost"
        )
    }
    legacy_snapshots = {
        row["activity_id"]: row
        for row in ActivityCostSnapshot.objects.filter(
            activity_id__in={line.activity_id for line in included},
            is_current=True,
        ).values("activity_id", "reference_cost", "operational_cost")
    }
    result = {}
    for line in included:
        if not line.catalogue_id:
            result[line.id] = None
            continue
        base_key = (line.cost_setting_key or "").split("#", 1)[0]
        country_rate = country_rates.get((line.catalogue_id, base_key))
        if country_rate is None:
            # Backward compatibility for old/imported lines whose catalogue
            # id was stamped but whose historical component row is no longer
            # present. A legacy dual snapshot is preferable to inventing a
            # current rate; otherwise preserve the already-approved line.
            snapshot = legacy_snapshots.get(line.activity_id)
            if (
                snapshot
                and snapshot["reference_cost"] is not None
                and int(snapshot["operational_cost"] or 0) > 0
            ):
                result[line.id] = round(
                    int(line.amount or 0)
                    * int(snapshot["reference_cost"])
                    / int(snapshot["operational_cost"])
                )
            else:
                result[line.id] = int(line.amount or 0)
            continue
        minimum_rate = int(line.unit_cost or 0)
        minimum_amount = int(line.amount or 0)
        if minimum_rate > 0:
            result[line.id] = round(minimum_amount * country_rate / minimum_rate)
        else:
            result[line.id] = country_rate * int(line.quantity or 0)
    return result


def _apply_live_envelope(budget, source) -> dict:
    """Refresh the governed full Country Operational Cost request.

    Staff implementation authority remains the Minimum Viable Cost. The CD
    submits the complete Country Operational Cost to the RVP, so every positive
    difference is explicitly classified as undisbursed strategic reserve rather
    than being omitted or presented as staff activity need.
    """
    envelope = _envelope_from_source(source)
    # The active admin lines are the source of truth. Some imports and repair
    # paths create them directly, so never trust a stale cached parent total.
    budget.admin_total = sum(
        int(total or 0)
        for total in budget.admin_lines.filter(status="active").values_list(
            "total_cost", flat=True
        )
    )
    capacity = envelope["maximumReserveCapacity"]
    reserve_requested = capacity
    deferred = 0

    budget.regional_standard_ceiling = envelope["regionalStandardCeiling"]
    budget.operational_activity_requirement = envelope["operationalActivityRequirement"]
    budget.strategic_reserve_requested = reserve_requested
    budget.deferred_amount = deferred
    budget.country_funding_shortfall = envelope["countryFundingShortfall"]
    budget.reference_configuration_missing_count = envelope[
        "referenceConfigurationMissingCount"
    ]
    # Administrative commitments remain an explicit, non-activity exception.
    # They are requested in addition to the governed activity allocation and
    # are never disguised as regional-standard activity need.
    budget.total_amount = (
        int(budget.operational_activity_requirement)
        + int(budget.admin_total or 0)
        + reserve_requested
    )
    budget.save(
        update_fields=[
            "regional_standard_ceiling",
            "operational_activity_requirement",
            "strategic_reserve_requested",
            "deferred_amount",
            "country_funding_shortfall",
            "reference_configuration_missing_count",
            "admin_total",
            "total_amount",
            "updated_at",
        ]
    )
    return {
        **envelope,
        "strategicReserveRequested": reserve_requested,
        "deferredAmount": deferred,
        "approvedFixedCommitments": int(budget.admin_total or 0),
        "totalCountryRequest": int(budget.total_amount),
        "reserveSelectionValid": reserve_requested == capacity,
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
        _apply_live_envelope(budget, source)
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
            .exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
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
    # M2 — count only status="active" admin lines, matching budget_workspace.
    admin_lines = list(budget.admin_lines.filter(status="active"))
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
    total_monthly = int(budget.total_amount)
    reserve_capacity = (
        0
        if budget.reference_configuration_missing_count
        else max(
            0,
            int(budget.regional_standard_ceiling)
            - int(budget.operational_activity_requirement),
        )
    )
    country_envelope = {
        "regionalStandardCeiling": int(budget.regional_standard_ceiling),
        "operationalActivityRequirement": int(budget.operational_activity_requirement),
        "countryOperationalTotal": int(budget.regional_standard_ceiling),
        "minimumViableTotal": int(budget.operational_activity_requirement),
        "maximumReserveCapacity": reserve_capacity,
        "strategicReserveRequested": int(budget.strategic_reserve_requested),
        "deferredAmount": int(budget.deferred_amount),
        "countryFundingShortfall": int(budget.country_funding_shortfall),
        "referenceConfigurationMissingCount": int(
            budget.reference_configuration_missing_count
        ),
        "approvedFixedCommitments": int(admin_total),
        "totalCountryRequest": int(budget.total_amount),
        "reserveSelectionValid": int(budget.strategic_reserve_requested)
        <= reserve_capacity,
    }
    from apps.budget.executable_budget_service import monthly_executable_budget

    executable_budget = monthly_executable_budget(fy=fy, month=month_num)
    if not has_permission(principal, Permission.ACTIVITY_REFERENCE_COST_VIEW.value):
        # IA/Admin may read the operational country budget for their existing
        # duties, but reference benchmarks are a distinct restricted layer.
        executable_budget = {
            key: value
            for key, value in executable_budget.items()
            if key
            not in {
                "referenceForecast",
                "referenceConfigurationMissingCount",
                "potentialCostAvoidance",
                "operationalPremium",
            }
        }
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
        return render_precomputed_metric_for_source(
            "apps.monthly_work_plan.country_budget_service:get_country_monthly_budget._kpi",
            label,
            _ugx(value_int),
            variant=variant,
            helper=helper,
            trend_pct=t["pct"],
            trend_up=t["up"],
            sparkline=t["sparkline"],
        )

    kpis = [
        _kpi(
            "General Budget Total",
            total_monthly,
            "total_all",
            "primary",
            source["label"],
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_staff_included",
            str(staff_included),
            variant="info",
            helper="All staff members",
            trend_pct=None,
            trend_up=None,
            sparkline="",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_total_planned_activities",
            str(total_activities),
            variant="analytics",
            helper="Across all categories",
            trend_pct=None,
            trend_up=None,
            sparkline="",
        ),
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
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_planned_schools",
            planned_schools,
            icon="school",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_partner_planned_schools",
            partner_schools,
            icon="handshake",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_cluster_meetings_sessions",
            cluster_sessions,
            icon="calendar",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_trainings_planned",
            trainings_planned,
            icon="training",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_ssa_collection_visits",
            ssa_visits,
            icon="clipboard",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_special_project_activities",
            special_project_acts,
            icon="project",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_admin_plan_items",
            len(admin_lines),
            icon="admin",
        ),
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
        "country_envelope": country_envelope,
        "monthly_executable_budget": executable_budget,
        "can_view_reference_cost": has_permission(
            principal, Permission.ACTIVITY_REFERENCE_COST_VIEW.value
        ),
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
        # §10 — an earlier month still awaiting RVP review must NOT freeze the
        # active month's preparation (periods are independent). Surface it as a
        # compact warning so the CD knows the prior month is pending, without
        # disabling the current month's Submit button.
        "prior_month_pending": _prior_month_pending(fy, budget.month_key),
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
    approved_operating_limit = (
        int(budget.operational_activity_requirement or 0)
        if budget.status
        in {"approved_by_rvp", "sent_to_accountant", "disbursed", "closed"}
        else 0
    )
    return {
        "reconciliation": {
            **rec,
            # The overall approved envelope also contains an explicit reserve
            # and may contain fixed administrative commitments. Never label
            # that larger number as staff operating authority.
            "approved_fmt": _ugx(approved_operating_limit),
            "committed_fmt": _ugx(rec["committedTotal"]),
            "disbursed_fmt": _ugx(rec["disbursedTotal"]),
            "accounted_fmt": _ugx(rec["accountedTotal"]),
            "returned_fmt": _ugx(rec["returnedTotal"]),
            "reimbursed_fmt": _ugx(rec["reimbursedTotal"]),
            "netsuite_fmt": _ugx(rec["netsuiteTotal"]),
            "variance_fmt": _ugx(abs(rec["variance"])),
            "system_delta_fmt": _ugx(abs(rec["systemDelta"])),
            "unattributed_fmt": _ugx(rec["unattributedTotal"]),
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


def _prior_month_pending(fy, current_month_key):
    """Any earlier submitted-to-RVP month in this FY (§10 warning).

    Periods are independent, so a prior pending month never blocks preparing
    the current one — but the CD should see it flagged so nothing slips
    through the cracks. Returns ``None`` or ``{month_label}``.
    """
    prior = (
        MonthlyWorkPlanBudget.objects.filter(
            fy=fy,
            status="submitted_to_rvp",
            month_key__lt=current_month_key,
        )
        .order_by("-month_key")
        .first()
    )
    if not prior:
        return None
    month_num = int(prior.month_key.split("-")[1])
    return MONTHS[month_num] if 1 <= month_num <= 12 else prior.month_key


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

    # M7 — these checks must interrogate the month's RAW cost-line set, not
    # the pre-filtered `lines` queryset: testing "no cancelled lines" against
    # a queryset that already excluded cancelled lines is vacuously true.
    # A bad line only fails the check when the stored program_total actually
    # still carries money beyond the clean (fully valid) line set — i.e. the
    # bad money is genuinely counted, not already excluded by a recompute.
    from django.db.models import Q

    from apps.activities.models import ActivityScheduleCostLine

    raw_lines = []
    try:
        _month_num = int(str(budget.month_key).split("-")[1])
    except (IndexError, ValueError, AttributeError):
        _month_num = None
    if _month_num is not None:
        raw_lines = list(
            ActivityScheduleCostLine.objects.filter(month=_month_num)
            .filter(Q(activity__fy=budget.fy) | Q(fiscal_year=budget.fy))
            .select_related("activity")
        )

    def _line_clean(li):
        a = li.activity
        return (
            a is not None
            and a.deleted_at is None
            and a.status not in ("cancelled", "rejected", "deferred")
            and not (a.delivery_type == "partner" and not a.planned_date)
        )

    clean_program_total = sum(
        int(li.amount or 0) for li in raw_lines if _line_clean(li)
    )
    stored_program_total = int(budget.program_total or 0)
    overcounted = stored_program_total > clean_program_total

    orphan_lines = [
        li
        for li in raw_lines
        if li.activity is None or li.activity.deleted_at is not None
    ]
    cancelled_included = [
        li
        for li in raw_lines
        if li.activity is not None
        and li.activity.deleted_at is None
        and li.activity.status in ("cancelled", "rejected", "deferred")
    ]
    partner_precosted = [
        li
        for li in raw_lines
        if li.activity is not None
        and li.activity.deleted_at is None
        and li.activity.delivery_type == "partner"
        and li.activity.status == "assigned_to_partner"
        and li.activity.planned_date is not None
    ]
    seen_lines = set()
    dupes = 0
    for li in valid_lines:
        key = (li.activity_id, li.cost_setting_key, li.line_item_type)
        if key in seen_lines:
            dupes += 1
        seen_lines.add(key)
    missing_catalogue_version = [li for li in valid_lines if not li.catalogue_version]
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
                    "detail": "Approve at least one Program Lead request before sending the General Budget to the RVP."
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
                # M7 — was hardcoded "passed". A line whose activity is
                # soft-deleted while its money still sits in the stored
                # program_total is exactly the orphan this check exists for.
                "label": "No orphan budget lines",
                "status": _status(orphan_lines and overcounted),
                "detail": (
                    f"{len(orphan_lines)} line(s) belong to deleted activities "
                    "but their money is still in the stored program total."
                )
                if (orphan_lines and overcounted)
                else "",
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
                # M7 — previously tested a queryset that had already excluded
                # cancelled lines (vacuous). Now fails when cancelled /
                # rejected / deferred activity money is still counted in the
                # stored program_total.
                "label": "No cancelled activities included",
                "status": _status(cancelled_included and overcounted),
                "detail": (
                    f"{len(cancelled_included)} cancelled/rejected/deferred "
                    "activity line(s) are still counted in the stored program "
                    "total."
                )
                if (cancelled_included and overcounted)
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
                # M7 — previously tested lines the source queryset had already
                # excluded (vacuous). The real anomaly: a partner-delivery
                # line costed and counted while its activity is still only
                # assigned_to_partner — money in the budget before the
                # partner ever scheduled the work.
                "label": "Partner activities are scheduled before included",
                "status": _status(partner_precosted),
                "detail": (
                    f"{len(partner_precosted)} partner line(s) costed while "
                    "the activity is still assigned_to_partner (not yet "
                    "scheduled by the partner)."
                )
                if partner_precosted
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
    reserve_capacity = (
        0
        if budget.reference_configuration_missing_count
        else max(
            0,
            int(budget.regional_standard_ceiling)
            - int(budget.operational_activity_requirement),
        )
    )
    reserve_over_capacity = int(budget.strategic_reserve_requested) > reserve_capacity
    if budget.country_funding_shortfall:
        allocation_balances = (
            int(budget.operational_activity_requirement)
            == int(budget.regional_standard_ceiling)
            + int(budget.country_funding_shortfall)
            and int(budget.strategic_reserve_requested) == 0
            and int(budget.deferred_amount) == 0
        )
    else:
        allocation_balances = int(budget.operational_activity_requirement) + int(
            budget.strategic_reserve_requested
        ) + int(budget.deferred_amount) == int(budget.regional_standard_ceiling)
    checks.extend(
        [
            {
                "label": "Country Operational Cost configured for scheduled activities",
                "status": (
                    "warning"
                    if budget.reference_configuration_missing_count
                    else "passed"
                ),
                "detail": (
                    f"{budget.reference_configuration_missing_count} activity(ies) "
                    "do not yet have a Country Operational Cost source. Reserve "
                    "capacity is unavailable until the CD completes the catalogue."
                    if budget.reference_configuration_missing_count
                    else ""
                ),
            },
            {
                "label": "Strategic reserve request stays within available capacity",
                "status": "failed" if reserve_over_capacity else "passed",
                "detail": (
                    f"Requested reserve is {_ugx(budget.strategic_reserve_requested)}; "
                    f"maximum capacity is {_ugx(reserve_capacity)}."
                    if reserve_over_capacity
                    else ""
                ),
            },
            {
                "label": "Country envelope balances to Country Operational Cost",
                # Missing reference configuration cannot balance truthfully; it
                # remains a management warning, not fabricated benchmark money.
                "status": (
                    "warning"
                    if budget.reference_configuration_missing_count
                    else ("passed" if allocation_balances else "failed")
                ),
                "detail": (
                    "Operational allocation, reserve and deferred amount must "
                    "equal the Country Operational Cost submitted to the RVP."
                    if not allocation_balances
                    else ""
                ),
            },
        ]
    )
    # Locked-month snapshot invariant — a budget in any LOCKED status was, by
    # definition, submitted; the guarded submit path always writes an
    # immutable MonthlyBudgetSubmissionSnapshot. A locked month with zero
    # snapshots reached its status through a hole (the old unguarded
    # _transition) and its "approved" figures are unverifiable.
    locked_without_snapshot = (
        budget.status in LOCKED_STATUSES
        and budget.pk is not None
        and not budget.snapshots.exists()
    )
    checks.append(
        {
            "label": "Locked month has an immutable submission snapshot",
            "status": "failed" if locked_without_snapshot else "passed",
            "detail": (
                f"Status is '{budget.status}' but no submission snapshot "
                "exists — this month bypassed the guarded submit path. Run "
                "`manage.py repair_monthly_budget_totals --apply` to revert "
                "it to draft for a proper resubmission."
            )
            if locked_without_snapshot
            else "",
        }
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
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_highest_planned_cost_staff",
            highest["name"] if highest else "—",
            icon="trophy",
            sub=f"{highest['total_fmt']}" if highest else "—",
            helper=f"{round(highest['total'] / total_monthly * 100, 1)}% of total plan-backed"
            if highest
            else "",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_largest_cluster_training_budget",
            _ugx(cat_totals["cluster_training"]),
            icon="school",
            sub="Cluster Training",
            helper=f"{round(cat_totals['cluster_training'] / total_monthly * 100, 1)}% of total budget",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_partner_cost_share",
            f"{partner_share}%",
            icon="handshake",
            sub=_ugx(cat_totals["partner_visits"]),
            helper="Partner visits share of total",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_top_cost_category",
            top_cat_label,
            icon="chart",
            sub=_ugx(cat_totals.get(top_cat_key, 0)) if top_cat_key else "—",
            helper=f"{round(cat_totals.get(top_cat_key, 0) / total_monthly * 100, 1)}% of total budget"
            if top_cat_key
            else "",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_admin_budget_share",
            f"{admin_share}%",
            icon="bank",
            sub=_ugx(admin_total),
            helper="Of total monthly budget",
        ),
        render_precomputed_metric_item(
            "monthly_work_plan_country_budget_service_average_allocation_per_staff",
            _ugx(avg_per_staff),
            icon="average",
            sub="Across all staff",
            helper=f"{staff_included} staff members",
        ),
    ]


def list_submitted_budgets(principal, filters=None):
    """Submitted/locked country budgets for an FY — the 'Submitted Budgets' list.

    Each submitted month moves out of the active budget-preparation workspace
    and into this history view, showing Month, FY, submitted amount, submitted
    by, submitted date, current RVP status, version and a View-Details link.
    Data comes from the locked MonthlyWorkPlanBudget rows joined to their
    latest immutable snapshot, never from live cost lines.
    """
    _require_read(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    budgets = MonthlyWorkPlanBudget.objects.filter(
        fy=fy, status__in=LOCKED_STATUSES
    ).order_by("-month_key")

    # "Submitted by" rendered the raw stored id ("cmrabe4td00k76ukgkdlu"), so
    # the RVP approving a country budget could not see who sent it. Resolved
    # once for the whole page rather than per row.
    submitter_names = _submitter_names([b.submitted_by_user_id for b in budgets])

    rows = []
    for b in budgets:
        month_num = int(b.month_key.split("-")[1])
        rows.append(
            {
                "budget_id": b.id,
                "month_key": b.month_key,
                "month_label": MONTHS[month_num]
                if 1 <= month_num <= 12
                else str(month_num),
                "fy": b.fy,
                "total_amount": b.total_amount,
                "total_amount_fmt": _ugx(b.total_amount),
                "submitted_at": b.submitted_at,
                "submitted_by_user_id": b.submitted_by_user_id,
                "submitted_by_name": submitter_names.get(b.submitted_by_user_id),
                "status": b.status,
                "status_label": b.get_status_display(),
                "version": b.submission_version,
            }
        )

    # The page carried a box labelled "Search submitted budgets…" that was
    # wired to nothing, so it fell through to the platform's global search and
    # navigated the user off the page entirely — a control that named a dataset
    # it never queried.
    #
    # The rows are a small, already-materialised list for one FY, so this
    # filters them in place rather than adding a second database round trip.
    # Month label and status label are what the page actually displays, so they
    # are what a typed query is matched against.
    search_q = str(filters.get("q") or "").strip().casefold()
    if search_q:
        rows = [
            row
            for row in rows
            if search_q in row["month_label"].casefold()
            or search_q in str(row["fy"]).casefold()
            or search_q in row["status_label"].casefold()
            or search_q in row["month_key"].casefold()
        ]

    return {"fy": fy, "rows": rows, "q": filters.get("q") or ""}


def get_submission_detail(principal, budget_id):
    """The read-only detail of one submitted month, rendered from its snapshot.

    The submitted month's breakdown must never drift with later activity/cost
    changes, so this always reads the latest immutable snapshot (staff_rows,
    line_items, admin_lines, totals) — never the live cost lines.
    """
    _require_read(principal)
    budget = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not budget:
        raise BadRequest("Country monthly budget not found.")
    snapshot = budget.snapshots.first()  # ordering = ["-version"]
    month_num = int(budget.month_key.split("-")[1])
    financial_record = snapshot or budget
    reserve_capacity = (
        0
        if financial_record.reference_configuration_missing_count
        else max(
            0,
            int(financial_record.regional_standard_ceiling)
            - int(financial_record.operational_activity_requirement),
        )
    )
    return {
        "budget_id": budget.id,
        "month_key": budget.month_key,
        "month_label": MONTHS[month_num] if 1 <= month_num <= 12 else str(month_num),
        "fy": budget.fy,
        "status": budget.status,
        "status_label": budget.get_status_display(),
        "submitted_at": budget.submitted_at,
        "submitted_by_user_id": budget.submitted_by_user_id,
        "submitted_by_name": _submitter_names([budget.submitted_by_user_id]).get(
            budget.submitted_by_user_id
        ),
        "version": budget.submission_version,
        "total_amount": budget.total_amount,
        "total_amount_fmt": _ugx(budget.total_amount),
        "program_total": budget.program_total,
        "program_total_fmt": _ugx(budget.program_total),
        "admin_total": budget.admin_total,
        "admin_total_fmt": _ugx(budget.admin_total),
        "country_envelope": {
            "regionalStandardCeiling": int(financial_record.regional_standard_ceiling),
            "operationalActivityRequirement": int(
                financial_record.operational_activity_requirement
            ),
            "countryOperationalTotal": int(financial_record.regional_standard_ceiling),
            "minimumViableTotal": int(
                financial_record.operational_activity_requirement
            ),
            "maximumReserveCapacity": reserve_capacity,
            "strategicReserveRequested": int(
                financial_record.strategic_reserve_requested
            ),
            "deferredAmount": int(financial_record.deferred_amount),
            "countryFundingShortfall": int(financial_record.country_funding_shortfall),
            "referenceConfigurationMissingCount": int(
                financial_record.reference_configuration_missing_count
            ),
            "approvedFixedCommitments": int(financial_record.admin_total),
            "totalCountryRequest": int(financial_record.total_amount),
        },
        "category_order": CATEGORY_ORDER,
        "staff_rows": snapshot.staff_rows if snapshot else [],
        "line_items": snapshot.line_items if snapshot else [],
        "admin_lines": snapshot.admin_lines if snapshot else [],
    }


def get_plan_sources(principal, filters=None):
    """The activities + cost lines behind the current month's budget — the
    'View Plan Sources' drawer content."""
    _require_read(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    month_num = int(filters.get("month") or timezone.now().month)
    source = _program_source(fy, month_num)
    lines = source["lines"]
    names = _user_names([li.responsible_user for li in lines])
    from apps.budget.models import ActivityCostSnapshot

    activity_ids = {line.activity_id for line in lines}
    snapshots = {
        snapshot.activity_id: snapshot
        for snapshot in ActivityCostSnapshot.objects.filter(
            activity_id__in=activity_ids, is_current=True
        )
    }
    lines_by_activity: dict[str, list] = {}
    for line in lines:
        lines_by_activity.setdefault(line.activity_id, []).append(line)
    country_by_line = _reference_amounts_for_lines(lines)
    budget = _get_or_create_budget(fy, month_num)
    rows = []
    for activity_id, activity_lines in lines_by_activity.items():
        li = activity_lines[0]
        a = li.activity
        operational = sum(int(line.amount or 0) for line in activity_lines)
        snapshot = snapshots.get(activity_id)
        country_amounts = [country_by_line.get(line.id) for line in activity_lines]
        reference = (
            None
            if any(amount is None for amount in country_amounts)
            else sum(int(amount or 0) for amount in country_amounts)
        )
        difference = max(0, int(reference or 0) - operational)
        if reference is None:
            viability = "Country operational cost required"
        elif snapshot is not None and snapshot.missing_configuration:
            viability = "Cost review required"
        elif snapshot is not None and snapshot.warnings:
            viability = "Review recommended"
        else:
            viability = "Viable"
        rows.append(
            {
                "activity_id": a.id,
                "activity_type": a.get_activity_type_display(),
                "school": a.school.name if a.school_id else "—",
                "staff": names.get(li.responsible_user, "—"),
                "planned_date": a.planned_date,
                "delivery_type": a.delivery_type,
                "label": ", ".join(
                    dict.fromkeys(line.label for line in activity_lines)
                ),
                "operational_cost": operational,
                "operational_cost_fmt": _ugx(operational),
                "reference_cost": reference,
                "reference_cost_fmt": _ugx(reference) if reference is not None else "—",
                "minimum_viable_cost": operational,
                "minimum_viable_cost_fmt": _ugx(operational),
                "country_operational_cost": reference,
                "country_operational_cost_fmt": (
                    _ugx(reference) if reference is not None else "—"
                ),
                "difference": difference,
                "difference_fmt": _ugx(difference),
                "reserve_eligible": reference is not None and difference > 0,
                "viability": viability,
                "funding_status": _approval_status_label(budget.status),
                "status": _validate_line(li),
                "catalogue_id": li.catalogue_id or "Missing",
            }
        )
    rows.sort(key=lambda row: -row["operational_cost"])
    rows = rows[:200]
    return {
        "fy": fy,
        "month": month_num,
        "month_label": MONTHS[month_num] if 1 <= month_num <= 12 else str(month_num),
        "rows": rows,
        "count": len(rows),
        "source_label": source["label"],
    }


# ── Actions ───────────────────────────────────────────────────────────────
def set_envelope_allocation(principal, budget_id, reserve_amount):
    """Compatibility guard for the former editable reserve allocation.

    The country now requests the full Country Operational Cost. Existing clients may
    still post this action, but they cannot lower the amount presented to the
    RVP or turn the country-controlled difference into staff spending authority.
    """
    from django.db import transaction

    _require_cd(principal)
    try:
        requested = int(reserve_amount or 0)
    except (TypeError, ValueError):
        raise BadRequest("Strategic reserve must be a whole UGX amount.")
    if requested < 0:
        raise BadRequest("Strategic reserve cannot be negative.")

    with transaction.atomic():
        budget = (
            MonthlyWorkPlanBudget.objects.select_for_update()
            .filter(id=budget_id)
            .first()
        )
        if budget is None:
            raise BadRequest("Country monthly budget not found.")
        if budget.status in LOCKED_STATUSES:
            raise BadRequest(
                "This country envelope is locked. Return it before changing the allocation."
            )
        month_num = int(budget.month_key.split("-")[1])
        source = _program_source(budget.fy, month_num)
        # Recompute the activity requirement before validating the CD's choice;
        # a schedule change may have changed reserve capacity since page load.
        _recompute_if_live(budget, source)
        capacity = (
            0
            if budget.reference_configuration_missing_count
            else max(
                0,
                int(budget.regional_standard_ceiling)
                - int(budget.operational_activity_requirement),
            )
        )
        if requested != capacity:
            raise BadRequest(
                "The country request must include the full Country Operational "
                f"Cost. Strategic reserve is automatically {_ugx(capacity)}."
            )
        previous = int(budget.strategic_reserve_requested or 0)
        budget.strategic_reserve_requested = requested
        budget.deferred_amount = capacity - requested
        budget.total_amount = (
            int(budget.operational_activity_requirement)
            + int(budget.admin_total or 0)
            + requested
        )
        budget.save(
            update_fields=[
                "strategic_reserve_requested",
                "deferred_amount",
                "total_amount",
                "updated_at",
            ]
        )
    _audit(
        principal,
        "country_budget.envelope_allocated",
        budget,
        {
            "regional_standard_ceiling": budget.regional_standard_ceiling,
            "operational_activity_requirement": budget.operational_activity_requirement,
            "previous_reserve_requested": previous,
            "strategic_reserve_requested": requested,
            "deferred_amount": budget.deferred_amount,
            "total_country_request": budget.total_amount,
        },
    )
    return budget


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
            raise BadRequest("The General Budget is already locked for RVP review.")
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
            f"({_ugx(request.total_amount)}) is included in the General Budget."
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


def _create_snapshot(principal, budget, source):
    """Capture an immutable point-in-time copy of the submitted month.

    The parent row's aggregate totals are frozen by LOCKED_STATUSES, but its
    staff table / category breakdown / per-line detail would otherwise be
    recomputed from live cost lines and drift from what the RVP approved. The
    snapshot stores those structures as JSON at submit time, so history and
    the read-only submission detail never change. Returns the snapshot and
    the new version number it was written under.
    """
    lines = source["lines"]
    names = _user_names([li.responsible_user for li in lines])
    reference_by_line = _reference_amounts_for_lines(lines)

    # staff_rows — same construction as get_country_monthly_budget.
    rows_by_user: dict[str, dict] = {}
    for li in lines:
        if _validate_line(li) == "Excluded":
            continue
        uid = li.responsible_user or "unassigned"
        row = rows_by_user.setdefault(
            uid,
            {
                "user_id": uid,
                "name": names.get(uid, "Unassigned"),
                "cats": {
                    k: {
                        "qty": 0,
                        "acts": set(),
                        "schools": set(),
                        "total": 0,
                        "reference_total": 0,
                    }
                    for k in CATEGORY_ORDER
                },
                "activity_ids": set(),
                "reference_missing": False,
            },
        )
        cat = _page_category(
            li.activity.activity_type, li.activity.delivery_type, _is_project_line(li)
        )
        c = row["cats"][cat]
        c["acts"].add(li.activity_id)
        if li.activity.school_id:
            c["schools"].add(li.activity.school_id)
        c["total"] += int(li.amount or 0)
        reference_amount = reference_by_line.get(li.id)
        if reference_amount is None:
            row["reference_missing"] = True
        else:
            c["reference_total"] += int(reference_amount)
        row["activity_ids"].add(li.activity_id)

    staff_rows = []
    for row in rows_by_user.values():
        row_total = 0
        row_reference_total = 0
        cat_cols = {}
        for cat in CATEGORY_ORDER:
            c = row["cats"][cat]
            qty = (
                len(c["schools"])
                if cat == "partner_in_school_training"
                else len(c["acts"])
            )
            cat_cols[cat] = {
                "qty": qty,
                "unit_cost": _ugx(round(c["total"] / qty)) if qty else "—",
                "total": _ugx(c["total"]),
                "reference_total": _ugx(c["reference_total"]),
                "minimum_viable_total": _ugx(c["total"]),
                "country_operational_total": _ugx(c["reference_total"]),
            }
            row_total += c["total"]
            row_reference_total += c["reference_total"]
        staff_rows.append(
            {
                "user_id": row["user_id"],
                "name": row["name"],
                "cats": cat_cols,
                "total": row_total,
                "total_fmt": _ugx(row_total),
                "reference_total": (
                    None if row["reference_missing"] else row_reference_total
                ),
                "reference_total_fmt": (
                    "—" if row["reference_missing"] else _ugx(row_reference_total)
                ),
                "minimum_viable_total": row_total,
                "minimum_viable_total_fmt": _ugx(row_total),
                "country_operational_total": (
                    None if row["reference_missing"] else row_reference_total
                ),
                "country_operational_total_fmt": (
                    "—" if row["reference_missing"] else _ugx(row_reference_total)
                ),
                "activity_count": len(row["activity_ids"]),
            }
        )
    staff_rows.sort(key=lambda r: -r["total"])

    # line_items — the per-line detail behind every cell.
    line_items = []
    for li in lines:
        if _validate_line(li) == "Excluded":
            continue
        reference_amount = reference_by_line.get(li.id)
        operational_amount = int(li.amount or 0)
        line_items.append(
            {
                "activity_id": li.activity_id,
                "label": li.label,
                "category": _page_category(
                    li.activity.activity_type,
                    li.activity.delivery_type,
                    _is_project_line(li),
                ),
                # Backward-compatible amount remains the payable operational
                # value. Management surfaces lead with reference_amount.
                "amount": operational_amount,
                "amount_fmt": _ugx(operational_amount),
                "operational_amount": operational_amount,
                "operational_amount_fmt": _ugx(operational_amount),
                "reference_amount": reference_amount,
                "reference_amount_fmt": (
                    _ugx(reference_amount) if reference_amount is not None else "—"
                ),
                "minimum_viable_amount": operational_amount,
                "minimum_viable_amount_fmt": _ugx(operational_amount),
                "country_operational_amount": reference_amount,
                "country_operational_amount_fmt": (
                    _ugx(reference_amount) if reference_amount is not None else "—"
                ),
                "difference": (
                    int(reference_amount) - operational_amount
                    if reference_amount is not None
                    else None
                ),
                "difference_fmt": (
                    _ugx(int(reference_amount) - operational_amount)
                    if reference_amount is not None
                    else "—"
                ),
                "staff": names.get(li.responsible_user, "Unassigned"),
                "planned_date": li.planned_date.isoformat()
                if li.planned_date
                else None,
                "delivery_type": li.activity.delivery_type,
                "school": li.activity.school.name if li.activity.school_id else None,
            }
        )

    admin_lines = [
        {
            "description": line.description,
            "category": line.cost_category,
            "quantity": str(line.quantity),
            "unit_cost": line.unit_cost,
            "total_cost": line.total_cost,
            "total_cost_fmt": _ugx(line.total_cost),
        }
        for line in budget.admin_lines.filter(status="active")
    ]

    version = budget.submission_version + 1
    snapshot = MonthlyBudgetSubmissionSnapshot.objects.create(
        monthly_budget=budget,
        version=version,
        fy=budget.fy,
        month_key=budget.month_key,
        country_id=budget.country_id,
        program_total=budget.program_total,
        admin_total=budget.admin_total,
        regional_standard_ceiling=budget.regional_standard_ceiling,
        operational_activity_requirement=budget.operational_activity_requirement,
        strategic_reserve_requested=budget.strategic_reserve_requested,
        deferred_amount=budget.deferred_amount,
        country_funding_shortfall=budget.country_funding_shortfall,
        reference_configuration_missing_count=(
            budget.reference_configuration_missing_count
        ),
        total_amount=budget.total_amount,
        activity_count=budget.activity_count,
        submitted_at=budget.submitted_at,
        submitted_by_user_id=budget.submitted_by_user_id,
        staff_rows=staff_rows,
        line_items=line_items,
        admin_lines=admin_lines,
    )
    return snapshot, version


def send_to_rvp(principal, budget_id):
    """Submit one month's budget to the RVP — atomic, locked, snapshotted.

    The whole transition (status guard → final recompute → integrity check →
    status flip → immutable snapshot → next-month preparation) runs in one
    transaction with the budget row locked via select_for_update. A concurrent
    second click blocks until this commits, then sees ``submitted_to_rvp`` and
    fails the guard — so there is exactly one submission, one snapshot, one
    audit row and one notification even under a race.
    """
    from django.db import transaction

    _require_cd(principal)
    with transaction.atomic():
        budget = (
            MonthlyWorkPlanBudget.objects.select_for_update()
            .filter(id=budget_id)
            .first()
        )
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
            source["lines"],
            list(budget.admin_lines.filter(status="active")),
            budget,
            source,
        )
        failed = [c for c in checks if c["status"] == "failed"]
        if failed:
            raise BadRequest("Cannot submit — validation failed: " + failed[0]["label"])

        budget.status = "submitted_to_rvp"
        budget.submitted_at = timezone.now()
        budget.submitted_by_user_id = principal.user_id
        # _create_snapshot bumps submission_version; capture it on the row.
        snapshot, version = _create_snapshot(principal, budget, source)
        budget.submission_version = version
        budget.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_by_user_id",
                "submission_version",
                "program_total",
                "admin_total",
                "total_amount",
                "activity_count",
                "updated_at",
            ]
        )

    month_label = MONTHS[int(budget.month_key.split("-")[1])]
    _audit(
        principal,
        "country_budget.submit_to_rvp",
        budget,
        {
            "total": budget.total_amount,
            "version": version,
            "regional_standard_ceiling": budget.regional_standard_ceiling,
            "operational_activity_requirement": budget.operational_activity_requirement,
            "strategic_reserve_requested": budget.strategic_reserve_requested,
            "deferred_amount": budget.deferred_amount,
            "country_funding_shortfall": budget.country_funding_shortfall,
        },
    )
    _notify_role(
        "RegionalVicePresident",
        "country_budget_submitted",
        "Monthly Fund Request ready for approval",
        f"Uganda {month_label} {budget.fy} Monthly Fund Request ({_ugx(budget.total_amount)}) is ready for your approval.",
        budget,
    )
    _emit_country_budget_event(
        "country_budget.submitted_to_rvp",
        principal,
        budget,
        {
            "total": budget.total_amount,
            "version": version,
            "regional_standard_ceiling": budget.regional_standard_ceiling,
            "operational_activity_requirement": budget.operational_activity_requirement,
            "strategic_reserve_requested": budget.strategic_reserve_requested,
            "deferred_amount": budget.deferred_amount,
        },
    )

    # §5/§17 — atomically prepare the next month so the active workspace can
    # roll forward. This runs in its OWN transaction: if it fails, the valid
    # RVP submission above is already committed and must NOT be reversed. The
    # caller surfaces a recoverable "preparation failed" state and offers a
    # retry; the retry is idempotent (get_or_create on the unique month key).
    next_budget = None
    prep_failed = False
    try:
        from django.db import transaction

        with transaction.atomic():
            next_budget, _created = prepare_next_month(principal, budget)
        _emit_country_budget_event(
            "country_budget.next_month_prepared",
            principal,
            next_budget,
            {"previous_month_key": budget.month_key},
        )
    except Exception:  # noqa: BLE001 — submission stays committed (§17)
        prep_failed = True
        _emit_country_budget_event(
            "country_budget.preparation_failed",
            principal,
            budget,
            {"previous_month_key": budget.month_key},
        )
    budget._next_month_prepared = not prep_failed  # noqa: SLF001 — view signal
    return budget


def _approve_monthly_strategic_reserve(principal, budget):
    """Materialize the approved envelope line as undisbursed country reserve."""
    from apps.audit.services import log as audit_log
    from apps.budget.models import (
        CountryStrategicActivityReserve,
        StrategicReserveStatus,
    )

    requested = int(budget.strategic_reserve_requested or 0)
    reserve = (
        CountryStrategicActivityReserve.objects.select_for_update()
        .filter(
            country=budget.country_id or HOME_COUNTRY_ID,
            fy=budget.fy,
            period_key=budget.month_key,
        )
        .first()
    )
    if reserve is not None:
        configured = int(reserve.opening_reserve) + int(reserve.approved_additions)
        if configured != requested:
            raise BadRequest(
                "The monthly strategic reserve record does not match this country "
                "envelope. Reconcile it before RVP approval."
            )
        if reserve.status == StrategicReserveStatus.CLOSED:
            raise BadRequest("A closed strategic reserve cannot be reused.")
        if reserve.status == StrategicReserveStatus.APPROVED:
            return reserve
    elif requested == 0:
        return None
    else:
        reserve = CountryStrategicActivityReserve.objects.create(
            country=budget.country_id or HOME_COUNTRY_ID,
            fy=budget.fy,
            period_key=budget.month_key,
            opening_reserve=requested,
            status=StrategicReserveStatus.DRAFT,
            notes=f"Country monthly envelope {budget.id} version {budget.submission_version}",
        )

    reserve.status = StrategicReserveStatus.APPROVED
    reserve.approved_by = principal.user_id
    reserve.approved_at = timezone.now()
    reserve.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    audit_log(
        action="strategic_reserve.approved_from_country_envelope",
        subject_kind="CountryStrategicActivityReserve",
        subject_id=reserve.id,
        actor_id=principal.user_id,
        actor_role=getattr(principal, "active_role", ""),
        payload={
            "monthlyBudgetId": budget.id,
            "monthKey": budget.month_key,
            "amount": requested,
        },
        required=True,
    )
    return reserve


def approve(principal, budget_id):
    from django.db import transaction

    _require_rvp(principal)
    with transaction.atomic():
        budget = (
            MonthlyWorkPlanBudget.objects.select_for_update()
            .filter(id=budget_id)
            .first()
        )
        if not budget:
            raise BadRequest("Country monthly budget not found.")
        _assert_rvp_country_scope(budget)
        if budget.status != "submitted_to_rvp":
            raise BadRequest("Only a submitted budget can be approved.")

        _approve_monthly_strategic_reserve(principal, budget)
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
        f"General Budget {budget.month_key}",
        "approve",
        principal,
        amount=budget.total_amount,
        fy=budget.fy,
    )
    _notify_role(
        "CountryDirector",
        "country_budget_approved",
        "General Budget approved by RVP",
        f"{month_label} {budget.fy} General Budget was approved by the RVP.",
        budget,
    )
    _notify_role(
        "Accountant",
        "country_budget_approved",
        "General Budget ready for disbursement",
        f"{month_label} {budget.fy} General Budget ({_ugx(budget.total_amount)}) was approved and is ready to prepare for disbursement.",
        budget,
    )
    _emit_country_budget_event(
        "country_budget.approved_by_rvp",
        principal,
        budget,
        {"total": budget.total_amount},
    )
    return budget


def return_budget(principal, budget_id, data):
    from django.db import transaction

    _require_rvp(principal)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    with transaction.atomic():
        budget = (
            MonthlyWorkPlanBudget.objects.select_for_update()
            .filter(id=budget_id)
            .first()
        )
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
        f"General Budget {budget.month_key}",
        "return",
        principal,
        reason=reason,
        amount=budget.total_amount,
        fy=budget.fy,
    )
    _notify_role(
        "CountryDirector",
        "country_budget_returned",
        "General Budget returned by RVP",
        f"{month_label} {budget.fy} General Budget was returned by the RVP. Reason: {reason}",
        budget,
    )
    _emit_country_budget_event(
        "country_budget.returned_by_rvp",
        principal,
        budget,
        {"reason": reason},
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


def _emit_country_budget_event(event_type, principal, budget, payload):
    """Push a country-budget lifecycle event through the realtime seam.

    The submit/approve/return actions still write their audit row and
    notification via the legacy ``_audit`` / ``_notify_role`` helpers (they are
    tested and dedupe correctly), but the spec wants the canonical
    ``country_budget.*`` events on the bus too so the live dashboards update in
    real time. This is best-effort: a bus failure never rolls back the action.
    """
    try:
        from apps.realtime.domain_events import emit, users_with_role

        # The relevant live audience: the actor plus every CD/RVP/Accountant,
        # since each of those dashboards reflects country-budget state.
        live = list(
            {
                principal.user_id,
                *users_with_role("CountryDirector"),
                *users_with_role("RegionalVicePresident"),
                *users_with_role("Accountant"),
            }
        )
        emit(
            event_type=event_type,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            subject_kind="MonthlyWorkPlanBudget",
            subject_id=budget.id,
            payload={"month_key": budget.month_key, "fy": budget.fy, **payload},
            live_user_ids=live,
        )
    except Exception:  # noqa: BLE001 — best-effort realtime push
        pass


def _next_fy_month(fy, month_num):
    """The (fy, month) that follows (fy, month) under the Oct→Sep FY rule.

    September (the FY's last month) rolls into October of the NEXT fiscal
    year — FY2026 Sep → FY2027 Oct — matching the spec's §5 example. Every
    other month advances one calendar month inside the same FY.
    """
    if month_num == 9:
        return str(int(fy) + 1), 10
    if month_num == 12:
        return fy, 1
    return fy, month_num + 1


def prepare_next_month(principal, submitted_budget):
    """Idempotently create (or fetch) the draft for the month after a submit.

    Called inside the submit transaction so "the next month is prepared" is
    atomic with the submission itself. Because it routes through a
    get_or_create on the unique (country, month_key) key, a refresh, a retry,
    a scheduler tick or a second tab all resolve to the same single next-month
    row — never a duplicate. Returns ``(next_budget, created)``.
    """
    month_num = int(submitted_budget.month_key.split("-")[1])
    next_fy, next_month = _next_fy_month(submitted_budget.fy, month_num)
    month_key = _month_key(next_fy, next_month)
    next_budget, created = MonthlyWorkPlanBudget.objects.get_or_create(
        country_id=HOME_COUNTRY_ID,
        month_key=month_key,
        defaults={"fy": next_fy, "status": "draft_generated"},
    )
    return next_budget, created
