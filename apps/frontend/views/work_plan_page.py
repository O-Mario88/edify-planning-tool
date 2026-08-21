"""Work Plan page — one scoped Activity dataset, grouped over the fiscal year.

The unified Work Plan reads the SAME operational ledger every other surface
uses (apps.activities.Activity + its ActivityScheduleCostLine budget rows) and
adds nothing of its own: scoping reuses the Calendar audience helper, the
next-action column reuses My Plan's canonical derivation, and every cost figure
is a sum of persisted cost lines — never an invented rate.

Query discipline (§ scale gate): one base queryset, cost totals annotated,
cost lines + weekly-request + advance chains prefetched, then a single Python
pass builds rows, month bands and KPI counters together. No per-row queries.

Role scoping (§18):
  • Admin / CountryDirector — country: every activity in the FY.
  • Accountant — country rows in a read-only finance context (no action CTAs).
  • RegionalVicePresident — region-scoped, read-only rows plus aggregate month
    bands so the submitted plan can be inspected before approval.
  • ProjectCoordinator — activities belonging to their scoped projects.
  • Program Lead / CCEO / everyone else — the Calendar audience: their own
    work (both StaffProfile and User id spaces) plus, for a PL, supervised
    CCEOs; partner-delivered work is reachable through monitored_by_staff_id.
"""

from __future__ import annotations

import calendar
from urllib.parse import urlencode

from django.db.models import Q, Sum

from apps.activities.models import Activity
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.clock import ClockService
from apps.core.enums import ActivityStatus, ActivityType, DeliveryType, SupportRationale
from apps.core.fy import fy_options, get_operational_fy, get_quarter_for_date
from apps.core.metrics import MetricValue, render_metric, render_strip
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission
from apps.my_plan.services import (
    compute_next_action,
    get_activity_status_label_and_class,
    status_tone,
)

# Terminal states that never count toward plan totals. A status filter naming
# one of them reveals those rows explicitly (§ spec: excluded from totals and
# the default list, revealable on demand).
HIDDEN_TERMINAL_STATUSES = ("cancelled", "rejected", "deferred")

# "Still expected to happen" — the scheduled/in-progress family. A dated
# activity whose service window has fully passed while still in one of these
# states is At Risk.
AT_RISK_OPEN_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "rescheduled",
    "in_progress",
    "completion_started",
)

# WeeklyFundRequest states meaning "money is sitting in an approval queue".
PENDING_APPROVAL_WFR_STATUSES = ("submitted_to_pl", "submitted_to_cd")

_WFR_LABELS = {
    "pending_responsible_confirmation": "In weekly request",
    "submitted_to_pl": "Awaiting PL approval",
    "submitted_to_cd": "Awaiting CD approval",
    "returned_by_pl": "Returned by PL",
    "returned_by_cd": "Returned by CD",
    "returned_by_accountant": "Returned by Accountant",
    "confirmed_for_advance": "Ready for disbursement",
    "disbursed": "Disbursed",
}

FY_MONTH_ORDER = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
QUARTER_MONTHS = {
    "Q1": (10, 11, 12),
    "Q2": (1, 2, 3),
    "Q3": (4, 5, 6),
    "Q4": (7, 8, 9),
}

# Roles that read this page but never act from it (§18): the Accountant holds
# a finance-review lens and the RVP an aggregate one.
_NO_ACTION_ROLES = {
    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
    EdifyRole.PROGRAM_ACCOUNTANT.value,
}


def _month_year(fy: int, month: int) -> int:
    """Calendar year of a month within an Oct–Sep fiscal year."""
    return fy - 1 if month >= 10 else fy


def _window_months(view: str, period) -> tuple[int, ...]:
    if view == "fy":
        return FY_MONTH_ORDER
    if view == "quarter":
        return QUARTER_MONTHS[period]
    return (period,)


def _window_bounds(fy: int, months: tuple[int, ...]):
    first, last = months[0], months[-1]
    start_year, end_year = _month_year(fy, first), _month_year(fy, last)
    from datetime import date

    start = date(start_year, first, 1)
    end = date(end_year, last, calendar.monthrange(end_year, last)[1])
    return start, end


