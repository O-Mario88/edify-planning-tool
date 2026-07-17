"""Role-scoped Special Projects My Plan dashboard.

This is a presentation service over the existing operational Activity ledger.
It deliberately does not create a second project-workflow state machine: every
row action resolves through ``apps.my_plan.services.compute_next_action`` and
partner-delivered work remains read-only to staff monitors.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.core.enums import ActivityStatus, ActivityType, SsaIntervention
from apps.core.fy import (
    fy_options,
    get_fy_date_range,
    get_operational_fy,
    get_quarter_date_range,
    get_quarter_for_date,
)
from apps.core.scoping import resolve_user_scope
from apps.analytics.platform_engine import planning_health
from apps.my_plan.services import (
    compute_next_action,
    get_activity_status_label_and_class,
)

from .dashboard_service import DELIVERED_STATUSES
from .models import Project


INTERVENTION_LABELS = dict(SsaIntervention.choices)
VISIT_TYPES = {
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "core_visit",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
    "core_assessment_visit",
}
TRAINING_TYPES = {
    "training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
    "cluster_training_ssa_collection",
}
ACTIVE_EXCLUSIONS = {"not_planned", "cancelled", "rejected", "closed"}
RETURNED_STATES = {"returned", "returned_by_pl", "returned_by_ia"}
REVIEW_STATES = {
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
}


def _project_queryset(principal, scope):
    qs = Project.objects.filter(deleted_at__isnull=True)
    if scope.country_scope:
        return qs
    if principal.active_role == "ProjectCoordinator" and principal.staff_profile_id:
        return qs.filter(manager_staff_id=principal.staff_profile_id)
    if scope.school_ids:
        return qs.filter(school_assignments__school_id__in=scope.school_ids).distinct()
    return qs.none()


def _fy_months(fy: str) -> list[dict]:
    end_year = int(fy)
    values = []
    for month in (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        year = end_year - 1 if month >= 10 else end_year
        values.append(
            {
                "value": str(month),
                "label": calendar.month_name[month],
                "year": year,
            }
        )
    return values


def _weeks_for_month(year: int, month: int) -> list[dict]:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    cursor = first - timedelta(days=first.weekday())
    weeks = []
    while cursor <= last:
        end = cursor + timedelta(days=6)
        weeks.append(
            {
                "value": cursor.isoformat(),
                "start": cursor,
                "end": end,
                "label": f"{cursor.strftime('%b')} {cursor.day} – {end.strftime('%b')} {end.day}",
            }
        )
        cursor += timedelta(days=7)
    return weeks


def _clean_choice(value, allowed, default=""):
    value = str(value or "").strip()
    return value if value in allowed else default


def _advance_status(activity) -> tuple[str, str]:
    cost_lines = list(activity.schedule_cost_lines.all())
    advances = []
    for line in cost_lines:
        advances.extend(list(line.advance_requests.all()))
    if not advances:
        return ("Not synced", "danger") if cost_lines else ("No budget", "neutral")
    states = {a.status for a in advances}
    if states & {"returned", "cancelled"}:
        return "Returned", "danger"
    if states & {"pending_responsible_confirmation", "draft_from_schedule"}:
        return "Confirmation due", "warning"
    if states & {"confirmed_for_advance", "submitted_to_accountant"}:
        return "Fund request synced", "info"
    if states & {"disbursed", "accountability_pending"}:
        return "Funds disbursed", "success"
    if states <= {"accounted", "reimbursed", "not_requested"}:
        return "Finance cleared", "success"
    return "Fund request synced", "info"


def _row(activity, partner_names, project_names, principal, today):
    status_label, _ = get_activity_status_label_and_class(activity, today)
    action = compute_next_action(activity, today)
    own_ids = {str(principal.id), str(principal.staff_profile_id or "")}
    can_act = (
        activity.delivery_type == "staff"
        and str(activity.responsible_staff_id or "") in own_ids
    )
    if not can_act:
        action = {
            "text": "View details",
            "action": "view",
            "url": f"/my-plan/{activity.id}",
            "description": "Monitoring only",
        }
    finance_label, finance_tone = _advance_status(activity)
    participants = sum(
        value or 0
        for value in (
            activity.teachers_attended,
            activity.leaders_attended,
            activity.other_participants,
        )
    )
    if activity.status in RETURNED_STATES:
        tone = "danger"
    elif activity.status in DELIVERED_STATUSES:
        tone = "success"
    elif activity.planned_date == today:
        tone = "warning"
    else:
        tone = "info"
    evidence_map = {
        "none": ("Not submitted", "danger"),
        "uploaded": ("Awaiting review", "warning"),
        "accepted": ("Submitted", "success"),
        "returned": ("Returned", "danger"),
        "rejected": ("Rejected", "danger"),
    }
    evidence_label, evidence_tone = evidence_map.get(
        activity.evidence_status, (activity.get_evidence_status_display(), "neutral")
    )
    return {
        "id": activity.id,
        "school": activity.school.name
        if activity.school_id
        else (activity.cluster.name if activity.cluster_id else "Unassigned"),
        "district": activity.school.district.name
        if activity.school_id and activity.school.district_id
        else (
            activity.cluster.district.name
            if activity.cluster_id and activity.cluster.district_id
            else "—"
        ),
        "project": project_names.get(activity.project_id, "—"),
        "planned_date": activity.planned_date,
        "purpose": activity.activity_purpose_text
        or activity.get_activity_type_display(),
        "focus": INTERVENTION_LABELS.get(
            activity.focus_intervention, "General support"
        ),
        "partner": partner_names.get(activity.assigned_partner_id, "—"),
        "participants": participants or "—",
        "status": status_label,
        "status_tone": tone,
        "evidence": evidence_label,
        "evidence_tone": evidence_tone,
        "finance": finance_label,
        "finance_tone": finance_tone,
        "readonly": activity.delivery_type == "partner" or not can_act,
        "action": action,
        "detail_url": f"/my-plan/{activity.id}",
        "rescheduled": (activity.reschedule_count or 0) > 0,
    }


def get_my_plan(principal, filters=None) -> dict:
    """Build the filtered Special Projects planning cockpit."""
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.fund_requests.models import AdvanceRequest
    from apps.geography.models import District, Region
    from apps.partners.models import Partner

    filters = filters or {}
    today = timezone.localdate()
    scope = resolve_user_scope(principal)
    projects = list(_project_queryset(principal, scope).order_by("name"))
    project_ids = [project.id for project in projects]
    project_names = {project.id: project.name for project in projects}

    selected_fy = _clean_choice(
        filters.get("fy"), set(fy_options(today)), get_operational_fy(today)
    )
    months = _fy_months(selected_fy)
    allowed_months = {m["value"] for m in months}
    selected_month = _clean_choice(
        filters.get("month"), allowed_months, str(today.month)
    )
    month_meta = next(m for m in months if m["value"] == selected_month)
    weeks = _weeks_for_month(month_meta["year"], int(selected_month))
    current_week_start = today - timedelta(days=today.weekday())
    default_week = (
        current_week_start.isoformat()
        if any(w["start"] == current_week_start for w in weeks)
        else weeks[0]["value"]
    )
    selected_week = _clean_choice(
        filters.get("week"), {w["value"] for w in weeks}, default_week
    )
    selected_week_meta = next(w for w in weeks if w["value"] == selected_week)
    selected_quarter = _clean_choice(
        filters.get("quarter"), {"Q1", "Q2", "Q3", "Q4"}, get_quarter_for_date(today)
    )
    selected_period = _clean_choice(
        filters.get("period"), {"week", "month", "quarter", "fy"}, "week"
    )

    terminal_requested = filters.get("status") in ACTIVE_EXCLUSIONS
    qs = Activity.objects.filter(
        deleted_at__isnull=True, project_id__in=project_ids
    ).filter(Q(fy=selected_fy) | Q(fiscal_year=selected_fy))
    if not terminal_requested:
        qs = qs.exclude(status__in=ACTIVE_EXCLUSIONS)

    selected_region = str(filters.get("region") or "")
    selected_district = str(filters.get("district") or "")
    selected_project = str(filters.get("project") or "")
    selected_partner = str(filters.get("partner") or "")
    selected_activity_type = str(filters.get("activity_type") or "")
    selected_status = str(filters.get("status") or "")
    search = str(filters.get("q") or "").strip()

    if selected_region:
        qs = qs.filter(
            Q(school__region_id=selected_region) | Q(cluster__region_id=selected_region)
        )
    if selected_district:
        qs = qs.filter(
            Q(school__district_id=selected_district)
            | Q(cluster__district_id=selected_district)
        )
    if selected_project in project_ids:
        qs = qs.filter(project_id=selected_project)
    else:
        selected_project = ""
    if selected_partner:
        qs = qs.filter(assigned_partner_id=selected_partner)
    if selected_activity_type:
        qs = qs.filter(activity_type=selected_activity_type)
    if selected_status:
        if selected_status == "returned":
            qs = qs.filter(status__in=RETURNED_STATES)
        elif selected_status == "review":
            qs = qs.filter(status__in=REVIEW_STATES)
        else:
            qs = qs.filter(status=selected_status)
    if search:
        qs = qs.filter(
            Q(school__name__icontains=search)
            | Q(cluster__name__icontains=search)
            | Q(school__district__name__icontains=search)
            | Q(activity_purpose_text__icontains=search)
        )

    base_qs = qs.distinct()
    week_start, week_end = selected_week_meta["start"], selected_week_meta["end"]
    month_start = date(month_meta["year"], int(selected_month), 1)
    month_end = date(
        month_meta["year"],
        int(selected_month),
        calendar.monthrange(month_meta["year"], int(selected_month))[1],
    )
    quarter_start_dt, quarter_end_dt = get_quarter_date_range(
        selected_fy, selected_quarter
    )
    fy_start_dt, fy_end_dt = get_fy_date_range(selected_fy)
    ranges = {
        "week": (week_start, week_end),
        "month": (month_start, month_end),
        "quarter": (quarter_start_dt.date(), quarter_end_dt.date() - timedelta(days=1)),
        "fy": (fy_start_dt.date(), fy_end_dt.date() - timedelta(days=1)),
    }
    period_start, period_end = ranges[selected_period]
    period_qs = base_qs.filter(planned_date__range=(period_start, period_end))

    lines = ActivityScheduleCostLine.objects.prefetch_related("advance_requests")
    activities = list(
        period_qs.select_related(
            "school",
            "school__district",
            "school__region",
            "cluster",
            "cluster__district",
            "cluster__region",
        )
        .prefetch_related(Prefetch("schedule_cost_lines", queryset=lines))
        .order_by("planned_date", "created_at")
    )
    all_partner_ids = set(
        base_qs.exclude(assigned_partner_id__isnull=True).values_list(
            "assigned_partner_id", flat=True
        )
    )
    partner_names = {
        p.id: p.name
        for p in Partner.objects.filter(id__in=all_partner_ids).order_by("name")
    }
    rows = [
        _row(activity, partner_names, project_names, principal, today)
        for activity in activities
    ]

    visits = [
        row
        for row, activity in zip(rows, activities)
        if activity.activity_type in VISIT_TYPES and activity.delivery_type == "staff"
    ]
    trainings = [
        row
        for row, activity in zip(rows, activities)
        if activity.activity_type in TRAINING_TYPES
        and activity.delivery_type == "staff"
    ]
    partner_activities = [
        row
        for row, activity in zip(rows, activities)
        if activity.delivery_type == "partner"
    ]

    def count_range(start, end):
        return base_qs.filter(planned_date__range=(start, end)).count()

    breakdown = {
        "week": count_range(week_start, week_end),
        "month": count_range(month_start, month_end),
        "quarter": count_range(ranges["quarter"][0], ranges["quarter"][1]),
        "fy": count_range(ranges["fy"][0], ranges["fy"][1]),
    }
    total_period = len(activities)
    completed_period = sum(1 for a in activities if a.status in DELIVERED_STATUSES)
    completion = round(completed_period / total_period * 100) if total_period else 0
    kpis = [
        {
            "label": "Planned This Week",
            "value": breakdown["week"],
            "helper": "activities",
            "tone": "blue",
            "icon": "calendar",
        },
        {
            "label": "Planned This Month",
            "value": breakdown["month"],
            "helper": "activities",
            "tone": "green",
            "icon": "calendar",
        },
        {
            "label": "Planned This Quarter",
            "value": breakdown["quarter"],
            "helper": "activities",
            "tone": "purple",
            "icon": "calendar",
        },
        {
            "label": "Planned This FY",
            "value": breakdown["fy"],
            "helper": "activities",
            "tone": "orange",
            "icon": "calendar",
        },
        {
            "label": "School Visits Scheduled",
            "value": len(visits),
            "helper": "visits in period",
            "tone": "blue",
            "icon": "school",
        },
        {
            "label": "Partner Activities",
            "value": len(partner_activities),
            "helper": "monitoring only",
            "tone": "purple",
            "icon": "partner",
        },
        {
            "label": "Project Trainings",
            "value": len(trainings),
            "helper": "trainings in period",
            "tone": "teal",
            "icon": "training",
        },
        {
            "label": "Completion Readiness",
            "value": f"{completion}%",
            "helper": "workflow complete",
            "tone": "green",
            "icon": "check",
        },
    ]

    period_ids = [a.id for a in activities]
    advance_activity_ids = set(
        AdvanceRequest.objects.filter(activity_id__in=period_ids).values_list(
            "activity_id", flat=True
        )
    )
    budget_activity_ids = set(
        ActivityScheduleCostLine.objects.filter(activity_id__in=period_ids).values_list(
            "activity_id", flat=True
        )
    )
    evidence_pending = sum(
        1
        for a in activities
        if a.status in {"completed", "evidence_uploaded"}
        and a.evidence_status != "accepted"
    )
    ia_pending = sum(1 for a in activities if a.status == "awaiting_ia_verification")
    workflow = [
        {
            "label": "Budget Created",
            "value": f"{len(budget_activity_ids)} / {total_period}",
            "tone": "success",
        },
        {
            "label": "Fund Request Synced",
            "value": f"{len(advance_activity_ids)} / {total_period}",
            "tone": "success"
            if len(advance_activity_ids) == total_period and total_period
            else "warning",
        },
        {
            "label": "Evidence Pending",
            "value": f"{evidence_pending} / {total_period}",
            "tone": "warning" if evidence_pending else "success",
        },
        {
            "label": "IA Review Pending",
            "value": f"{ia_pending} / {total_period}",
            "tone": "danger" if ia_pending else "success",
        },
    ]

    attention = []
    for activity, row in zip(activities, rows):
        if len(attention) >= 5:
            break
        if activity.status in RETURNED_STATES:
            issue, tone = "Returned for correction", "danger"
        elif activity.reschedule_count:
            issue, tone = f"Rescheduled {activity.reschedule_count} time(s)", "danger"
        elif (
            activity.status in {"completed", "evidence_uploaded"}
            and activity.evidence_status != "accepted"
        ):
            issue, tone = "Evidence needs attention", "warning"
        elif (
            activity.delivery_type == "partner"
            and activity.status == "assigned_to_partner"
        ):
            issue, tone = "Partner confirmation pending", "warning"
        elif activity.status == "awaiting_ia_verification":
            issue, tone = "IA review pending", "info"
        elif (
            activity.planned_date
            and activity.planned_date < today
            and activity.status in {"scheduled", "in_progress"}
        ):
            issue, tone = "Activity is overdue", "danger"
        else:
            continue
        attention.append(
            {
                "id": activity.id,
                "title": row["school"],
                "issue": issue,
                "tone": tone,
                "url": row["detail_url"],
            }
        )

    upcoming = [
        row for row, activity in zip(rows, activities) if activity.planned_date == today
    ][:4]
    plan_analytics = planning_health(
        total=total_period,
        ready=completed_period,
        scheduled=total_period,
        at_risk=len(attention),
        overdue=sum(
            1
            for activity in activities
            if activity.planned_date
            and activity.planned_date < today
            and activity.status in {"scheduled", "in_progress"}
        ),
    )
    recommended = next(
        (
            row
            for row in rows
            if not row["readonly"] and row["action"]["action"] != "view"
        ),
        None,
    )
    recommendation = {
        "title": recommended["action"]["text"]
        if recommended
        else "Review the project plan",
        "message": recommended["action"]["description"]
        if recommended
        else (
            "No workflow action is due in this period."
            if total_period
            else "There are no activities in the selected period."
        ),
        "action_text": recommended["action"]["text"]
        if recommended
        else "Open project planning",
        "action_url": recommended["action"]["url"]
        if recommended
        else "/projects/planning",
        "drawer": bool(recommended),
    }

    region_ids = set(
        base_qs.exclude(school__region_id__isnull=True).values_list(
            "school__region_id", flat=True
        )
    )
    district_options = (
        District.objects.filter(
            Q(schools__activities__project_id__in=project_ids)
            | Q(clusters__activities__project_id__in=project_ids)
        )
        .distinct()
        .order_by("name")
    )
    if selected_region:
        district_options = district_options.filter(region_id=selected_region)
    regions = Region.objects.filter(id__in=region_ids).order_by("name")
    partner_options = Partner.objects.filter(id__in=all_partner_ids).order_by("name")
    activity_type_values = list(
        base_qs.values_list("activity_type", flat=True)
        .distinct()
        .order_by("activity_type")
    )
    activity_type_labels = dict(ActivityType.choices)

    period_labels = {
        "week": f"{week_start.strftime('%b')} {week_start.day} – {week_end.strftime('%b')} {week_end.day}, {week_end.year}",
        "month": f"{calendar.month_name[int(selected_month)]} {month_meta['year']}",
        "quarter": f"{selected_quarter} · FY {selected_fy}",
        "fy": f"FY {selected_fy}",
    }
    selected = {
        "fy": selected_fy,
        "quarter": selected_quarter,
        "month": selected_month,
        "week": selected_week,
        "region": selected_region,
        "district": selected_district,
        "project": selected_project,
        "partner": selected_partner,
        "activity_type": selected_activity_type,
        "status": selected_status,
        "period": selected_period,
        "q": search,
    }
    export_query = urlencode(
        {**{k: v for k, v in selected.items() if v}, "export": "csv"}
    )
    calendar_query = urlencode(
        {
            "project_scope": "special",
            "project": selected_project,
            "month": selected_month,
            "year": month_meta["year"],
        }
    )

    return {
        "live": True,
        "has_projects": bool(project_ids),
        "has_activities": bool(activities),
        "projects": projects,
        "regions": regions,
        "districts": district_options,
        "partners": partner_options,
        "activity_types": [
            {
                "value": value,
                "label": activity_type_labels.get(
                    value, value.replace("_", " ").title()
                ),
            }
            for value in activity_type_values
        ],
        "status_options": [
            {"value": ActivityStatus.SCHEDULED, "label": "Scheduled"},
            {"value": ActivityStatus.IN_PROGRESS, "label": "In progress"},
            {"value": "returned", "label": "Returned"},
            {"value": "review", "label": "In review"},
            {"value": ActivityStatus.COMPLETED, "label": "Completed"},
            {"value": ActivityStatus.RESCHEDULED, "label": "Rescheduled"},
        ],
        "fy_options": fy_options(today),
        "months": months,
        "weeks": weeks,
        "quarters": ["Q1", "Q2", "Q3", "Q4"],
        "selected": selected,
        "period_label": period_labels[selected_period],
        "period_count": total_period,
        "kpis": kpis,
        "visits": visits[:25],
        "trainings": trainings[:25],
        "partner_activities": partner_activities[:25],
        "upcoming": upcoming,
        "attention": attention,
        "workflow": workflow,
        "analytics": plan_analytics,
        "recommendation": recommendation,
        "breakdown": breakdown,
        "export_url": f"/projects/my-plan?{export_query}",
        "calendar_url": f"/calendar?{calendar_query}",
    }
