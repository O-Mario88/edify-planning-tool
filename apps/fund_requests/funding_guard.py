"""Cross-channel mutual exclusion for planned-cost disbursement.

Every staff funding surface converges on one ``AdvanceRequest`` per activity
budget line.  A caller must hold those rows and prove every line is currently
approved for release before any parent request is marked disbursed.  Missing
rows are deliberately blockers: partner and cost-missing lines omit advances
by design and must never leak into a staff-payment channel.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

from .models import AdvanceRequest, AdvanceRequestStatus


DISBURSABLE_ADVANCE_STATUSES = (
    AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
    AdvanceRequestStatus.SUBMITTED_TO_ACCOUNTANT,
)
PERIOD_DISBURSABLE_ADVANCE_STATUSES = (
    AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
    *DISBURSABLE_ADVANCE_STATUSES,
)


def lock_disbursable_advances(
    line_ids, *, allowed_statuses=DISBURSABLE_ADVANCE_STATUSES
) -> list[AdvanceRequest]:
    """Lock and return the one approved advance for every budget line.

    This must be called inside ``transaction.atomic()``. Locking in stable
    budget-line order makes concurrent weekly/period releases serialize on the
    same rows; after the first commits, the second observes ``disbursed`` and
    fails closed.
    """

    unique_line_ids = sorted({str(line_id) for line_id in line_ids if line_id})
    if not unique_line_ids:
        raise BadRequest(
            "Cannot disburse — this request has no approved budget-line ledger."
        )

    advances = list(
        AdvanceRequest.objects.select_for_update()
        .filter(budget_line_id__in=unique_line_ids)
        .order_by("budget_line_id")
    )
    found = {str(advance.budget_line_id) for advance in advances}
    missing = len(set(unique_line_ids) - found)
    ineligible = sum(advance.status not in allowed_statuses for advance in advances)
    if missing or ineligible:
        raise BadRequest(
            "Cannot disburse — "
            f"{missing + ineligible} of this request's budget lines are missing "
            "an approved advance or already had money released. Reconcile the "
            "request before paying it."
        )
    return advances


__all__ = [
    "DISBURSABLE_ADVANCE_STATUSES",
    "PERIOD_DISBURSABLE_ADVANCE_STATUSES",
    "lock_disbursable_advances",
]