def _window_q(start, end) -> Q:
    """Activities whose service window touches [start, end].

    planned_date anchors the row; a multi-day activity whose end_date spills
    into the window still belongs to it. Legacy rows without a planned_date
    fall back to scheduled_date — the same tolerance My Plan applies.
    """
    return (
        Q(planned_date__range=(start, end))
        | Q(planned_date__lt=start, end_date__gte=start)
        | Q(planned_date__isnull=True, scheduled_date__date__range=(start, end))
    )


def _scoped_activities(user, fy: str):
    """(queryset, rows_visible) — §18 scoping over the FY ledger."""
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    role = user.active_role

    if role in (
        EdifyRole.ADMIN.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.PROGRAM_ACCOUNTANT.value,
    ):
        return qs, True

    if role == EdifyRole.REGIONAL_VICE_PRESIDENT.value:
        # Aggregate lens only. Region narrowing when geography is assigned;
        # an RVP with no region rows oversees the whole deployment (the same
        # convention resolve_user_scope documents).
        from apps.core.scoping import resolve_user_scope

        region_ids = resolve_user_scope(user).region_ids
        if region_ids:
            qs = qs.filter(
                Q(school__district__region_id__in=region_ids)
                | Q(cluster__district__region_id__in=region_ids)
                | Q(event_district__region_id__in=region_ids)
            )
        return qs, True

    if role == EdifyRole.PROJECT_COORDINATOR.value:
        from apps.projects.scoping import scoped_projects

        project_ids = list(scoped_projects(user).values_list("id", flat=True))
        return qs.filter(project_id__in=project_ids), True

    # PL / CCEO / IA / everyone else: the Calendar audience. Imported lazily —
    # extended_views imports this module's caller, so a top-level import here
    # would be circular.
    from apps.frontend.views.extended_views import _calendar_staff_audience

    owner_ids, _ = _calendar_staff_audience(user)
    if owner_ids is None:
        return qs, True
    return (
        qs.filter(
            Q(responsible_staff_id__in=owner_ids)
            | Q(monitored_by_staff_id__in=owner_ids, delivery_type="partner")
        ),
        True,
    )


def _date_label(start, end) -> str:
    """ "14 August 2026", "12–14 August 2026" or "28 August – 2 September 2026"."""
    if not start:
        return "Not dated"
    if end and end != start:
        if (end.year, end.month) == (start.year, start.month):
            return f"{start.day}–{end.day} {start.strftime('%B %Y')}"
        if end.year == start.year:
            return (
                f"{start.day} {start.strftime('%B')} – "
                f"{end.day} {end.strftime('%B %Y')}"
            )
        return (
            f"{start.day} {start.strftime('%B %Y')} – "
            f"{end.day} {end.strftime('%B %Y')}"
        )
    return f"{start.day} {start.strftime('%B %Y')}"


def _query_string(base: dict, **overrides) -> str:
    merged = {key: value for key, value in base.items() if value not in (None, "")}
    for key, value in overrides.items():
        if value in (None, ""):
            merged.pop(key, None)
        else:
            merged[key] = value
    encoded = urlencode(merged)
    return f"/work-plan?{encoded}" if encoded else "/work-plan"


