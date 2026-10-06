"""Group trainings planned through a cluster count in the Core package.

Owner, 2026-10-02: the package's trainings "should include both in-school
training and group trainings planned through clusters. So if a core school is
part of a group training, it should be counted in the core package."

A cluster TRAINING therefore fills a training slot at every Core school it
counts for (``credited_school_ids``): the invited schools from the day it is
booked (owner, 2026-09-21: "It should move to core school training planned
table"), narrowed to the invited schools that came once its register is
confirmed. The slot is in the package of the year the session is dated in,
made if this is the first work planned into that year
(``services.ensure_core_plan``).

It is on the half of whoever delivers it — staff's two, or the Partner's two
when a Partner delivers the session (a Partner who only facilitates a staff
session does not make it the Partner's) — and takes a slot only while that
half has room (``package_split``). Until 2026-10-02 a session took the next
open slot whatever the split, and a cluster MEETING took one too, so two
group trainings and two meetings read "4/4 trainings" with the Partner's half
never assigned: what the owner called inflated. Past its half's two, a group
training is still the school's training, on its history, and fills no slot;
a group session is never refused over one school.

A cluster meeting is not a training. It takes no slot, and
``credit_cluster_session`` gives back any slot one holds from before.

The package is counted from its slots (``CorePackageSchedulingService`` and
``resync_plan_completion``), so the credit is a slot: the Activity → slot
mirror carries the session's status across from then on, exactly as it does
for a training scheduled from the Core Schools page. One session may fill a
slot at many schools; each school's slot links the same activity id.
"""

from __future__ import annotations

from django.db import transaction

from apps.activities.training_history import CLUSTER_SESSION_TYPES
from apps.core.clock import local_day
from apps.core_schools import package_year

#: The cluster sessions that are trainings: the ones a package counts.
PACKAGE_SESSION_TYPES = package_year.CLUSTER_TRAINING_TYPES

# One definition with the deploy repair (``package_year.refile``).
CREDITED_STATUSES = package_year.SESSION_CREDITED_STATUSES
PLANNED_STATUSES = package_year.SESSION_PLANNED_STATUSES
LIVE_STATUSES = package_year.SESSION_LIVE_STATUSES


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
    return package_year.session_school_ids(rows, activity)


def counts_in_package(activity) -> bool:
    """Whether this session is one a Core package counts: a live group
    training, not a meeting, not the work of a project no SSA intervention
    measures, and not a universal training, which every school may attend on
    top of its package's four (owner, 2026-10-06)."""
    from apps.core_schools.package_credit import outside_package
    from apps.planning.training_entitlement import names_universal_course

    return (
        bool(activity.cluster_id)
        and activity.activity_type in PACKAGE_SESSION_TYPES
        and activity.deleted_at is None
        and activity.status in LIVE_STATUSES
        and bool(activity.fy)
        and not outside_package(activity.project_id)
        and not names_universal_course(activity)
    )


def _release(slot) -> None:
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


