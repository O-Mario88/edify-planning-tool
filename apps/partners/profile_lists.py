"""What a partner organisation's profile lists about its work (owner,
2026-10-08: "The partner profile should show a comprensive details (profile and
basic info or Bio data, List of schools they have been assigned for visits,
list of trainings they are going to facilitate").

The profile had one table of schools the organisation had already visited or
trained, and one of every activity it ever held. Neither answers the two
questions a supervisor opens the profile with: which schools has this
organisation been given to visit, and which trainings is it due to
facilitate. A school handed over and not yet dated was in neither table.

Two lists, each one row per piece of work:

* ``visit_schools`` — every school handed to the organisation for a visit and
  still its to deliver, or delivered: waiting for a date, dated, delivered.
* ``trainings`` — every training it delivers or facilitates: the in-school
  trainings handed to it, and the group trainings and cluster meetings an
  officer runs with this organisation as facilitator
  (``apps.activities.facilitation``).

Work staff took back is in neither (``PartnerAssignment.RELEASED_STATUSES``),
and neither is work that was called off.
"""

from __future__ import annotations

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
    TRAINING_TYPES,
)
from apps.core.clock import local_day

#: Where a piece of work stands, in the words the profile uses, and the tone
#: of its badge: done is green, planned is blue (owner, 2026-09-27).
WAITING = ("Waiting for a date", "warning")
_STAGES = {
    **{status: ("Completed", "success") for status in COMPLETED_WORK_STATUSES},
    **{
        status: ("In progress", "info")
        for status in ("in_progress", "completion_started")
    },
    **{
        status: ("Evidence in review", "info")
        for status in (
            "evidence_uploaded",
            "evidence_accepted",
            "salesforce_id_required",
            "submitted_to_pl",
            "submitted_to_ia",
            "awaiting_ia_verification",
        )
    },
    **{
        status: ("Returned for correction", "warning")
        for status in ("returned", "returned_by_ia", "returned_by_pl")
    },
}
SCHEDULED = ("Scheduled", "info")


def stage_of(activity) -> tuple[str, str]:
    """(label, tone) for the activity a piece of work became; ``WAITING`` when
    it has not been given a date."""
    if activity is None:
        return WAITING
    return _STAGES.get(activity.status, SCHEDULED)


def _day(activity):
    if activity is None:
        return None
    if activity.scheduled_date:
        return local_day(activity.scheduled_date)
    return activity.planned_date


def _names(person_ids) -> dict[str, str]:
    """{id: name} for ids that are a People record's or a user's
    (``apps.core.scoping.owner_ids``), in two queries."""
    from apps.accounts.models import StaffProfile, User

    ids = {i for i in person_ids if i}
    names: dict[str, str] = {}
    if not ids:
        return names
    for profile in StaffProfile.objects.filter(id__in=ids).select_related("user"):
        names[profile.id] = profile.user.name
    for user in User.objects.filter(id__in=ids - set(names)):
        names[user.id] = user.name
    return names


def _is_training(assignment) -> bool:
    """A hand-over that is a training rather than a visit: it names a course,
    or the work it is, or became, is a training."""
    if assignment.training_course_id or assignment.training_number:
        return True
    activity = assignment.scheduled_activity
    kind = (
        activity.activity_type
        if activity is not None
        else assignment.expected_activity_type
        or getattr(assignment.catalogue_item, "workflow_kind", "")
    )
    return (kind or "") in TRAINING_TYPES


def _handovers(partner):
    from apps.partners.models import PartnerAssignment

    return [
        assignment
        for assignment in PartnerAssignment.objects.filter(partner=partner)
        .exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
        .select_related(
            "school",
            "school__district",
            "cluster",
            "cluster__district",
            "catalogue_item",
            "training_course",
            "scheduled_activity",
        )
        .order_by("-created_at")
        # Called off after the partner had dated it, and not taken back.
        if assignment.scheduled_activity is None
        or assignment.scheduled_activity.status not in NOT_IN_PLAN_ACTIVITY_STATUSES
    ]


def _order(rows: list[dict]) -> list[dict]:
    """What needs a date first, then what is coming soonest, then what is
    done, most recent first: the order a supervisor reads it in."""

    def key(row):
        if row["date"] is None:
            return (0, 0)
        if row["tone"] != "success":
            return (1, row["date"].toordinal())
        return (2, -row["date"].toordinal())

    return sorted(rows, key=key)


