"""Special-project My Plan — the coordinator's scheduled project activities.

Receives everything scheduled from the Special Projects Planning page (activities
stamped with `project_id`). Staff-owned project visits/trainings are actionable;
partner-planned project activities appear read-only (monitoring), exactly like
staff monitoring partner work in the normal engine.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

from .dashboard_service import DELIVERED_STATUSES
from .models import Project

INTERVENTION_LABELS = dict(SsaIntervention.choices)
VISIT_TYPES = ["school_visit", "follow_up_visit", "coaching_visit", "core_visit"]
TRAINING_TYPES = [
    "training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
]

STATUS_LABEL = {
    "scheduled": ("Scheduled", "info"),
    "assigned_to_partner": ("Assigned", "purple"),
    "partner_scheduled": ("Partner Scheduled", "info"),
    "in_progress": ("In Progress", "warning"),
    "completion_started": ("Completing", "warning"),
    "evidence_uploaded": ("Evidence In", "info"),
    "awaiting_ia_verification": ("Awaiting IA", "warning"),
    "ia_verified": ("IA Verified", "success"),
    "completed": ("Completed", "success"),
    "closed": ("Closed", "success"),
    "returned": ("Returned", "danger"),
    "returned_by_ia": ("Returned by IA", "danger"),
    "returned_by_pl": ("Returned by PL", "danger"),
}
EVIDENCE_LABEL = {
    "none": ("Not Submitted", "danger"),
    "uploaded": ("Awaiting Evidence", "warning"),
    "returned": ("Returned", "danger"),
    "accepted": ("Submitted", "success"),
    "rejected": ("Rejected", "danger"),
}


def _row(a, partner_names, project_names):
    label, tone = STATUS_LABEL.get(
        a.status, (a.status.replace("_", " ").title(), "neutral")
    )
    ev_label, ev_tone = EVIDENCE_LABEL.get(a.evidence_status, ("—", "neutral"))
    return {
        "id": a.id,
        "school": a.school.name
        if a.school_id
        else (a.cluster.name if a.cluster_id else "—"),
        "project": project_names.get(a.project_id, "—"),
        "district": a.school.district.name
        if a.school_id and a.school.district_id
        else "—",
        "planned_date": a.planned_date,
        "purpose": a.activity_purpose_text
        or INTERVENTION_LABELS.get(a.focus_intervention, "Project support"),
        "focus": INTERVENTION_LABELS.get(a.focus_intervention, "—"),
        "partner": partner_names.get(a.assigned_partner_id, "—"),
        "participants": (a.teachers_attended or 0) + (a.leaders_attended or 0)
        or a.expected_outcome,
        "status": label,
        "status_tone": tone,
        "evidence": ev_label,
        "evidence_tone": ev_tone,
    }


def get_my_plan(principal, filters=None) -> dict:
    from apps.activities.models import Activity, ActivityScheduleCostLine

    scope = resolve_user_scope(principal)
    fy = get_operational_fy()

    projects_qs = Project.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope:
        staff_id = getattr(principal, "staff_profile_id", None)
        projects_qs = (
            projects_qs.filter(manager_staff_id=staff_id)
            if staff_id
            else projects_qs.none()
        )
    projects = list(projects_qs)
    project_ids = [p.id for p in projects]
    project_names = {p.id: p.name for p in projects}

    acts = list(
        Activity.objects.filter(
            deleted_at__isnull=True, project_id__in=project_ids
        ).select_related("school", "school__district", "cluster")
    )
    from apps.partners.models import Partner

    partner_ids = {a.assigned_partner_id for a in acts if a.assigned_partner_id}
    partner_names = {p.id: p.name for p in Partner.objects.filter(id__in=partner_ids)}

    # ── Period counts (by planned_date) ───────────────────────────────────────
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    month = today.month
    q_start = (today.month - 1) // 3 * 3 + 1

    def _in(d, lo, hi):
        return d is not None and lo <= d <= hi

    planned = [
        a for a in acts if a.status not in ["not_planned", "cancelled", "rejected"]
    ]
    week_n = sum(1 for a in planned if _in(a.planned_date, week_start, week_end))
    month_n = sum(
        1 for a in planned if a.planned_date and a.planned_date.month == month
    )
    quarter_n = sum(
        1
        for a in planned
        if a.planned_date and q_start <= a.planned_date.month <= q_start + 2
    )
    fy_n = len(planned)

    visits = [
        a for a in acts if a.activity_type in VISIT_TYPES and a.delivery_type == "staff"
    ]
    trainings = [
        a
        for a in acts
        if a.activity_type in TRAINING_TYPES and a.delivery_type == "staff"
    ]
    partner_acts = [a for a in acts if a.delivery_type == "partner"]

    delivered = [a for a in acts if a.status in DELIVERED_STATUSES]
    completion = round(len(delivered) / len(acts) * 100) if acts else 0

    kpis = [
        {
            "label": "Planned This Week",
            "value": str(week_n),
            "icon": "calendar",
            "variant": "primary",
            "helper": "activities",
        },
        {
            "label": "Planned This Month",
            "value": str(month_n),
            "icon": "calendar",
            "variant": "success",
            "helper": "activities",
        },
        {
            "label": "Planned This Quarter",
            "value": str(quarter_n),
            "icon": "calendar",
            "variant": "analytics",
            "helper": "activities",
        },
        {
            "label": "Planned This FY",
            "value": str(fy_n),
            "icon": "calendar",
            "variant": "warning",
            "helper": "activities",
        },
        {
            "label": "School Visits",
            "value": str(len(visits)),
            "icon": "school",
            "variant": "info",
            "helper": "scheduled",
        },
        {
            "label": "Partner Activities",
            "value": str(len(partner_acts)),
            "icon": "users",
            "variant": "analytics",
            "helper": "monitored",
        },
        {
            "label": "Project Trainings",
            "value": str(len(trainings)),
            "icon": "briefcase",
            "variant": "info",
            "helper": "scheduled",
        },
        {
            "label": "Completion Readiness",
            "value": f"{completion}%",
            "icon": "check",
            "variant": "success",
            "helper": "delivered",
        },
    ]

    # ── Attention items ────────────────────────────────────────────────────────
    attention = []
    resched = sum(
        1
        for a in acts
        if (a.reschedule_count or 0) > 0 and a.status not in DELIVERED_STATUSES
    )
    if resched:
        attention.append(
            {"tone": "danger", "label": f"Rescheduled: {resched} activity(ies)"}
        )
    awaiting_ev = sum(
        1
        for a in partner_acts
        if a.evidence_status in ["uploaded", "none"]
        and a.status in ["in_progress", "completion_started", "evidence_uploaded"]
    )
    if awaiting_ev:
        attention.append(
            {
                "tone": "warning",
                "label": f"Awaiting evidence: {awaiting_ev} partner activity(ies)",
            }
        )
    partner_pending = sum(1 for a in partner_acts if a.status == "assigned_to_partner")
    if partner_pending:
        attention.append(
            {
                "tone": "warning",
                "label": f"Partner pending confirmation: {partner_pending} activity(ies)",
            }
        )
    ia_pending = sum(1 for a in acts if a.status == "awaiting_ia_verification")
    if ia_pending:
        attention.append(
            {"tone": "info", "label": f"IA review pending: {ia_pending} activity(ies)"}
        )

    # ── Budget & workflow status ───────────────────────────────────────────────
    lines_by_act = set(
        ActivityScheduleCostLine.objects.filter(
            activity__project_id__in=project_ids
        ).values_list("activity_id", flat=True)
    )
    budget_created = len({a.id for a in acts if a.id in lines_by_act})
    evidence_pending = sum(
        1 for a in acts if a.evidence_status in ["uploaded", "returned"]
    )
    ia_review = sum(1 for a in acts if a.status == "awaiting_ia_verification")
    workflow = [
        {
            "label": "Budget Created",
            "value": f"{budget_created} / {len(acts)}",
            "tone": "success",
        },
        {
            "label": "Evidence Pending",
            "value": f"{evidence_pending} / {len(acts)}",
            "tone": "warning",
        },
        {
            "label": "IA Review Pending",
            "value": f"{ia_review} / {len(acts)}",
            "tone": "info",
        },
    ]

    # ── Upcoming today ─────────────────────────────────────────────────────────
    upcoming = [
        _row(a, partner_names, project_names)
        for a in acts
        if a.planned_date == today and a.status in ["scheduled", "in_progress"]
    ][:5]

    return {
        "kpis": kpis,
        "visits": [_row(a, partner_names, project_names) for a in visits][:12],
        "trainings": [_row(a, partner_names, project_names) for a in trainings][:12],
        "partner_activities": [
            _row(a, partner_names, project_names) for a in partner_acts
        ][:12],
        "attention": attention,
        "workflow": workflow,
        "upcoming": upcoming,
        "breakdown": {
            "week": week_n,
            "month": month_n,
            "quarter": quarter_n,
            "fy": fy_n,
        },
        "fy": fy,
        "has_activities": bool(acts),
        "has_projects": bool(project_ids),
    }
