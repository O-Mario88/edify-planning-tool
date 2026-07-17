"""Live Special Projects planning queue.

The only intake is ``ProjectSchoolAssignment`` (created by School Directory →
Assign to Project).  From there each school/project pair is evaluated against
the current FY SSA and project-stamped Activity ledger so one project's work
cannot accidentally advance another project's planning state.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone

from apps.core.enums import (
    ActivityStatus,
    ActivityType,
    SsaIntervention,
    ssa_score_band,
)
from apps.core.fy import fy_options, get_operational_fy, get_quarter_for_date
from apps.core.permissions import RolePermissionService
from apps.core.scoping import resolve_user_scope
from apps.analytics.platform_engine import planning_health

from .dashboard_service import _fmt_ugx
from .models import Project, ProjectCategory, ProjectSchoolAssignment


INTERVENTION_LABELS = dict(SsaIntervention.choices)
PROJECT_TYPE_LABELS = dict(ProjectCategory.choices)
ACTIVE_ACTIVITY_STATES = {
    ActivityStatus.PLANNED,
    ActivityStatus.SCHEDULED,
    ActivityStatus.ASSIGNED_TO_PARTNER,
    ActivityStatus.PARTNER_SCHEDULED,
    ActivityStatus.IN_PROGRESS,
    ActivityStatus.COMPLETION_STARTED,
    ActivityStatus.EVIDENCE_UPLOADED,
    ActivityStatus.EVIDENCE_ACCEPTED,
    ActivityStatus.SALESFORCE_ID_REQUIRED,
    ActivityStatus.SUBMITTED_TO_PL,
    ActivityStatus.RETURNED_BY_PL,
    ActivityStatus.AWAITING_IA_VERIFICATION,
    ActivityStatus.IA_VERIFIED,
    ActivityStatus.ACCOUNTANT_CONFIRMED,
    ActivityStatus.COMPLETED,
    ActivityStatus.RETURNED,
    ActivityStatus.RETURNED_BY_IA,
    ActivityStatus.RESCHEDULED,
}
RETURNED_STATES = {
    ActivityStatus.RETURNED,
    ActivityStatus.RETURNED_BY_PL,
    ActivityStatus.RETURNED_BY_IA,
}


def _clean_choice(value, allowed, default=""):
    value = str(value or "").strip()
    return value if value in allowed else default


def _scoped_projects(principal):
    """Projects visible to the caller — the ONE project scope rule.

    Ecosystem audit: this function used to widen access by school overlap
    (any coordinator whose portfolio intersected another coordinator's
    project could open its planning queue and impact matrix), while
    my_plan_service and dashboard_service restricted a ProjectCoordinator to
    manager_staff_id only. All four surfaces now share this rule:
    coordinators see ONLY projects they manage; country roles see all;
    non-coordinator school-scoped roles (PL oversight) keep the portfolio
    lens for supervision."""
    scope = resolve_user_scope(principal)
    qs = Project.objects.filter(deleted_at__isnull=True)
    if scope.country_scope:
        return qs.order_by("name")

    staff_id = getattr(principal, "staff_profile_id", None)
    if getattr(principal, "active_role", "") == "ProjectCoordinator":
        if not staff_id:
            return qs.none()
        return qs.filter(manager_staff_id=staff_id).order_by("name")

    school_ids = list(scope.school_ids or [])
    project_filter = Q()
    if staff_id:
        project_filter |= Q(manager_staff_id=staff_id)
    if school_ids:
        project_filter |= Q(school_assignments__school_id__in=school_ids)
    if not project_filter:
        return qs.none()
    return qs.filter(project_filter).distinct().order_by("name")


def _activity_state(activity):
    if not activity:
        return ("Not planned", "neutral")
    status = activity.get_status_display()
    if activity.status in RETURNED_STATES:
        return (status, "danger")
    if activity.status in {
        ActivityStatus.COMPLETED,
        ActivityStatus.IA_VERIFIED,
        ActivityStatus.ACCOUNTANT_CONFIRMED,
        ActivityStatus.CLOSED,
    }:
        return (status, "success")
    if activity.status in {
        ActivityStatus.AWAITING_IA_VERIFICATION,
        ActivityStatus.SUBMITTED_TO_PL,
        ActivityStatus.EVIDENCE_UPLOADED,
    }:
        return (status, "info")
    if activity.delivery_type == "partner":
        return (status, "purple")
    return (status, "warning")


def _row_state(latest_ssa, activities):
    latest_activity = activities[0] if activities else None
    if latest_ssa is None:
        baseline_activity = next(
            (activity for activity in activities if activity.ssa_collection_expected),
            None,
        )
        if baseline_activity:
            label, tone = _activity_state(baseline_activity)
            return {
                "bucket": "baseline",
                "baseline": "Baseline scheduled",
                "baseline_tone": "warning",
                "readiness": label,
                "readiness_tone": tone,
                "action": "Monitor baseline SSA visit",
                "next_step": "Complete the planned SSA collection before support activities are scheduled.",
                "action_kind": "my_plan",
                "activity": baseline_activity,
            }
        return {
            "bucket": "baseline",
            "baseline": "No baseline",
            "baseline_tone": "danger",
            "readiness": "Baseline required",
            "readiness_tone": "danger",
            "action": "Schedule baseline SSA visit",
            "next_step": "Establish the current intervention scores before planning project support.",
            "action_kind": "schedule",
            "activity": None,
        }

    baseline_label = f"Baseline complete · {latest_ssa.date_of_ssa:%d %b %Y}"
    if not latest_activity:
        return {
            "bucket": "ready",
            "baseline": baseline_label,
            "baseline_tone": "success",
            "readiness": "Ready for support",
            "readiness_tone": "warning",
            "action": "Schedule recommended support",
            "next_step": "Use the weakest SSA intervention to plan a targeted visit or training.",
            "action_kind": "schedule",
            "activity": None,
        }

    status_label, status_tone = _activity_state(latest_activity)
    partner_pending = (
        latest_activity.delivery_type == "partner"
        and latest_activity.status
        in {
            ActivityStatus.ASSIGNED_TO_PARTNER,
            ActivityStatus.PLANNED,
        }
    )
    return {
        "bucket": "partner" if partner_pending else "scheduled",
        "baseline": baseline_label,
        "baseline_tone": "success",
        "readiness": status_label,
        "readiness_tone": status_tone,
        "action": "Monitor partner scheduling"
        if partner_pending
        else "Open activity in My Plan",
        "next_step": (
            "Confirm the partner's delivery date and monitor the evidence workflow."
            if partner_pending
            else "Continue this activity through completion, evidence, review, and finance clearance."
        ),
        "action_kind": "my_plan",
        "activity": latest_activity,
    }


def _weakest(latest_ssa):
    if latest_ssa is None:
        return ("Not assessed", None)
    scores = sorted(latest_ssa.scores.all(), key=lambda score: score.score)
    if not scores:
        return ("Not assessed", None)
    score = scores[0]
    return (
        INTERVENTION_LABELS.get(score.intervention, score.intervention),
        score.score,
    )


def get_planning(principal, filters=None) -> dict:
    """Return the filtered, paginated project-school planning workspace."""
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.geography.models import District, Region
    from apps.partners.models import Partner
    from apps.ssa.models import SsaRecord

    filters = filters or {}
    today = timezone.localdate()
    current_fy = get_operational_fy(today)
    selected_fy = _clean_choice(filters.get("fy"), set(fy_options(today)), current_fy)
    selected_quarter = _clean_choice(
        filters.get("quarter"), {"Q1", "Q2", "Q3", "Q4"}, get_quarter_for_date(today)
    )
    selected_tab = _clean_choice(
        filters.get("tab"), {"all", "baseline", "ready", "partner", "scheduled"}, "all"
    )
    selected_project = str(filters.get("project") or "").strip()
    selected_region = str(filters.get("region") or "").strip()
    selected_district = str(filters.get("district") or "").strip()
    selected_staff = str(filters.get("staff") or "").strip()
    selected_project_type = str(filters.get("project_type") or "").strip()
    selected_partner_type = _clean_choice(
        filters.get("partner_type"), {"staff", "partner", "unassigned"}
    )
    selected_activity_type = str(filters.get("activity_type") or "").strip()
    search = str(filters.get("q") or "").strip()

    projects = list(_scoped_projects(principal))
    project_ids = [project.id for project in projects]
    if selected_project not in project_ids:
        selected_project = ""

    ssa_prefetch = Prefetch(
        "school__ssa_records",
        queryset=SsaRecord.objects.filter(fy=selected_fy, deleted_at__isnull=True)
        .prefetch_related("scores")
        .order_by("-date_of_ssa"),
        to_attr="planning_ssa_records",
    )
    assignments_qs = (
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .select_related("project", "school", "school__region", "school__district")
        .prefetch_related(ssa_prefetch)
        .order_by("school__name", "project__name")
    )
    if selected_project:
        assignments_qs = assignments_qs.filter(project_id=selected_project)
    if selected_region:
        assignments_qs = assignments_qs.filter(school__region_id=selected_region)
    if selected_district:
        assignments_qs = assignments_qs.filter(school__district_id=selected_district)
    if selected_staff:
        assignments_qs = assignments_qs.filter(project__manager_staff_id=selected_staff)
    if selected_project_type:
        assignments_qs = assignments_qs.filter(
            Q(project_type=selected_project_type)
            | Q(project__category=selected_project_type)
        )
    if search:
        assignments_qs = assignments_qs.filter(
            Q(school__name__icontains=search)
            | Q(school__school_id__icontains=search)
            | Q(project__name__icontains=search)
            | Q(school__district__name__icontains=search)
        )
    assignments = list(assignments_qs)

    activity_qs = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            project_id__in=project_ids,
            fy=selected_fy,
            quarter=selected_quarter,
            school_id__isnull=False,
        )
        .exclude(
            status__in=[
                ActivityStatus.CANCELLED,
                ActivityStatus.REJECTED,
                ActivityStatus.DEFERRED,
            ]
        )
        .select_related("school")
        .order_by("-created_at")
    )
    activities = list(activity_qs)
    activities_by_pair = defaultdict(list)
    for activity in activities:
        activities_by_pair[(activity.project_id, activity.school_id)].append(activity)

    partner_ids = {a.assigned_partner_id for a in activities if a.assigned_partner_id}
    partner_names = {
        partner.id: partner.name
        for partner in Partner.objects.filter(id__in=partner_ids)
    }

    rows = []
    for assignment in assignments:
        school = assignment.school
        project = assignment.project
        pair_activities = activities_by_pair.get((project.id, school.id), [])
        if selected_activity_type and not any(
            activity.activity_type == selected_activity_type
            for activity in pair_activities
        ):
            continue
        if selected_partner_type == "partner" and not any(
            a.delivery_type == "partner" for a in pair_activities
        ):
            continue
        if selected_partner_type == "staff" and not any(
            a.delivery_type == "staff" for a in pair_activities
        ):
            continue
        if selected_partner_type == "unassigned" and pair_activities:
            continue

        latest_ssa = (
            school.planning_ssa_records[0] if school.planning_ssa_records else None
        )
        state = _row_state(latest_ssa, pair_activities)
        if selected_tab != "all" and state["bucket"] != selected_tab:
            continue
        weakest, weakest_score = _weakest(latest_ssa)
        average = (
            round(latest_ssa.average_score, 2)
            if latest_ssa and latest_ssa.average_score is not None
            else None
        )
        risk_label, _risk_color, risk_tone = ssa_score_band(average)
        latest_activity = state["activity"]
        partner_name = (
            partner_names.get(latest_activity.assigned_partner_id, "—")
            if latest_activity
            else "—"
        )
        project_type = assignment.project_type or PROJECT_TYPE_LABELS.get(
            project.category, project.category.replace("_", " ").title()
        )
        my_plan_url = (
            f"/projects/my-plan?{urlencode({'project': project.id, 'q': school.name})}"
        )
        rows.append(
            {
                "assignment_id": assignment.id,
                "school_pk": school.id,
                "school_id": school.school_id,
                "school_name": school.name,
                "district": school.district.name,
                "district_id": school.district_id,
                "region": school.region.name,
                "region_id": school.region_id,
                "project_id": project.id,
                "project_name": project.name,
                "project_type": project_type,
                "school_type": school.get_school_type_display(),
                "baseline_status": state["baseline"],
                "baseline_tone": state["baseline_tone"],
                "readiness": state["readiness"],
                "readiness_tone": state["readiness_tone"],
                "action": state["action"],
                "next_step": state["next_step"],
                "action_kind": state["action_kind"],
                "bucket": state["bucket"],
                "weakest": weakest,
                "weakest_score": weakest_score,
                "average": average,
                "risk_label": risk_label,
                "risk_tone": risk_tone,
                "partner": partner_name,
                "activity_type": latest_activity.get_activity_type_display()
                if latest_activity
                else "—",
                "planned_date": latest_activity.planned_date
                if latest_activity
                else None,
                "schedule_url": f"/planning/schedule-modal?{urlencode({'school_id': school.id, 'project_id': project.id})}",
                "partner_url": f"/planning/assign-partner-modal?{urlencode({'school_id': school.id, 'project_id': project.id})}",
                "my_plan_url": my_plan_url,
                "school_url": f"/schools/{school.id}",
                "ssa_url": f"/schools/{school.id}#ssa-timeline",
                "project_url": f"/projects/{project.id}",
                "manager_staff_id": project.manager_staff_id or "",
            }
        )

    # Tab counts are calculated after all non-readiness filters.
    tab_counts = {"all": 0, "baseline": 0, "ready": 0, "partner": 0, "scheduled": 0}
    # Rebuild only when a tab was applied, preserving accurate navigation counts.
    if selected_tab == "all":
        count_source = rows
    else:
        shadow_filters = dict(filters)
        shadow_filters["tab"] = "all"
        shadow_filters["page"] = 1
        shadow = (
            get_planning(principal, {**shadow_filters, "_counts_only": "1"})
            if not filters.get("_counts_only")
            else None
        )
        count_source = None
        if shadow:
            tab_counts = shadow["tab_counts"]
    if count_source is not None:
        tab_counts["all"] = len(count_source)
        for row in count_source:
            tab_counts[row["bucket"]] += 1

    page_size = (
        int(filters.get("per_page") or 10)
        if str(filters.get("per_page") or "10").isdigit()
        else 10
    )
    page_size = page_size if page_size in {10, 25, 50} else 10
    paginator = Paginator(rows, page_size)
    page_obj = paginator.get_page(filters.get("page") or 1)
    page_rows = list(page_obj.object_list)

    selected_assignment = str(filters.get("selected") or "")
    selected_row = next(
        (row for row in page_rows if row["assignment_id"] == selected_assignment), None
    )
    if selected_row is None and page_rows:
        selected_row = page_rows[0]
        selected_assignment = selected_row["assignment_id"]

    all_filtered_rows = rows
    baseline_count = sum(1 for row in all_filtered_rows if row["bucket"] == "baseline")
    partner_count = sum(1 for row in all_filtered_rows if row["bucket"] == "partner")
    high_risk = sum(
        1
        for row in all_filtered_rows
        if row["average"] is not None and row["average"] < 5
    )
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    scheduled_week = sum(
        1
        for activity in activities
        if activity.planned_date
        and week_start <= activity.planned_date <= week_end
        and activity.status in ACTIVE_ACTIVITY_STATES
    )
    planned_pairs = {
        (activity.project_id, activity.school_id)
        for activity in activities
        if activity.status in ACTIVE_ACTIVITY_STATES
    }
    completion = (
        round(len(planned_pairs) / len(assignments) * 100) if assignments else 0
    )
    followup = sum(
        1
        for activity in activities
        if activity.status in RETURNED_STATES
        or activity.reschedule_count
        or (
            activity.planned_date
            and activity.planned_date < today
            and activity.status
            in {ActivityStatus.SCHEDULED, ActivityStatus.IN_PROGRESS}
        )
    )
    analytics = planning_health(
        total=len(assignments),
        ready=len(planned_pairs),
        scheduled=tab_counts["scheduled"],
        at_risk=high_risk,
        overdue=followup,
    )

    kpis = [
        {
            "label": "Total Project Schools",
            "value": len(assignments),
            "helper": "school–project assignments",
            "tone": "blue",
            "icon": "school",
        },
        {
            "label": "Without Baseline / SSA",
            "value": baseline_count,
            "helper": f"FY {selected_fy}",
            "tone": "orange",
            "icon": "warning",
        },
        {
            "label": "Assigned to Partner",
            "value": partner_count,
            "helper": "awaiting or partner-led",
            "tone": "purple",
            "icon": "partner",
        },
        {
            "label": "Scheduled This Week",
            "value": scheduled_week,
            "helper": "project activities",
            "tone": "green",
            "icon": "calendar",
        },
        {
            "label": "Schools in Active Projects",
            "value": len({a.school_id for a in assignments}),
            "helper": f"across {len({a.project_id for a in assignments})} projects",
            "tone": "teal",
            "icon": "folder",
        },
        {
            "label": "Planning Completion",
            "value": f"{completion}%",
            "helper": "project pairs with an activity",
            "tone": "blue",
            "icon": "chart",
        },
        {
            "label": "High-Risk Project Schools",
            "value": high_risk,
            "helper": "SSA average below 5.0",
            "tone": "red",
            "icon": "risk",
        },
        {
            "label": "Schools Requiring Follow-up",
            "value": followup,
            "helper": "returned, overdue or rescheduled",
            "tone": "orange",
            "icon": "clock",
        },
    ]

    band_cards = [
        {
            "label": "Baseline Required",
            "value": tab_counts["baseline"],
            "pct": round(tab_counts["baseline"] / max(tab_counts["all"], 1) * 100),
            "tone": "red",
            "icon": "document",
            "trend": "Complete SSA before support planning",
        },
        {
            "label": "Ready for Scheduling",
            "value": tab_counts["ready"],
            "pct": round(tab_counts["ready"] / max(tab_counts["all"], 1) * 100),
            "tone": "orange",
            "icon": "calendar",
            "trend": "Use SSA recommendations",
        },
        {
            "label": "Ready for Partner Assignment",
            "value": tab_counts["partner"],
            "pct": round(tab_counts["partner"] / max(tab_counts["all"], 1) * 100),
            "tone": "green",
            "icon": "partner",
            "trend": "Monitor delivery confirmation",
        },
    ]

    summary = []
    for project in projects:
        project_rows = [
            row for row in all_filtered_rows if row["project_id"] == project.id
        ]
        if not project_rows and selected_project:
            continue
        assigned = len(project_rows)
        ready = sum(
            1
            for row in project_rows
            if row["bucket"] in {"ready", "partner", "scheduled"}
        )
        summary.append(
            {
                "name": project.name,
                "url": f"/projects/{project.id}",
                "assigned": assigned,
                "ready": ready,
                "ready_pct": round(ready / assigned * 100) if assigned else 0,
                "baseline": sum(
                    1 for row in project_rows if row["bucket"] == "baseline"
                ),
                "partner": sum(1 for row in project_rows if row["bucket"] == "partner"),
                "scheduled": sum(
                    1 for row in project_rows if row["bucket"] == "scheduled"
                ),
            }
        )

    activity_ids = [activity.id for activity in activities]
    budget = (
        ActivityScheduleCostLine.objects.filter(activity_id__in=activity_ids).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    visit_pending = sum(
        1
        for activity in activities
        if "visit" in activity.activity_type
        and activity.status in ACTIVE_ACTIVITY_STATES
    )
    training_pending = sum(
        1
        for activity in activities
        if "training" in activity.activity_type
        and activity.status in ACTIVE_ACTIVITY_STATES
    )
    delivery = [
        {
            "label": "No Baseline",
            "value": baseline_count,
            "tone": "red",
            "helper": "SSA needed",
        },
        {
            "label": "Visit Pending",
            "value": visit_pending,
            "tone": "orange",
            "helper": "active workflow",
        },
        {
            "label": "Training Pending",
            "value": training_pending,
            "tone": "blue",
            "helper": "active workflow",
        },
        {
            "label": "Partner Assignment Pending",
            "value": partner_count,
            "tone": "purple",
            "helper": "partner-led",
        },
        {
            "label": "High-Risk Schools",
            "value": high_risk,
            "tone": "red",
            "helper": "SSA below 5.0",
        },
    ]

    region_ids = {assignment.school.region_id for assignment in assignments_qs}
    district_options = District.objects.filter(
        id__in={assignment.school.district_id for assignment in assignments_qs}
    ).order_by("name")
    if selected_region:
        district_options = district_options.filter(region_id=selected_region)
    manager_ids = {
        project.manager_staff_id for project in projects if project.manager_staff_id
    }
    staff_options = (
        StaffProfile.objects.filter(id__in=manager_ids)
        .select_related("user")
        .order_by("user__name")
    )
    project_types = sorted(
        {
            assignment.project_type or assignment.project.category
            for assignment in assignments
        }
    )
    activity_values = sorted({activity.activity_type for activity in activities})
    activity_labels = dict(ActivityType.choices)

    selected = {
        "fy": selected_fy,
        "quarter": selected_quarter,
        "region": selected_region,
        "district": selected_district,
        "staff": selected_staff,
        "project": selected_project,
        "project_type": selected_project_type,
        "partner_type": selected_partner_type,
        "activity_type": selected_activity_type,
        "tab": selected_tab,
        "q": search,
        "selected": selected_assignment,
        "per_page": page_size,
    }
    stable_query = {
        key: value for key, value in selected.items() if value and key != "selected"
    }
    export_url = f"/projects/planning?{urlencode({**stable_query, 'export': 'csv'})}"
    for row in page_rows:
        row["select_url"] = (
            f"/projects/planning?{urlencode({**stable_query, 'page': page_obj.number, 'selected': row['assignment_id']})}"
        )
    page_links = []
    for number in paginator.get_elided_page_range(
        page_obj.number, on_each_side=1, on_ends=1
    ):
        page_links.append(
            {
                "label": number,
                "current": number == page_obj.number,
                "url": f"/projects/planning?{urlencode({**stable_query, 'page': number})}"
                if isinstance(number, int)
                else "",
            }
        )

    return {
        "has_projects": bool(project_ids),
        "has_assignments": bool(assignments),
        "projects": projects,
        "regions": Region.objects.filter(id__in=region_ids).order_by("name"),
        "districts": district_options,
        "staff_options": staff_options,
        "project_types": [
            {
                "value": value,
                "label": PROJECT_TYPE_LABELS.get(
                    value, value.replace("_", " ").title()
                ),
            }
            for value in project_types
        ],
        "partner_types": [
            {"value": "staff", "label": "Staff-led"},
            {"value": "partner", "label": "Partner-led"},
            {"value": "unassigned", "label": "Not assigned"},
        ],
        "activity_types": [
            {
                "value": value,
                "label": activity_labels.get(value, value.replace("_", " ").title()),
            }
            for value in activity_values
        ],
        "fy_options": fy_options(today),
        "quarters": ["Q1", "Q2", "Q3", "Q4"],
        "selected": selected,
        "rows": page_rows,
        "export_rows": all_filtered_rows,
        "selected_row": selected_row,
        "page_obj": page_obj,
        "page_links": page_links,
        "result_start": page_obj.start_index() if paginator.count else 0,
        "result_end": page_obj.end_index() if paginator.count else 0,
        "total": paginator.count,
        "tab_counts": tab_counts,
        "kpis": kpis,
        "band_cards": band_cards,
        "summary": summary[:8],
        "delivery": delivery,
        "analytics": analytics,
        "budget": _fmt_ugx(budget),
        "export_url": export_url,
        "can_schedule": RolePermissionService.can_schedule_activity(principal),
        "can_assign_partner": RolePermissionService.can_assign_to_partner(principal),
    }
