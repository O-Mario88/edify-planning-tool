"""Put right what earlier cancellations left behind.

Owner, 2026-10-08: "cancelled activities should undo the scheduling done" and
"the cancelled activities should not remain counting ... the v1 or v2 v3 or
v4 should be reset back to the actual scheduled activities."

A cancellation now gives its Core package slot back and renumbers what is
left (`core_schools.package_credit.give_back_slots`), and puts a Partner's
hand-over back to waiting for its date
(`partners.services.undo_assignment_scheduling`). Two kinds of row written
before that are still as the old code left them:

* a **package slot pointing at work that was called off** — the school reads
  "V1 not planned, V2 planned" for one visit;
* a **hand-over still "scheduled by the partner" on a cancelled activity** —
  the Partner cannot date the school again and the school is on no list.

`find` reads which rows those are (with the models it is given, so a
migration can ask with its own); `repair` puts them right with the same code
a cancellation runs today. The `repair_cancelled_work` command is the dry run
and the manual door; activities migration 0066 applies it on deploy.

A hand-over is put back to waiting only where its cancelled activity was
dated in the running year or later. One from a year that has closed is closed
with it: a Partner should not find last year's school back on its list.
"""

from __future__ import annotations

from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES

#: Activity states in which work holds no slot: called off, or never planned.
CALLED_OFF = NOT_IN_PLAN_ACTIVITY_STATUSES


def find(Slot, Activity, Handover) -> dict:
    """``{"slots": [...], "handovers": [...]}``: the ids of the package slots
    that point at called-off work, and of the hand-overs left scheduled on a
    cancelled activity."""
    called_off = Activity.objects.filter(status__in=CALLED_OFF).values("id")
    slots = list(
        Slot.objects.filter(activity_id__in=called_off)
        .order_by("school_id", "activity_type", "sequence_number")
        .values_list("id", flat=True)
    )
    # The hand-over states that say the work is on a day: a constant, read
    # from the live class for its values alone.
    from apps.partners.models import PartnerAssignment

    handovers = list(
        Handover.objects.filter(
            status__in=PartnerAssignment.SCHEDULED_STATUSES,
            scheduled_activity__status="cancelled",
        )
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return {"slots": slots, "handovers": handovers}


def repair(*, write: bool, out=print) -> dict:
    """Give back the slots and settle the hand-overs `find` names. With
    ``write`` false nothing changes and every row is still listed. Each row
    is put right in a transaction of its own: one that cannot be is reported
    and left, and the rest still go."""
    from django.db import transaction

    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.core_schools.cluster_credit import _release
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.package_credit import close_gaps
    from apps.core_schools.services import resync_plan_completion
    from apps.partners.dating_policy import partner_has_dated
    from apps.partners.models import PartnerAssignment
    from apps.partners.services import undo_assignment_scheduling
    from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal

    found = find(CoreActivitySlot, Activity, PartnerAssignment)
    report = {"slots": 0, "renumbered": 0, "reopened": 0, "closed": 0, "skipped": 0}
    running_year = str(get_operational_fy())

    packages = {}
    for slot in CoreActivitySlot.objects.filter(id__in=found["slots"]).select_related(
        "core_plan"
    ):
        label = f"{slot.activity_type[0].upper()}{slot.sequence_number}"
        out(
            f"  slot {slot.school_id} FY{slot.core_plan.fy} {label}: held by "
            f"called-off activity {slot.activity_id} - given back"
        )
        packages[(slot.core_plan_id, slot.activity_type)] = slot.core_plan
        report["slots"] += 1
        if write:
            _release(slot)
    for (_plan_id, kind), plan in packages.items():
        if not write:
            continue
        try:
            with transaction.atomic():
                moves = close_gaps(plan, kind)
                resync_plan_completion(plan)
        except Exception as exc:  # noqa: BLE001 - report it, repair the rest
            out(f"  ! could not renumber {plan.school_id} {kind}: {exc}")
            report["skipped"] += 1
            continue
        letter = kind[0].upper()
        for was, now in sorted(moves.items()):
            out(f"  {plan.school_id} FY{plan.fy}: {letter}{was} is now {letter}{now}")
            report["renumbered"] += 1

    withdrawn = set(
        PartnerAssignmentWithdrawal.objects.filter(
            assignment_id__in=found["handovers"]
        ).values_list("assignment_id", flat=True)
    )
    for handover in PartnerAssignment.objects.filter(
        id__in=found["handovers"]
    ).select_related("scheduled_activity", "school", "partner"):
        activity = handover.scheduled_activity
        where = getattr(handover.school, "name", None) or handover.school_id or "—"
        who = getattr(handover.partner, "name", "") or handover.partner_id
        if handover.id in withdrawn:
            # A withdrawal is deciding this one; it is left to that record.
            out(
                f"  hand-over {handover.id} ({where}, {who}): under a withdrawal - left"
            )
            report["skipped"] += 1
            continue
        reopen = partner_has_dated(activity) and str(activity.fy or "") >= running_year
        outcome = "reopened" if reopen else "closed"
        if write:
            try:
                with transaction.atomic():
                    outcome = (
                        undo_assignment_scheduling(
                            activity,
                            partner_dated=reopen,
                            reason=(
                                "Its activity had been cancelled"
                                + (
                                    f": {activity.last_reason}"
                                    if activity.last_reason
                                    else "."
                                )
                            ),
                        )
                        or outcome
                    )
            except Exception as exc:  # noqa: BLE001 - report it, repair the rest
                out(f"  ! could not settle hand-over {handover.id}: {exc}")
                report["skipped"] += 1
                continue
        out(
            f"  hand-over {handover.id} ({where}, {who}): scheduled on cancelled "
            f"activity {activity.id} - "
            + (
                "waiting for the partner's date again"
                if outcome == "reopened"
                else "closed with it"
            )
        )
        report[outcome] += 1
    return report