def build_work_plan_context(user, params) -> dict:
    from apps.monthly_work_plan.schedule_plan import monthly_work_plan

    today = ClockService.today()
    operational_fy = get_operational_fy(today)

    options = fy_options(today)
    fy = params.get("fy") or operational_fy
    if fy not in options:
        fy = operational_fy
    fy_int = int(fy)

    view = params.get("view") or "month"
    if view not in ("month", "quarter", "fy"):
        view = "month"

    current_quarter = get_quarter_for_date(today)
    if view == "month":
        try:
            period = int(params.get("period") or 0)
        except (TypeError, ValueError):
            period = 0
        if period not in range(1, 13):
            period = today.month if fy == operational_fy else 10
    elif view == "quarter":
        period = params.get("period") or ""
        if period not in QUARTER_MONTHS:
            period = current_quarter if fy == operational_fy else "Q1"
    else:
        period = ""

    status = (params.get("status") or "").strip()
    responsible = (params.get("responsible") or "").strip()
    project_filter = (params.get("project") or "").strip()
    activity_type = (params.get("activity_type") or "").strip()
    executor = (params.get("executor") or "").strip()
    flag = (params.get("flag") or "").strip()
    if flag not in ("pending_approval", "cost_missing", "at_risk"):
        flag = ""

    base_qs, rows_visible = _scoped_activities(user, fy)

    # Terminal statuses leave the plan unless explicitly asked for.
    valid_statuses = set(ActivityStatus.values)
    if status not in valid_statuses:
        status = ""
    if status:
        base_qs = base_qs.filter(status=status)
    else:
        base_qs = base_qs.exclude(status__in=HIDDEN_TERMINAL_STATUSES)

    if responsible:
        base_qs = base_qs.filter(responsible_staff_id=responsible)
    if project_filter:
        base_qs = base_qs.filter(project_id=project_filter)
    if activity_type and activity_type in set(ActivityType.values):
        base_qs = base_qs.filter(activity_type=activity_type)
    if executor and executor in set(DeliveryType.values):
        base_qs = base_qs.filter(delivery_type=executor)

    window_months = _window_months(view, period)
    window_start, window_end = _window_bounds(fy_int, window_months)
    period_qs = base_qs.filter(_window_q(window_start, window_end))

    activities = list(
        period_qs.select_related("school", "cluster", "event_district")
        .annotate(lines_total=Sum("schedule_cost_lines__amount"))
        .prefetch_related(
            "schedule_cost_lines",
            "schedule_cost_lines__weekly_request_lines__weekly_fund_request",
            "schedule_cost_lines__advance_requests",
        )
        .order_by("planned_date", "created_at")
    )

    # ── Display-name maps: one query per id space, never per row. ────────────
    staff_ids: set[str] = set()
    partner_ids: set[str] = set()
    project_ids: set[str] = set()
    for a in activities:
        if a.responsible_staff_id:
            staff_ids.add(a.responsible_staff_id)
        if a.monitored_by_staff_id:
            staff_ids.add(a.monitored_by_staff_id)
        if a.assigned_partner_id:
            partner_ids.add(a.assigned_partner_id)
        if a.project_id:
            project_ids.add(a.project_id)

    name_map: dict[str, str] = {}
    if staff_ids:
        from apps.accounts.models import StaffProfile, User

        profiles = StaffProfile.objects.filter(
            Q(id__in=staff_ids) | Q(user_id__in=staff_ids)
        ).select_related("user")
        for profile in profiles:
            display = profile.user.name if profile.user_id else ""
            if display:
                name_map[profile.id] = display
                if profile.user_id:
                    name_map[profile.user_id] = display
        unresolved = staff_ids - set(name_map)
        if unresolved:
            for user_id, user_name in User.objects.filter(
                id__in=unresolved
            ).values_list("id", "name"):
                name_map[user_id] = user_name or "Staff"

    partner_map: dict[str, str] = {}
    if partner_ids:
        from apps.partners.models import Partner

        partner_map = dict(
            Partner.objects.filter(id__in=partner_ids).values_list("id", "name")
        )

    project_map: dict[str, str] = {}
    if project_ids:
        from apps.projects.models import Project

        project_map = dict(
            Project.objects.filter(id__in=project_ids).values_list("id", "name")
        )

    rationale_labels = dict(SupportRationale.choices)

    viewer_ids = {value for value in (user.id, user.staff_profile_id) if value}
    actions_enabled = user.active_role not in _NO_ACTION_ROLES

    # ── One pass: rows + month bands + KPI counters together. ────────────────
    bands: dict[int, dict] = {}
    query_state = {
        "fy": fy,
        "view": view,
        "period": str(period),
        "status": status,
        "responsible": responsible,
        "project": project_filter,
        "activity_type": activity_type,
        "executor": executor,
        "flag": flag,
    }
    for m in window_months:
        bands[m] = {
            "month": m,
            "label": f"{calendar.month_name[m]} {_month_year(fy_int, m)}",
            "count": 0,
            "cost": 0,
            "completed": 0,
            "at_risk": 0,
            "url": _query_string(query_state, view="month", period=m, flag=None),
        }
    undated_band = {
        "month": None,
        "label": "Undated",
        "count": 0,
        "cost": 0,
        "completed": 0,
        "at_risk": 0,
        "url": _query_string(query_state, flag=None),
    }
    window_month_set = set(window_months)

    rows: list[dict] = []
    period_budget = 0
    pending_approval_count = 0
    cost_missing_count = 0
    at_risk_count = 0
    completed_count = 0

    for a in activities:
        anchor = a.planned_date or (
            a.scheduled_date.date() if a.scheduled_date else None
        )
        if anchor is not None:
            band_month = anchor.month
            if band_month not in window_month_set:
                # A multi-day spillover (or clock-skewed legacy row): clamp to
                # the window edge it touches so every activity lands in
                # exactly one band.
                band_month = (
                    window_months[0] if anchor < window_start else window_months[-1]
                )
            band = bands[band_month]
        elif a.month in window_month_set:
            band = bands[a.month]
            band_month = a.month
        else:
            band = undated_band
            band_month = None

        cost_lines = list(a.schedule_cost_lines.all())

        # Cost lines land in the band of their own service month (multi-day
        # allocations), falling back to the parent activity's band, so each
        # line is counted exactly once across the FY.
        activity_period_cost = 0
        for line in cost_lines:
            amount = line.amount or 0
            line_month = (
                line.planned_date.month if line.planned_date else None
            ) or line.month
            target = bands[line_month] if line_month in window_month_set else band
            target["cost"] += amount
            activity_period_cost += amount
        period_budget += activity_period_cost

        is_completed = a.status in COMPLETED_WORK_STATUSES
        effective_end = a.end_date or anchor
        is_at_risk = bool(
            effective_end
            and effective_end < today
            and a.status in AT_RISK_OPEN_STATUSES
        )
        is_pending_approval = any(
            wfr_line.weekly_fund_request.status in PENDING_APPROVAL_WFR_STATUSES
            for line in cost_lines
            for wfr_line in line.weekly_request_lines.all()
        )

        band["count"] += 1
        if is_completed:
            band["completed"] += 1
            completed_count += 1
        if is_at_risk:
            band["at_risk"] += 1
            at_risk_count += 1
        if is_pending_approval:
            pending_approval_count += 1
        if a.cost_missing:
            cost_missing_count += 1

        if flag == "pending_approval" and not is_pending_approval:
            continue
        if flag == "cost_missing" and not a.cost_missing:
            continue
        if flag == "at_risk" and not is_at_risk:
            continue

        status_label, status_class = get_activity_status_label_and_class(a, today)
        owned = a.responsible_staff_id in viewer_ids or (
            a.delivery_type == "partner" and a.monitored_by_staff_id in viewer_ids
        )
        if actions_enabled and (owned or user.active_role == EdifyRole.ADMIN.value):
            action = compute_next_action(a, today)
        else:
            action = {
                "text": "View",
                "action": "view",
                "url": f"/my-plan/{a.id}",
                "description": "",
            }

        place = (
            a.venue
            or (a.school.name if a.school_id else "")
            or (a.cluster.name if a.cluster_id else "")
            or (a.event_district.name if a.event_district_id else "")
        )
        context_label = (
            project_map.get(a.project_id)
            or (a.activity_context_type or "").replace("_", " ").title()
        )
        meta = " · ".join(
            part
            for part in (a.get_activity_type_display(), context_label, place)
            if part
        )

        wfr_status = ""
        for line in cost_lines:
            for wfr_line in line.weekly_request_lines.all():
                raw = wfr_line.weekly_fund_request.status
                wfr_status = _WFR_LABELS.get(raw, raw.replace("_", " ").capitalize())
                break
            if wfr_status:
                break

        participants = (
            (a.teachers_attended or 0)
            + (a.leaders_attended or 0)
            + (a.other_participants or 0)
        ) or a.expected_participants

        rows.append(
            {
                "id": a.id,
                "date_label": _date_label(anchor, a.end_date),
                "band_month": band_month,
                "name": a.activity_name_snapshot or a.get_activity_type_display(),
                "meta": meta,
                "responsible": (
                    partner_map.get(a.assigned_partner_id, "Unassigned Partner")
                    if a.delivery_type == "partner"
                    else name_map.get(a.responsible_staff_id, "Unassigned")
                ),
                "responsibility_type": a.get_delivery_type_display(),
                "partner_name": partner_map.get(a.assigned_partner_id, "")
                if a.delivery_type == "partner"
                else "",
                "status": a.status,
                "status_label": status_label,
                "status_class": status_class,
                "status_tone": status_tone(status_class),
                "cost": a.lines_total or 0,
                "cost_missing": a.cost_missing,
                "action": action,
                # Expanded detail (server-rendered, no extra endpoint).
                "purpose": a.activity_purpose_text or "",
                "rationale": rationale_labels.get(a.support_rationale, ""),
                "focus_intervention": a.get_focus_intervention_display()
                if a.focus_intervention
                else "",
                "programme_activity_type": (
                    a.get_programme_activity_type_display()
                    if a.programme_activity_type
                    else a.get_activity_type_display()
                ),
                "programme_delivery_mode": (
                    a.get_programme_delivery_mode_display()
                    if a.programme_delivery_mode
                    else (a.delivery_method_snapshot or "").replace("_", " ").title()
                ),
                "school_count": a.planned_school_count,
                "venue": place,
                "participants": participants,
                "cost_lines": [
                    {"label": line.label, "amount": line.amount or 0}
                    for line in cost_lines
                ],
                "weekly_request_status": wfr_status or "Not yet requested",
                "evidence_status": a.get_evidence_status_display(),
            }
        )

    groups = list(bands.values())
    if undated_band["count"]:
        groups.append(undated_band)

    fy_totals = None
    if view == "fy":
        fy_totals = {
            "count": sum(g["count"] for g in groups),
            "cost": sum(g["cost"] for g in groups),
            "completed": sum(g["completed"] for g in groups),
            "at_risk": sum(g["at_risk"] for g in groups),
        }

    # Activities this calendar month — one COUNT over the scoped FY ledger.
    from datetime import date as _date

    month_start = _date(today.year, today.month, 1)
    month_end = _date(
        today.year,
        today.month,
        calendar.monthrange(today.year, today.month)[1],
    )
    activities_this_month = base_qs.filter(_window_q(month_start, month_end)).count()

    period_label = {
        "month": f"{calendar.month_name[period]} {_month_year(fy_int, period)}"
        if view == "month"
        else "",
        "quarter": f"{period} FY{fy}",
        "fy": f"FY{fy}",
    }[view] or f"FY{fy}"

    # Every tile is bound to its registry entry (apps.core.metrics): the
    # definition, unit, period and drilldown live with the metric, not in this
    # view — so the same number cannot mean two things on two pages.
    kpi_strip_items = render_strip(
        [
            render_metric(
                "work_plan_activities_planned",
                MetricValue.measured(len(activities)),
                drilldown_url=_query_string(query_state, flag=None),
            ),
            render_metric(
                "work_plan_activities_this_month",
                MetricValue.measured(activities_this_month),
                drilldown_url=_query_string(
                    query_state, view="month", period=today.month, flag=None
                ),
            ),
            render_metric(
                "work_plan_plan_derived_budget",
                MetricValue.measured(period_budget),
                drilldown_url=_query_string(query_state, flag=None),
            ),
            render_metric(
                "work_plan_pending_approval",
                MetricValue.measured(pending_approval_count),
                drilldown_url=_query_string(query_state, flag="pending_approval"),
            ),
            render_metric(
                "work_plan_cost_setup_required",
                MetricValue.measured(cost_missing_count),
                drilldown_url=_query_string(query_state, flag="cost_missing"),
            ),
            render_metric(
                "work_plan_activities_at_risk",
                MetricValue.measured(at_risk_count),
                drilldown_url=_query_string(query_state, flag="at_risk"),
            ),
        ]
    )

    view_tabs = [
        {
            "key": "month",
            "label": "Monthly",
            "url": _query_string(
                query_state,
                view="month",
                period=today.month if fy == operational_fy else 10,
                flag=None,
            ),
            "active": view == "month",
        },
        {
            "key": "quarter",
            "label": "Quarterly",
            "url": _query_string(
                query_state,
                view="quarter",
                period=current_quarter if fy == operational_fy else "Q1",
                flag=None,
            ),
            "active": view == "quarter",
        },
        {
            "key": "fy",
            "label": "FY",
            "url": _query_string(query_state, view="fy", period=None, flag=None),
            "active": view == "fy",
        },
    ]

    month_options = [
        {"val": m, "label": f"{calendar.month_name[m]} {_month_year(fy_int, m)}"}
        for m in FY_MONTH_ORDER
    ]

    responsible_options = sorted(
        {
            (a.responsible_staff_id, name_map.get(a.responsible_staff_id, "Staff"))
            for a in activities
            if a.responsible_staff_id
        },
        key=lambda pair: pair[1],
    )

    from apps.projects.scoping import scoped_projects

    project_options = list(scoped_projects(user).values("id", "name"))

    flag_labels = {
        "pending_approval": "Pending approval",
        "cost_missing": "Cost setup required",
        "at_risk": "At risk",
    }

    filters_active = any(
        (status, responsible, project_filter, activity_type, executor, flag)
    )

    from apps.planning.work_plan_approval import approval_context

    return {
        "fy": fy,
        "fy_options": options,
        "view": view,
        "period": period,
        "period_label": period_label,
        "view_tabs": view_tabs,
        "month_options": month_options,
        "quarter_options": list(QUARTER_MONTHS),
        "status_options": list(ActivityStatus.choices),
        "activity_type_options": list(ActivityType.choices),
        "executor_options": list(DeliveryType.choices),
        "responsible_options": responsible_options,
        "project_options": project_options,
        "selected_status": status,
        "selected_responsible": responsible,
        "selected_project": project_filter,
        "selected_activity_type": activity_type,
        "selected_executor": executor,
        "flag": flag,
        "flag_label": flag_labels.get(flag, ""),
        "clear_flag_url": _query_string(query_state, flag=None),
        "clear_filters_url": _query_string(
            {"fy": fy, "view": view, "period": str(period)}
        ),
        "filters_active": filters_active,
        "kpi_strip_items": kpi_strip_items,
        "groups": groups,
        "fy_totals": fy_totals,
        "rows": rows,
        "rows_visible": rows_visible,
        "total_activities": len(activities),
        "completed_activities": completed_count,
        "can_add_activity": has_permission(
            user, Permission.MANUAL_ACTIVITY_CREATE.value
        ),
        "can_export": has_permission(user, Permission.EXPORT.value),
        "work_plan_approval": approval_context(user, fy),
        # §18: the schedule-derived monthly plan. Computed by the canonical
        # service so the page never re-derives a target contribution or a cost
        # of its own — the two places would drift the first time either
        # changed.
        "monthly_plan": monthly_work_plan(staff_ids=_work_plan_staff_ids(user), fy=fy),
    }


def _work_plan_staff_ids(user) -> list[str]:
    """Whose scheduled work this Work Plan covers.

    A staff member sees their own; a manager sees themselves and the people
    they supervise, because a Work Plan that stops at the viewer cannot show a
    Program Lead what their team has committed the month to.
    """
    from apps.accounts.models import StaffSupervisorAssignment

    own = getattr(user, "staff_profile_id", None)
    if not own:
        return []
    ids = [str(own)]
    ids.extend(
        str(supervisee_id)
        for supervisee_id in StaffSupervisorAssignment.objects.filter(
            supervisor_id=own
        ).values_list("supervisee_id", flat=True)
    )
    return ids
