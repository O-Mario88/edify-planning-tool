"""Work that holds its Salesforce ID but was never handed in (owner,
2026-10-15).

"as long as the activity is completed and entered in salesforce, completed
using salesforce ID it is counted and marked as completed from my Plan and
everywhere they appear ... it is the PL who approves for CCEO and theirs are
approved automatically."

Two doors saved a staff member's Salesforce ID without handing the work in:
the Salesforce ID drawer, and the upload drawer before uploads were switched
off (2026-10-13). Such work — often a visit done ahead of its planned day,
still "scheduled" — was in no count and on no Programme Lead's list. And a
lead's own work handed in before 2026-10-15 waits on the lead, who now never
has to approve it.

This hands it in, as Submit would: a CCEO's goes to their Programme Lead
(``submitted_to_pl``, where the 17:00 reminder tells the lead); a lead's own
is approved. Only a CCEO's or a lead's staff work: partner work is completed by
Impact Assessment with its ID, and other staff's work is IA's (owner, same
day). Returned work is not touched: the lead sent it back to be corrected.

Run by the deploy (a pl_review data migration) and by
``manage.py hand_in_entered_work`` for a dry run.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

#: Not handed in yet: planned, begun, or the legacy staged "completed".
NOT_HANDED_IN_STATUSES = (
    "scheduled",
    "rescheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "completed",
)


def _candidates(ids=None):
    from apps.activities.models import Activity
    from apps.pl_review.services import LEAD_REVIEWABLE_STATUSES, lead_verified_q

    holds_id = ~Q(salesforce_activity_id__isnull=True) & ~Q(salesforce_activity_id="")
    found = Activity.objects.filter(deleted_at__isnull=True)
    if ids is not None:
        found = found.filter(id__in=list(ids))
    return (
        found.filter(lead_verified_q())
        .filter(holds_id)
        .filter(
            Q(status__in=NOT_HANDED_IN_STATUSES)
            | Q(status__in=LEAD_REVIEWABLE_STATUSES)
        )
        .order_by("planned_date", "id")
    )


def hand_in_entered_work(*, apply: bool = False, ids=None) -> list[dict]:
    """What there is to do, and with ``apply`` it is done. Each row says the
    activity and what happens to it; an empty list means nothing to do.

    ``ids`` narrows it to those activities: the Salesforce ID drawer hands in
    the one it saved an ID on when the Submit gates find something missing
    (owner, 2026-10-19: completed work with its Salesforce ID "MUST show for
    the PLs to approve"). The lead sees what is missing and approves or
    returns it. The scheduled job runs it for everything."""
    from apps.pl_review.services import (
        LEAD_REVIEWABLE_STATUSES,
        approve_on_hand_in,
        programme_lead_owner,
    )

    done = []
    for activity in _candidates(ids):
        lead_own = bool(programme_lead_owner(activity))
        if activity.status in LEAD_REVIEWABLE_STATUSES and not lead_own:
            # A CCEO's, already with the lead.
            continue
        done.append(
            {
                "id": activity.id,
                "from": activity.status,
                "to": "ia_verified" if lead_own else "submitted_to_pl",
            }
        )
        if apply:
            _hand_in(activity)
            approve_on_hand_in(activity)
    return done


def _hand_in(activity) -> None:
    """``submitted_to_pl``, as Submit writes it; already there, nothing."""
    from apps.activities.models import Activity, ActivityCompletionVerification
    from apps.pl_review.services import LEAD_REVIEWABLE_STATUSES

    if activity.status in LEAD_REVIEWABLE_STATUSES:
        return
    with transaction.atomic():
        a = Activity.objects.select_for_update().get(pk=activity.pk)
        if a.status not in NOT_HANDED_IN_STATUSES:
            return
        a.status = "submitted_to_pl"
        if a.evidence_status == "none":
            a.evidence_status = "accepted"
        a.save(update_fields=["status", "evidence_status", "updated_at"])
        ActivityCompletionVerification.objects.update_or_create(
            activity=a,
            defaults={
                "salesforce_id": a.salesforce_activity_id or "",
                "entered_by": a.responsible_staff_id or "system",
                "status": "pending",
            },
        )
    activity.status = a.status
