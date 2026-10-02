"""Cluster sessions and the Core package: kept apart.

Owner, 2026-10-02: a cluster training or meeting is "separate" from a Core
school's package — "Outside the package". The package's four trainings are
in-school trainings, two by staff and two assigned to a Partner; a cluster
session fills no T1..T4 and is on neither side of the split. It is still the
school's training on every page that reads training coverage, and it is shown
and counted on its own.

From 2026-09-21 until then a session took the next open training slot at
every Core school it invited ("should be counted as part of the 4
trainings"). Nothing limited how many, so two group trainings and two
meetings read "4/4 trainings" with the Partner's half never assigned — what
the owner called inflated.

``credit_cluster_session`` still runs on every save of a session
(``Activity.save``). It now only gives back any slot the session holds from
before, so a package is corrected the next time its session is touched; the
deploy repair (``package_year.refile``) does the same for all of them at
once.

``credited_school_ids`` is unchanged and is still what says which schools a
session counts for: those invited while it is booked, those invited and
present once its register is confirmed.
"""

from __future__ import annotations

from django.db import transaction

from apps.activities.training_history import CLUSTER_SESSION_TYPES

#: The register has been confirmed and the session has not been abandoned.
#: `completion_started` is deliberately absent: attendance recorded while the
#: session is still being completed is a draft, and a slot left in a status
#: the scheduler reads as open could be scheduled over.
CREDITED_STATUSES = frozenset(
    {
        "submitted_to_pl",
        "awaiting_ia_verification",
        "returned",
        "returned_by_pl",
        "completed",
        "ia_verified",
        "accountant_confirmed",
        "closed",
    }
)

#: A session that is booked but whose register has not been confirmed. The
#: invitation alone takes the slot here, so the package reads "planned" from
#: the day the session is scheduled (owner, 2026-09-21) — the same reading a
#: training booked from the Core Schools page gives.
PLANNED_STATUSES = frozenset(
    {
        "planned",
        "scheduled",
        "rescheduled",
        "assigned_to_partner",
        "partner_scheduled",
        "in_progress",
        "completion_started",
        "evidence_uploaded",
        "evidence_accepted",
        "salesforce_id_required",
        "returned_by_ia",
    }
)

#: Every status in which this session holds a slot at all. Outside it — a
#: cancelled, rejected, deferred or unplanned session — the slots go back.
LIVE_STATUSES = CREDITED_STATUSES | PLANNED_STATUSES


def credited_school_ids(activity) -> set[str]:
    """School pks whose place at this session counts as Core training.

    Two readings of the same list, because a session means different things
    before and after it happens:

    * **Booked, not yet registered** — the invitation is the commitment, so
      every invited member school takes a slot. That is what puts the school
      on the Core School Trainings Planned table.
    * **Register confirmed** — attended *and* invited. A school that was
      invited and did not come has its slot released by the same pass, so the
      package never counts a training the school did not take.

    A session scheduled before invitations were recorded by name has no
    invitation row at all; the whole cluster was invited to it (the planner's
    count meant every member), so attendance alone credits.
    """
    from apps.activities.models import ClusterActivityAttendance

    rows = list(
        ClusterActivityAttendance.objects.filter(activity=activity).values_list(
            "school_id", "invited", "attended", "is_guest"
        )
    )
    invited = {school_id for school_id, i, _a, guest in rows if i and not guest}
    if activity.status in PLANNED_STATUSES:
        return invited
    attended = {school_id for school_id, _i, a, _g in rows if a}
    attended |= set(activity.attended_school_ids or [])
    if not invited:
        guests = {school_id for school_id, _i, _a, guest in rows if guest}
        return attended - guests
    return attended & invited


@transaction.atomic
def credit_cluster_session(activity) -> None:
    """Give back every Core training slot this session holds.

    A cluster session is outside the Core package (owner, 2026-10-02), so it
    links no slot. The name is kept for its caller, ``Activity.save``.
    """
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.services import resync_plan_completion

    if not activity.cluster_id or activity.activity_type not in CLUSTER_SESSION_TYPES:
        return

    touched_plans = {}
    for slot in CoreActivitySlot.objects.filter(
        activity_id=activity.id, activity_type="training"
    ).select_related("core_plan"):
        slot.status = "Planned"
        slot.activity_id = None
        slot.owner = "unassigned"
        slot.assigned_staff_id = None
        slot.assigned_partner_id = None
        slot.scheduled_for = None
        slot.scheduled_month = None
        slot.scheduled_week = None
        slot.salesforce_id = None
        slot.evidence_uri = None
        slot.save()
        touched_plans[slot.core_plan_id] = slot.core_plan
    for plan in touched_plans.values():
        resync_plan_completion(plan)


__all__ = [
    "CREDITED_STATUSES",
    "LIVE_STATUSES",
    "PLANNED_STATUSES",
    "credit_cluster_session",
    "credited_school_ids",
]