def visit_schools(partner) -> list[dict]:
    """Every school this organisation has been handed for a visit."""
    from apps.partners.purposes import visit_purpose_label

    handovers = [a for a in _handovers(partner) if a.school_id and not _is_training(a)]
    names = _names(a.monitoring_staff_id or a.assigning_staff_id for a in handovers)
    rows = []
    for assignment in handovers:
        activity = assignment.scheduled_activity
        label, tone = stage_of(activity)
        school = assignment.school
        rows.append(
            {
                "school": school,
                "district": school.district.name if school.district_id else "",
                "visit": visit_purpose_label(assignment.purpose_of_visit, "")
                or getattr(assignment.catalogue_item, "display_name", "")
                or "School visit",
                "officer": names.get(
                    assignment.monitoring_staff_id
                    or assignment.assigning_staff_id
                    or "",
                    "",
                ),
                "assigned_on": local_day(assignment.created_at),
                "date": _day(activity) or assignment.scheduled_date,
                "visited_by": getattr(activity, "delivery_contact_name", "") or "",
                "status": label,
                "tone": tone,
                "activity_id": getattr(activity, "id", ""),
            }
        )
    return _order(rows)


def trainings(partner) -> list[dict]:
    """Every training this organisation delivers or facilitates."""
    from apps.activities.facilitation import is_meeting
    from apps.activities.models import Activity

    rows = []

    # 1. In-school trainings handed to it: its own to deliver.
    handed = [a for a in _handovers(partner) if _is_training(a)]
    # 2. An officer's group training or cluster meeting it facilitates.
    facilitated = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            facilitating_partner_id=partner.id,
            delivery_type="staff",
        )
        .exclude(status__in=NOT_IN_PLAN_ACTIVITY_STATUSES)
        .select_related(
            "school",
            "school__district",
            "cluster",
            "cluster__district",
            "training_course",
        )
    )
    names = _names(
        [a.monitoring_staff_id or a.assigning_staff_id for a in handed]
        + [a.responsible_staff_id for a in facilitated]
    )

    for assignment in handed:
        activity = assignment.scheduled_activity
        label, tone = stage_of(activity)
        place = assignment.school or assignment.cluster
        rows.append(
            {
                "training": getattr(assignment.training_course, "display_name", "")
                or getattr(assignment.catalogue_item, "display_name", "")
                or "In-school training",
                "kind": "In-school training" if assignment.school_id else "Training",
                "school_id": assignment.school_id or "",
                "place": getattr(place, "name", ""),
                "place_href": f"/schools/{assignment.school_id}"
                if assignment.school_id
                else (
                    f"/clusters/{assignment.cluster_id}"
                    if assignment.cluster_id
                    else ""
                ),
                "district": getattr(getattr(place, "district", None), "name", "") or "",
                "officer": names.get(
                    assignment.monitoring_staff_id
                    or assignment.assigning_staff_id
                    or "",
                    "",
                ),
                "date": _day(activity) or assignment.scheduled_date,
                "facilitator": getattr(activity, "delivery_contact_name", "") or "",
                "status": label,
                "tone": tone,
                "activity_id": getattr(activity, "id", ""),
            }
        )

    for activity in facilitated:
        label, tone = stage_of(activity)
        place = activity.cluster or activity.school
        rows.append(
            {
                "training": getattr(activity.training_course, "display_name", "")
                or activity.activity_name_snapshot
                or activity.get_activity_type_display(),
                "kind": "Cluster meeting"
                if is_meeting(activity.activity_type)
                else "Group training",
                "school_id": activity.school_id or "",
                "place": getattr(place, "name", ""),
                "place_href": f"/clusters/{activity.cluster_id}"
                if activity.cluster_id
                else (f"/schools/{activity.school_id}" if activity.school_id else ""),
                "district": getattr(getattr(place, "district", None), "name", "") or "",
                "officer": names.get(activity.responsible_staff_id or "", ""),
                "date": _day(activity),
                "facilitator": activity.delivery_contact_name or "",
                "status": label,
                "tone": tone,
                "activity_id": activity.id,
            }
        )
    return _order(rows)