@transaction.atomic
def credit_cluster_session(activity) -> None:
    """Link or release Core training slots to match this session.

    Runs on every save of a cluster session (``Activity.save``) and when its
    list or register changes (``cluster_attendance``).
    """
    from apps.core.fy import get_operational_fy
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
        core_slot_status,
    )
    from apps.core_schools.models import CoreActivitySlot, CorePlan
    from apps.core_schools.package_split import TRAINING, package_splits
    from apps.core_schools.services import (
        CORE_PLAN_CLOSED_STATUSES,
        ensure_core_plan,
        resync_plan_completion,
    )
    from apps.schools.models import School

    if not activity.cluster_id or activity.activity_type not in CLUSTER_SESSION_TYPES:
        return

    linked = list(
        CoreActivitySlot.objects.filter(
            activity_id=activity.id, activity_type="training"
        ).select_related("core_plan")
    )
    fy = str(activity.fy or "")
    side = package_year.side_of(activity)
    schools = (
        {
            school.school_id: school
            for school in School.objects.filter(
                id__in=credited_school_ids(activity),
                school_type="core",
                deleted_at__isnull=True,
            )
        }
        if counts_in_package(activity)
        else {}
    )

    touched_plans = {}
    holding: set[str] = set()
    for slot in linked:
        if (
            slot.school_id in schools
            and str(slot.core_plan.fy) == fy
            and slot.school_id not in holding
        ):
            holding.add(slot.school_id)
            if slot.owner != side:
                # The half follows whoever delivers the session now.
                slot.owner = side
                slot.assigned_staff_id = activity.responsible_staff_id
                slot.assigned_partner_id = activity.assigned_partner_id
                slot.save()
            continue
        # Off the list, cancelled, a meeting, or another year's package: the
        # slot goes back to its package, open to be scheduled.
        _release(slot)
        touched_plans[slot.core_plan_id] = slot.core_plan

    wanted = [school for code, school in schools.items() if code not in holding]
    if wanted:
        # The package of the year the session is dated in. A past year's is
        # only ever the one it had.
        plans = {}
        if fy >= str(get_operational_fy()):
            for school in wanted:
                plan = ensure_core_plan(school, fy)
                if plan is not None:
                    plans[school.id] = plan
        else:
            by_code = {
                plan.school_id: plan
                for plan in CorePlan.objects.filter(
                    school_id__in=[school.school_id for school in wanted], fy=fy
                ).exclude(status__in=CORE_PLAN_CLOSED_STATUSES)
            }
            plans = {
                school.id: by_code[school.school_id]
                for school in wanted
                if school.school_id in by_code
            }
        # Locked before the halves are read, as every door that books package
        # work locks the package it counts against (`_locked_core_plan`).
        list(
            CorePlan.objects.select_for_update().filter(
                pk__in=[plan.pk for plan in plans.values()]
            )
        )
        splits = package_splits(
            [school for school in wanted if school.id in plans],
            fy,
            exclude_activity_id=activity.id,
        )
        for school in wanted:
            plan = plans.get(school.id)
            if plan is None or not splits[school.id].is_open(TRAINING, side):
                # No package, or this half already has its two: the session
                # is still on the school's history, in no slot.
                continue
            slots = list(
                plan.slots.select_for_update()
                .filter(activity_type="training")
                .order_by("sequence_number")
            )
            # `holding` was read before this lock. Every save of the session
            # runs this pass, so two saves at once both found the school
            # unlinked; the second waited here for the first to link a slot,
            # then took the next open one too: one session, two trainings.
            if any(slot.activity_id == activity.id for slot in slots):
                continue
            open_slot = next(
                (
                    slot
                    for slot in slots
                    if not CorePackageSchedulingService.is_allocated(slot)
                    and (slot.status or "").strip().lower() != "assigned"
                ),
                None,
            )
            if open_slot is None:
                continue
            open_slot.activity_id = activity.id
            open_slot.status = core_slot_status(activity.status)
            open_slot.owner = side
            open_slot.assigned_staff_id = activity.responsible_staff_id
            open_slot.assigned_partner_id = activity.assigned_partner_id
            # The day the package shows for this training. `scheduled_date`
            # is the instant the drawer wrote; `planned_date` is the calendar
            # day every plan surface selects on, and a session created through
            # a path that set only the latter must still date its slot —
            # otherwise the Core School Trainings Planned table lists it with
            # no day at all.
            when = (
                local_day(activity.scheduled_date)
                if activity.scheduled_date
                else activity.planned_date
            )
            if when:
                open_slot.scheduled_for = when
            open_slot.scheduled_month = (
                str(activity.planned_month) if activity.planned_month else None
            )
            open_slot.scheduled_week = activity.planned_week
            open_slot.save()
            touched_plans[plan.id] = plan

    for plan in touched_plans.values():
        resync_plan_completion(plan)


__all__ = [
    "CREDITED_STATUSES",
    "LIVE_STATUSES",
    "PACKAGE_SESSION_TYPES",
    "PLANNED_STATUSES",
    "counts_in_package",
    "credit_cluster_session",
    "credited_school_ids",
]
