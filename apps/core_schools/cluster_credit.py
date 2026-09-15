"""Cluster sessions a Core School took part in count as its trainings.

Owner rule (2026-09-15): a cluster training or cluster meeting counts toward a
Core School's trainings when the school was ticked on the session's invitation
list at scheduling AND is on the register of who attended at completion.

The Core package is counted from its slots (`CorePackageSchedulingService` and
`resync_plan_completion`), so the credit is a slot: the session is linked to
the school's next open training slot, and the Activity → slot mirror carries
the session's status across from then on, exactly as it does for a training
scheduled from the Core Schools page. Every count that reads slots — the
package progress, the 4-training cap, the planning queue — agrees without a
second definition of "trained".

One cluster session may fill a slot at many schools; each school's slot links
the same activity id.
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


def credited_school_ids(activity) -> set[str]:
    """School pks whose attendance at this session counts as Core training.

    Attended and invited. A session scheduled before invitations were recorded
    by name has no invitation row at all; the whole cluster was invited to it
    (the planner's count meant every member), so attendance alone credits.
    """
    from apps.activities.models import ClusterActivityAttendance

    rows = list(
        ClusterActivityAttendance.objects.filter(activity=activity).values_list(
            "school_id", "invited", "attended", "is_guest"
        )
    )
    attended = {school_id for school_id, _i, a, _g in rows if a}
    attended |= set(activity.attended_school_ids or [])
    if not any(invited for _s, invited, _a, _g in rows):
        guests = {school_id for school_id, _i, _a, guest in rows if guest}
        return attended - guests
    invited = {school_id for school_id, i, _a, guest in rows if i and not guest}
    return attended & invited


@transaction.atomic
def credit_cluster_session(activity) -> None:
    """Link or release Core training slots to match this session's register."""
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
    )
    from apps.core_schools.models import CoreActivitySlot, CorePlan
    from apps.core_schools.services import resync_plan_completion
    from apps.schools.models import School

    if not activity.cluster_id or activity.activity_type not in CLUSTER_SESSION_TYPES:
        return

    linked = list(
        CoreActivitySlot.objects.filter(
            activity_id=activity.id, activity_type="training"
        ).select_related("core_plan")
    )
    live = activity.deleted_at is None and activity.status in CREDITED_STATUSES
    credited_codes = (
        set(
            School.objects.filter(
                id__in=credited_school_ids(activity),
                school_type="core",
                deleted_at__isnull=True,
            ).values_list("school_id", flat=True)
        )
        if live
        else set()
    )

    touched_plans = {}
    for slot in linked:
        if slot.school_id in credited_codes and str(slot.core_plan.fy) == str(
            activity.fy
        ):
            continue
        # No longer on the register (or the session was cancelled): the slot
        # goes back to the package, open to be scheduled.
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

    already = {slot.school_id for slot in linked if slot.activity_id}
    wanted = credited_codes - already
    if wanted:
        plans = CorePlan.objects.filter(school_id__in=wanted, fy=str(activity.fy))
        for plan in plans:
            open_slot = next(
                (
                    slot
                    for slot in plan.slots.select_for_update()
                    .filter(activity_type="training")
                    .order_by("sequence_number")
                    if not CorePackageSchedulingService.is_allocated(slot)
                    and (slot.status or "").strip().lower() != "assigned"
                ),
                None,
            )
            if open_slot is None:
                # All four trainings are already scheduled or done; the
                # session is still on the school's history, it just has no
                # package slot left to fill.
                continue
            open_slot.activity_id = activity.id
            open_slot.status = activity.status
            open_slot.owner = (
                "partner" if activity.delivery_type == "partner" else "staff"
            )
            open_slot.assigned_staff_id = activity.responsible_staff_id
            open_slot.assigned_partner_id = activity.assigned_partner_id
            if activity.scheduled_date:
                open_slot.scheduled_for = activity.scheduled_date.date()
            open_slot.scheduled_month = (
                str(activity.planned_month) if activity.planned_month else None
            )
            open_slot.scheduled_week = activity.planned_week
            open_slot.save()
            touched_plans[plan.id] = plan

    for plan in touched_plans.values():
        resync_plan_completion(plan)


__all__ = ["CREDITED_STATUSES", "credit_cluster_session", "credited_school_ids"]
