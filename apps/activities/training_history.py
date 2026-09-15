"""The trainings a school has done — what a Training Follow Up follows up.

A school is trained two ways: in its own classroom (an in-school or Core
training carrying the school FK) or at a cluster session it attended (no
school FK, an attendance register instead). A follow-up visit may follow up
either, so the drawers' dropdown and the create service's validation both ask
this module rather than each keeping its own list of source types.
"""

from __future__ import annotations

from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
from apps.core.activity_types import ActivityType
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy

#: The work is done: delivered and at or past its completion record.
FOLLOW_UP_SOURCE_STATUSES = (
    "completed",
    "ia_verified",
    "accountant_confirmed",
    "closed",
)

#: Cluster sessions a school can attend. Meetings are followed up too.
CLUSTER_SESSION_TYPES = (
    ActivityType.CLUSTER_TRAINING,
    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
    ActivityType.CLUSTER_MEETING,
    ActivityType.CLUSTER_MEETING_SSA_REVIEW,
)

FOLLOW_UP_SOURCE_TYPES = frozenset({*SCHOOL_TRAINING_TYPES, *CLUSTER_SESSION_TYPES})


def follow_up_source_problem(source, school, fy) -> str | None:
    """Why ``source`` cannot be followed up at ``school`` in ``fy``, or None."""
    if source.activity_type not in FOLLOW_UP_SOURCE_TYPES:
        return (
            "Training Follow Up must reference a completed training or cluster "
            "meeting this School took part in."
        )
    if source.status not in FOLLOW_UP_SOURCE_STATUSES:
        return "Follow-up requires a completed source Training or support Activity."
    if str(source.fy) != str(fy):
        return (
            "Training Follow Up must reference a session from the same Fiscal "
            "Year as the scheduled visit."
        )
    if source.activity_type in CLUSTER_SESSION_TYPES:
        # A cluster invitation is not attendance: only the completion register
        # credits a school with having been in the room.
        if school.id not in (source.attended_school_ids or []):
            return (
                "This School is not recorded as attending the selected Cluster "
                "Training or Cluster Meeting."
            )
    elif source.school_id != school.id:
        return "The selected training was delivered at a different School."
    return None


def school_trainings_done(school, *, fy=None):
    """Completed trainings and cluster sessions this school did in ``fy``."""
    from django.db.models import Q

    from apps.activities.models import Activity

    fy = fy or get_operational_fy()
    return (
        Activity.objects.filter(
            deleted_at__isnull=True,
            fy=fy,
            status__in=FOLLOW_UP_SOURCE_STATUSES,
        )
        .filter(
            Q(school=school, activity_type__in=SCHOOL_TRAINING_TYPES)
            | Q(
                activity_type__in=CLUSTER_SESSION_TYPES,
                attended_school_ids__contains=[school.id],
            )
        )
        .select_related("catalogue_item", "cluster")
        .order_by("-planned_date", "-created_at")
    )


def follow_up_options(school, *, fy=None) -> list[dict]:
    """The dropdown a Training Follow Up chooses from, newest first."""
    labels = dict(SsaIntervention.choices)
    options = []
    for activity in school_trainings_done(school, fy=fy):
        name = (
            activity.activity_name_snapshot
            or getattr(activity.catalogue_item, "display_name", "")
            or activity.get_activity_type_display()
        )
        when = (
            activity.planned_date.strftime("%d %b %Y")
            if activity.planned_date
            else "Date not recorded"
        )
        where = (
            getattr(activity.cluster, "name", "") or "Cluster session"
            if activity.activity_type in CLUSTER_SESSION_TYPES
            else "At the school"
        )
        intervention = activity.focus_intervention or activity.purpose_intervention
        options.append(
            {
                "id": activity.id,
                "label": f"{name} · {when} · {where}",
                "intervention": intervention or "",
                "interventionLabel": (
                    labels.get(intervention, intervention)
                    if intervention
                    else "Not SSA-scored"
                ),
                "salesforceId": activity.salesforce_activity_id or "",
            }
        )
    return options


__all__ = [
    "CLUSTER_SESSION_TYPES",
    "FOLLOW_UP_SOURCE_STATUSES",
    "FOLLOW_UP_SOURCE_TYPES",
    "follow_up_options",
    "follow_up_source_problem",
    "school_trainings_done",
]
