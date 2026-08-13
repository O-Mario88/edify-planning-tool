"""THE definition of a staff-fundable budget line.

Every payment-channel builder (weekly generator, monthly draft sync, period
submit, PL monthly approval) must select lines through this one predicate.
The 2026-08-12 audit found four builders with four different exclusion sets:
the period channel included cancelled/deferred/partner/already-paid lines the
funding guard could never release, so approvers signed inflated totals and the
accountant hit permanent "reconcile the request" blocks.

Budget AGGREGATES (roll-ups, dashboards) deliberately do NOT use this
predicate — partner-delivered work belongs in budget totals even though it is
paid through the PartnerPayment workflow, never through a staff channel.
"""

from __future__ import annotations

from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
from .models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequestStatus

# Advance states that take a LINE out of any new fund request: money already
# moved through some channel, or the responsible owner explicitly chose not to
# be advanced for it. RETURNED is absent on purpose — a returned advance is
# re-requestable, and period approval re-routes it to the accountant.
NON_REQUESTABLE_ADVANCE_STATUSES = (
    *MONEY_MOVED_ADVANCE_STATUSES,
    AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT,
    AdvanceRequestStatus.NOT_REQUESTED,
    AdvanceRequestStatus.CANCELLED,
)


def fundable_lines(qs):
    """Narrow an ActivityScheduleCostLine queryset to staff-payable work.

    Excludes: soft-deleted or unscheduled activities, cancelled/rejected/
    deferred work, partner-delivered work (paid via PartnerPayment only),
    cost-missing activities (they carry no advances, so their lines would
    hard-block the whole request at the funding guard), and lines whose
    advance already moved money or was explicitly opted out by its owner.
    """
    return (
        qs.filter(
            activity__deleted_at__isnull=True,
            activity__scheduled_date__isnull=False,
            activity__cost_missing=False,
        )
        .exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .exclude(activity__delivery_type="partner")
        .exclude(advance_requests__status__in=NON_REQUESTABLE_ADVANCE_STATUSES)
    )


__all__ = [
    "NON_FUNDABLE_ACTIVITY_STATUSES",
    "NON_REQUESTABLE_ADVANCE_STATUSES",
    "fundable_lines",
]
