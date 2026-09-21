"""Past-due activity queries and formatting for 'What needs you now' on the Dashboard."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.notifications.models import Notification

TERMINAL_OR_COMPLETED_STATUSES = frozenset(
    {
        *COMPLETED_WORK_STATUSES,
        "completed",
        "closed",
        "cancelled",
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "accountant_confirmed",
    }
)

VISIT_TYPES = frozenset(
    {
        "school_visit",
        "follow_up_visit",
        "coaching_visit",
        "in_school_support",
        "donor_visit",
        "story_gathering_visit",
        "school_invitation",
        "social_visit",
        "training_follow_up_visit",
        "in_school_coaching_visit",
        "core_visit",
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "core_assessment_visit",
    }
)

TRAINING_TYPES = frozenset(
    {
        "cluster_training",
        "core_training",
        "training",
        "in_school_training",
        "school_improvement_training",
        "cluster_training_ssa_collection",
    }
)

MEETING_TYPES = frozenset(
    {
        "cluster_meeting",
        "cluster_meeting_ssa_review",
    }
)


def _user_owner_ids(user) -> list[str]:
    """Collect both User CUID and StaffProfile CUID for the given user."""
    ids = set()
    if getattr(user, "id", None):
        ids.add(str(user.id))
    sp_id = getattr(user, "staff_profile_id", None)
    if sp_id:
        ids.add(str(sp_id))
    return [i for i in ids if i]


def get_past_due_dashboard_context(user) -> dict[str, Any]:
    """Build the 'What needs you now' dataset for the dashboard.

    For CCEO:
      Returns their own past-due plans.
    For Program Lead:
      Returns their own past-due plans and those of their line-managed team.
    """
    today = timezone.localdate()
    role = getattr(user, "active_role", "")
    is_pl = role == "Program Lead"

    own_ids = _user_owner_ids(user)

    team_member_ids: list[str] = []
    team_members_by_id: dict[str, Any] = {}
    if is_pl:
        from apps.hr.team_roster import team_members

        members = team_members(user)
        for m in members:
            m_name = (m.user.name if m.user_id and m.user else "") or "CCEO"
            team_member_ids.append(m.id)
            team_members_by_id[m.id] = {"id": m.id, "name": m_name, "profile": m}
            if m.user_id:
                team_member_ids.append(m.user_id)
                team_members_by_id[m.user_id] = {
                    "id": m.id,
                    "name": m_name,
                    "profile": m,
                }

    # Query all active, past-due activities for this user (or team if PL)
    all_scoped_ids = list(set(own_ids + team_member_ids))
    if not all_scoped_ids:
        return _empty_past_due_context(is_pl)

    qs = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(status__in=TERMINAL_OR_COMPLETED_STATUSES)
        .filter(
            Q(planned_date__lt=today)
            | Q(planned_date__isnull=True, scheduled_date__date__lt=today)
        )
        .filter(
            Q(responsible_staff_id__in=all_scoped_ids)
            | Q(monitored_by_staff_id__in=all_scoped_ids, delivery_type="partner")
        )
        .select_related(
            "school",
            "school__district",
            "school__sub_county",
            "cluster",
            "cluster__district",
        )
        .prefetch_related("schedule_cost_lines")
        .order_by("planned_date", "scheduled_date")
    )

    activities = list(qs)
    if not activities:
        return _empty_past_due_context(is_pl)

    # Names for the people on these rows only, in both id spaces, from one
    # profile query; a bare User id without a profile costs a second query
    # only when one appears. Reading every user and every profile on each
    # dashboard open was two whole-table queries for a handful of names.
    people = {a.responsible_staff_id for a in activities} | {
        a.monitored_by_staff_id for a in activities
    }
    people.discard(None)
    people.discard("")
    users_map: dict[str, str] = {}
    for sp in StaffProfile.objects.select_related("user").filter(
        Q(id__in=people) | Q(user_id__in=people)
    ):
        name = sp.user.name if sp.user_id and sp.user else ""
        if name:
            users_map[sp.id] = name
            if sp.user_id:
                users_map[sp.user_id] = name
    unresolved = [pid for pid in people if pid not in users_map]
    if unresolved:
        users_map.update(
            User.objects.filter(id__in=unresolved).values_list("id", "name")
        )

    # Query which activities already have an active reminder notification
    active_reminder_act_ids = set(
        Notification.objects.filter(
            context_type="activity",
            context_id__in=[a.id for a in activities],
            source_event_type="pl_activity_overdue_reminder",
            resolved_at__isnull=True,
        ).values_list("context_id", flat=True)
    )

    from apps.budget.costing_service import planned_minimum_amounts

    minimum_amounts = planned_minimum_amounts(activities)

    past_due_school_visits: list[dict[str, Any]] = []
    past_due_cluster_trainings: list[dict[str, Any]] = []
    past_due_cluster_meetings: list[dict[str, Any]] = []

    own_count = 0
    team_count = 0

    for a in activities:
        is_own = a.responsible_staff_id in own_ids or (
            not a.responsible_staff_id and a.monitored_by_staff_id in own_ids
        )
        if is_own:
            own_count += 1
        else:
            team_count += 1

        owner_name = users_map.get(a.responsible_staff_id) or users_map.get(
            a.monitored_by_staff_id, "Staff"
        )
        first_name = owner_name.split()[0] if owner_name else "Team Member"

        planned_dt = a.planned_date or (
            a.scheduled_date.date() if a.scheduled_date else None
        )
        days_overdue = (today - planned_dt).days if planned_dt else 0

        cluster_district_name = ""
        if a.cluster and getattr(a.cluster, "district", None):
            cluster_district_name = getattr(a.cluster.district, "name", "") or ""
        elif a.school and getattr(a.school, "district", None):
            cluster_district_name = getattr(a.school.district, "name", "") or ""

        # Status text and tone
        if a.status in ("returned", "returned_by_pl", "returned_by_ia"):
            status_lbl = "Returned"
            status_tone = "danger"
            status_class = "bg-rose-50 text-rose-700 border-rose-200"
        elif a.status == "in_progress":
            status_lbl = "In Progress"
            status_tone = "warning"
            status_class = "bg-amber-50 text-amber-700 border-amber-200"
        else:
            status_lbl = "Past Due"
            status_tone = "danger"
            status_class = "bg-rose-50 text-rose-700 border-rose-200"

        row = {
            "id": a.id,
            "activity_type": a.activity_type,
            "activity_type_label": a.get_activity_type_display(),
            "status": a.status,
            "status_label": status_lbl,
            "status_tone": status_tone,
            "status_class": status_class,
            "planned_date": planned_dt,
            "days_overdue": days_overdue,
            "is_own": is_own,
            "owner": owner_name,
            "owner_first_name": first_name,
            "execution_role": "Staff" if a.delivery_type == "staff" else "Partner",
            "school_id": a.school.school_id if a.school else "",
            "school_name": (
                a.school.name if a.school else (a.cluster.name if a.cluster else "—")
            ),
            "school_district": (
                a.school.district.name
                if a.school and a.school.district
                else cluster_district_name
            ),
            "cluster_id": a.cluster.id if a.cluster else "",
            "cluster_name": (
                a.cluster.name if a.cluster else (a.school.name if a.school else "—")
            ),
            "cluster_district": cluster_district_name or "—",
            "place_url": (
                f"/clusters/{a.cluster.id}"
                if a.cluster
                else (f"/schools/{a.school.id}" if a.school else "")
            ),
            "purpose": (a.activity_purpose_text or a.get_activity_type_display()),
            "focus_intervention": (
                a.get_focus_intervention_display() if a.focus_intervention else "—"
            ),
            "budget_total": minimum_amounts.get(a.id, 0),
            "budget_status": "Budget Planned"
            if a.schedule_cost_lines.exists()
            else "No Budget",
            "budget_status_color": "blue"
            if a.schedule_cost_lines.exists()
            else "slate",
            "verification_status": "Pending",
            "verification_color": "purple",
            "expected_participants": a.expected_participants or "—",
            "delivery_type": a.delivery_type,
            "reminder_sent": a.id in active_reminder_act_ids,
            "complete_url": f"/my-plan/{a.id}/complete-drawer",
            "reschedule_url": f"/my-plan/{a.id}/reschedule-drawer",
            "cancel_url": f"/my-plan/{a.id}/cancel-drawer",
            "details_url": f"/my-plan/{a.id}",
            "is_completed": False,
        }

        if a.activity_type in VISIT_TYPES:
            past_due_school_visits.append(row)
        elif a.activity_type in TRAINING_TYPES:
            past_due_cluster_trainings.append(row)
        elif a.activity_type in MEETING_TYPES:
            past_due_cluster_meetings.append(row)
        else:
            # Fallback to visits table if unmatched
            past_due_school_visits.append(row)

    total_count = len(activities)

    return {
        "past_due_total_count": total_count,
        "pl_own_past_due_count": own_count,
        "pl_team_past_due_count": team_count,
        "past_due_school_visits": past_due_school_visits,
        "past_due_cluster_trainings": past_due_cluster_trainings,
        "past_due_cluster_meetings": past_due_cluster_meetings,
        "past_due_visits_count": len(past_due_school_visits),
        "past_due_trainings_count": len(past_due_cluster_trainings),
        "past_due_meetings_count": len(past_due_cluster_meetings),
        "is_pl": is_pl,
    }


def _empty_past_due_context(is_pl: bool) -> dict[str, Any]:
    return {
        "past_due_total_count": 0,
        "pl_own_past_due_count": 0,
        "pl_team_past_due_count": 0,
        "past_due_school_visits": [],
        "past_due_cluster_trainings": [],
        "past_due_cluster_meetings": [],
        "past_due_visits_count": 0,
        "past_due_trainings_count": 0,
        "past_due_meetings_count": 0,
        "is_pl": is_pl,
    }
