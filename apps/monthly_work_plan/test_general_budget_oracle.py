"""Oracle for the General Budget page's country view-model
(get_country_monthly_budget and the helpers it changed).

The 2026-09-24 performance change reads the month's cost lines, and the raw
month set the integrity checks inspect, as plain rows instead of models, and
reads the six trailing months in one grouped query instead of six. The
`_frozen_*` functions below are copies of the implementations before
that change (commit 4425605), renamed and calling each other; every test
asserts the live code returns exactly what they return, on fixtures covering
an empty month, months either side of the FY boundary, a locked envelope,
missing links (no catalogue source, no reference snapshot, no owner), every
integrity-check failure and equal staff totals.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.forms.models import model_to_dict
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import ActivityCostSnapshot
from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import (
    render_precomputed_metric_for_source,
    render_precomputed_metric_item,
)
from apps.core.permissions import has_permission
from apps.core.rbac import Permission
from apps.monthly_work_plan import country_budget_service as live
from apps.monthly_work_plan.country_budget_service import (
    CATEGORY_ORDER,
    CD_ROLES,
    CLUSTER_TRAINING,
    HOME_COUNTRY_ID,
    LOCKED_STATUSES,
    MONTHS,
    NON_FUNDABLE_ACTIVITY_STATUSES,
    RETURN_REASONS,
    RVP_ROLES,
    SSA_VISIT_TYPES,
    TRAINING_TYPES,
    _approval_status_label,
    _bottom_stats,
    _execution_context,
    _get_or_create_budget,
    _is_project_line,
    _page_category,
    _prior_month_pending,
    _recompute_if_live,
    _require_read,
    _trend,
    _ugx,
    _user_names,
    _valid_lines_qs,
    _validate_line,
    get_country_monthly_budget,
)
from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget
from apps.projects.models import Project
from apps.schools.models import School

# ── Frozen reference (pre-change implementations, commit 4425605) ───────────


def _frozen_program_source(fy, month_num):
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


def _frozen_integrity_checks(lines, admin_lines, budget, source=None):
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
                "label": "Regional Standard Funding Cost configured for scheduled activities",
                "status": (
                    "warning"
                    if budget.reference_configuration_missing_count
                    else "passed"
                ),
                "detail": (
                    f"{budget.reference_configuration_missing_count} activity(ies) "
                    "do not yet have a regional-standard cost snapshot. Reserve "
                    "capacity is provisional until regional finance completes the card."
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
                "label": "Country envelope allocation balances to the regional ceiling",
                # Missing reference configuration cannot balance truthfully; it
                # remains a management warning, not fabricated benchmark money.
                "status": (
                    "warning"
                    if budget.reference_configuration_missing_count
                    else ("passed" if allocation_balances else "failed")
                ),
                "detail": (
                    "Operational allocation, reserve and deferred amount must "
                    "equal the Regional Standard Funding Ceiling."
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


def _frozen_trailing_month_series(fy, month_num, n=6):
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


def _frozen_get_country_monthly_budget(principal, filters=None):
    _require_read(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    month_num = int(filters.get("month") or timezone.now().month)
    search = (filters.get("q") or "").strip().lower()

    budget = _get_or_create_budget(fy, month_num)
    source = _frozen_program_source(fy, month_num)
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

    series = _frozen_trailing_month_series(fy, month_num, n=6)
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
    checks = _frozen_integrity_checks(lines, admin_lines, budget, source)
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
        "fy_options": sorted(set(fy_options()) | {fy}, reverse=True),
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


# ── Fixtures and assertions ──────────────────────────────────────────────────

User = get_user_model()
FY = "2026"
NOW = "2026-04-18 10:00:00+03:00"


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


@freeze_time(NOW)
class GeneralBudgetOracleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = _user("gb-cd@t.org", "CountryDirector")
        cls.accountant = _user("gb-acct@t.org", "Accountant")
        cls.rvp = _user("gb-rvp@t.org", "RegionalVicePresident")
        cls.ia = _user("gb-ia@t.org", "ImpactAssessment")
        officer_a = _user("gb-a@t.org", "CCEO")
        officer_b = _user("gb-b@t.org", "CCEO")
        officer_c = _user("gb-c@t.org", "CCEO")
        officer_d = _user("gb-d@t.org", "CCEO")
        project = Project.objects.create(name="Oracle Project", category="pilot")
        school_1 = School.objects.create(school_id="GB-1", name="GB One")
        school_2 = School.objects.create(school_id="GB-2", name="GB Two")

        def activity(atype, planned, *, fy=FY, **extra):
            scheduled = extra.pop("scheduled", planned)
            return Activity.objects.create(
                activity_type=atype,
                delivery_type=extra.pop("delivery_type", "staff"),
                status=extra.pop("status", "scheduled"),
                fy=fy,
                planned_date=planned,
                scheduled_date=(
                    timezone.make_aware(
                        timezone.datetime(
                            scheduled.year, scheduled.month, scheduled.day, 9
                        )
                    )
                    if scheduled
                    else None
                ),
                **extra,
            )

        def line(act, key, amount, owner, *, when=None, fy=FY, **extra):
            when = when or act.planned_date or act.scheduled_date.date()
            return ActivityScheduleCostLine.objects.create(
                activity=act,
                cost_setting_key=key,
                label=key.replace("_", " ").title(),
                unit_cost=amount,
                quantity=1,
                amount=amount,
                planned_date=extra.pop("planned_date", when),
                month=when.month,
                fiscal_year=fy,
                catalogue_id=extra.pop("catalogue_id", "cat-1"),
                catalogue_version=extra.pop("catalogue_version", 1),
                line_item_type=extra.pop("line_item_type", "transport"),
                responsible_user=owner,
                **extra,
            )

        april = date(2026, 4, 9)
        # Plain staff visits; A and B end on equal totals.
        visit_a = activity("school_visit", april, school=school_1)
        line(visit_a, "primary_transport_per_day", 60_000, officer_a.id)
        line(visit_a, "lunch", 20_000, officer_a.id, line_item_type="meal")
        visit_b = activity("follow_up_visit", april, school=school_2)
        line(visit_b, "primary_transport_per_day", 80_000, officer_b.id)
        # No catalogue version. (A duplicate line cannot be built: the
        # database allows one line per activity and cost key.)
        line(
            visit_b,
            "fuel",
            0,
            officer_b.id,
            catalogue_version=None,
        )
        # No catalogue source: "Missing Cost".
        uncosted = activity("coaching_visit", date(2026, 4, 14), school=school_1)
        line(uncosted, "lunch", 15_000, officer_c.id, catalogue_id=None)
        # Cost flagged missing on the activity: "Needs Review".
        review = activity("school_visit", date(2026, 4, 15), cost_missing=True)
        line(review, "lunch", 12_000, officer_c.id)
        # SSA collection, a cluster training completed without counts, and a
        # staff in-school training that folds into cluster training.
        ssa = activity(SSA_VISIT_TYPES[0], date(2026, 4, 16), school=school_2)
        line(ssa, "primary_transport_per_day", 30_000, officer_a.id)
        training = activity("cluster_training", date(2026, 4, 17), status="completed")
        line(training, "venue", 90_000, officer_b.id)
        line(training, "participant_meals", 45_000, None)
        in_school = activity("in_school_training", date(2026, 4, 20), school=school_1)
        line(in_school, "facilitation", 25_000, officer_c.id)
        # Partner work: scheduled; still only assigned (costed early); and
        # assigned with no planned date at all (excluded from the page).
        partner_visit = activity(
            "school_visit", date(2026, 4, 21), delivery_type="partner", school=school_2
        )
        line(partner_visit, "partner_visit_fee", 50_000, officer_a.id)
        partner_training = activity(
            "in_school_training",
            date(2026, 4, 22),
            delivery_type="partner",
            status="assigned_to_partner",
            school=school_1,
        )
        line(partner_training, "partner_training_lump_sum", 300_000, officer_a.id)
        unplanned = activity(
            "in_school_training",
            None,
            delivery_type="partner",
            scheduled=date(2026, 4, 23),
        )
        line(unplanned, "partner_training_lump_sum", 200_000, officer_b.id)
        # Equal to the unassigned participant meals: a staff-row tie.
        tie = activity("school_visit", date(2026, 4, 23))
        line(tie, "lunch", 45_000, officer_d.id)
        # Special Project money through either path.
        own_project = activity("school_visit", date(2026, 4, 24), project_id=project.id)
        line(own_project, "lunch", 18_000, officer_b.id)
        line_project = activity("school_visit", date(2026, 4, 24))
        line(line_project, "lunch", 22_000, officer_c.id, project=project)
        # Raw-set-only rows: cancelled, rejected, deferred and deleted work.
        for status in ("cancelled", "rejected", "deferred"):
            gone = activity("school_visit", date(2026, 4, 27), status=status)
            line(gone, "lunch", 5_000, officer_a.id)
        deleted = activity("school_visit", date(2026, 4, 28))
        line(deleted, "lunch", 7_000, officer_a.id)
        Activity.objects.filter(id=deleted.id).update(deleted_at=timezone.now())

        # Reference snapshots: priced, unpriced, and zero operational cost.
        def snapshot(act, reference, operational, breakdown=None):
            ActivityCostSnapshot.objects.create(
                activity=act,
                reference_cost=reference,
                operational_cost=operational,
                calculated_at=timezone.now(),
                reference_breakdown=breakdown or [],
                operational_breakdown=breakdown or [],
            )

        snapshot(visit_a, 100_000, 80_000)
        snapshot(visit_b, 90_000, 80_000)
        snapshot(ssa, None, 30_000)
        snapshot(training, 150_000, 0)

        # Trailing months either side of the FY boundary; a September line on
        # an FY2026 activity must NOT land in September 2025 (FY2025).
        for when, fy, owner in (
            (date(2025, 8, 12), "2025", officer_a),
            (date(2025, 9, 9), "2025", officer_b),
            (date(2025, 9, 10), "2026", officer_b),
            (date(2025, 10, 7), "2026", officer_a),
            (date(2025, 12, 2), "2026", officer_c),
            (date(2026, 1, 20), "2026", officer_a),
            (date(2026, 3, 3), "2026", officer_b),
        ):
            past = activity("school_visit", when, fy=fy)
            line(past, "primary_transport_per_day", 40_000, owner.id, fy=fy)
            past_partner = activity(
                "in_school_training", when, fy=fy, delivery_type="partner"
            )
            line(past_partner, "partner_training_lump_sum", 110_000, owner.id, fy=fy)

        # Admin plans: the month's (one active, one removed) and past totals.
        april_budget = MonthlyWorkPlanBudget.objects.create(
            country_id=HOME_COUNTRY_ID, month_key="2026-04", fy=FY
        )
        for description, status, total in (
            ("Office internet", "active", 25_000),
            ("Old item", "removed", 90_000),
        ):
            AdminBudgetLine.objects.create(
                monthly_budget=april_budget,
                cost_category="operations",
                description=description,
                quantity=1,
                unit_cost=total,
                total_cost=total,
                created_by_user_id=cls.cd.id,
                status=status,
            )
        MonthlyWorkPlanBudget.objects.create(
            country_id=HOME_COUNTRY_ID, month_key="2026-01", fy=FY, admin_total=33_000
        )
        # A locked month: its snapshot is not recomputed.
        MonthlyWorkPlanBudget.objects.create(
            country_id=HOME_COUNTRY_ID,
            month_key="2026-03",
            fy=FY,
            status="submitted_to_rvp",
            program_total=1,
            total_amount=1,
        )

    def assertSameAsFrozen(self, principal, month, fy=FY):
        filters = {"fy": fy, "month": month}
        expected = _frozen_get_country_monthly_budget(principal, filters)
        expected_row = model_to_dict(expected["budget"])
        actual = get_country_monthly_budget(principal, filters)
        self.assertEqual(actual, expected, (principal.email, filters))
        self.assertEqual(model_to_dict(actual["budget"]), expected_row)

    def test_general_budget_matches_for_every_reader(self):
        for principal in (self.cd, self.accountant, self.rvp, self.ia):
            with self.subTest(principal=principal.email):
                self.assertSameAsFrozen(principal, 4)

    def test_general_budget_across_months(self):
        # Empty month, FY-boundary months, a locked month and the busy month.
        for month in (1, 3, 5, 8, 9, 10, 12, 4):
            with self.subTest(month=month):
                self.assertSameAsFrozen(self.cd, month)
        self.assertSameAsFrozen(self.cd, 4, fy="2031")

    def test_fixture_exercises_the_edges(self):
        page = get_country_monthly_budget(self.cd, {"fy": FY, "month": 4})
        failing = {c["label"] for c in page["checks"] if c["status"] != "passed"}
        for label in (
            "All activity costs linked to planned activities",
            "No uncosted planned activities",
            "All Cost Catalogue versions present",
            "Partner activities are scheduled before included",
            "Cluster training participant/session counts exist",
        ):
            self.assertIn(label, failing)
        totals = [row["total"] for row in page["staff_rows"]]
        self.assertNotEqual(len(totals), len(set(totals)), "no equal staff totals")
        self.assertGreater(
            page["country_envelope"]["referenceConfigurationMissingCount"], 0
        )

    def test_integrity_checks_on_models_and_rows(self):
        budget = MonthlyWorkPlanBudget.objects.get(month_key="2026-04")
        admin_lines = list(budget.admin_lines.filter(status="active"))
        models = _frozen_program_source(FY, 4)
        rows = live._program_source(FY, 4, lean=True)
        expected = _frozen_integrity_checks(
            models["lines"], admin_lines, budget, models
        )
        # The other caller hands in model lines; the page hands in rows.
        self.assertEqual(
            live._integrity_checks(models["lines"], admin_lines, budget, models),
            expected,
        )
        self.assertEqual(
            live._integrity_checks(rows["lines"], admin_lines, budget, rows), expected
        )
        for month_key in ("2026-13", "bad", None):
            with self.subTest(month_key=month_key):
                broken = MonthlyWorkPlanBudget(month_key=month_key, fy=FY)
                self.assertEqual(
                    live._integrity_checks([], [], broken),
                    _frozen_integrity_checks([], [], broken),
                )

    def test_program_source(self):
        for month in (4, 9, 1):
            frozen = _frozen_program_source(FY, month)
            self.assertEqual(live._program_source(FY, month), frozen)
            lean = live._program_source(FY, month, lean=True)
            self.assertEqual(
                {k: v for k, v in lean.items() if k != "lines"},
                {k: v for k, v in frozen.items() if k != "lines"},
            )
            self.assertEqual(len(lean["lines"]), len(frozen["lines"]))

    def test_trailing_month_series(self):
        for month in range(1, 13):
            for n in (6, 13):
                with self.subTest(month=month, n=n):
                    self.assertEqual(
                        live._trailing_month_series(FY, month, n=n),
                        _frozen_trailing_month_series(FY, month, n=n),
                    )
