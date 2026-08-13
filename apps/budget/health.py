"""Finance integrity checks: is the money where the work is, and asked once?

A data audit of the dev estate raised these. Each looks for a condition that is
invisible on any single page — every record involved is individually valid, and
only the relationship between them is wrong — which is exactly the kind of
defect that survives until someone reconciles totals by hand.

* **Period drift.** A cost line whose week is not its activity's week. The
  money is requested for one week and the work happens in another. Found five,
  all from one upload, all one week early: an activity scheduled at local
  midnight is stored as 21:00 UTC the previous day, and any code deriving the
  week from the raw UTC date lands it in the week before. `costing_service`
  gets this right today; the historical rows do not.

* **Split lines.** One activity's cost lines spread across two weeks, so no
  single weekly request carries its full cost.

* **Double funding.** One budget line claimed by two live weekly fund
  requests. Clean when first measured, and cheap to keep checking.

  The sibling condition — one person holding two requests for the same week —
  has no check here, because a database UniqueConstraint already makes it
  impossible to write. See the note further down.

Reported, never repaired here. A cost line in the wrong week may already sit
inside an approved or disbursed request, and silently moving money underneath a
finance decision is worse than the drift. Repair belongs to the controlled
data-repair workflow, with its dry run and its approval.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

#: Requests that no longer hold a claim on money.
_DEAD_REQUEST_STATUSES = ("returned_by_accountant", "returned", "cancelled")


def _issue(key, severity, count, summary, action):
    return {
        "key": key,
        "severity": severity if count else "ok",
        "count": count,
        "current_state": summary,
        "recommended_action": action if count else "None — nothing to do.",
    }


def cost_line_period_drift(limit: int = 500) -> dict:
    """Cost lines sitting in a different week from the activity they fund."""
    from apps.activities.models import ActivityScheduleCostLine

    drifted = []
    rows = ActivityScheduleCostLine.objects.select_related("activity").exclude(
        week_start_date=None
    )[:20000]
    for line in rows:
        activity = line.activity
        if not activity or not activity.planned_date:
            continue
        expected = activity.planned_date - timedelta(
            days=activity.planned_date.weekday()
        )
        if line.week_start_date != expected:
            drifted.append(
                {
                    "activity_id": activity.id,
                    "work_week": expected.isoformat(),
                    "money_week": line.week_start_date.isoformat(),
                    "amount": line.amount,
                }
            )
        if len(drifted) >= limit:
            break

    return {
        **_issue(
            "cost_line_period_drift",
            "high",
            len(drifted),
            f"{len(drifted)} cost line(s) sit in a different week from their "
            "activity — funded for one week, worked in another.",
            "Repair through the Data Repair Center: re-derive the week from "
            "the activity's local planned date, then re-sync the affected "
            "weekly requests. Check first whether the stale week's request is "
            "already approved or disbursed.",
        ),
        "samples": drifted[:10],
    }


def split_week_cost_lines() -> dict:
    """Activities whose cost lines straddle more than one week.

    Multi-day programme activities are EXEMPT: the §9 cross-period allocator
    (costing_service._programme_period_specs) deliberately dates their
    day-scaled components into the months the work happens in, stamping each
    split line's key with a ``#mYYYYMM`` suffix. Flagging those made every
    legitimate cross-month event a permanent "high" finding, which trains
    people to ignore the check (2026-08-12 audit M-8)."""
    from apps.activities.models import ActivityScheduleCostLine

    weeks = defaultdict(set)
    period_split_activities = set()
    for activity_id, week, key in ActivityScheduleCostLine.objects.exclude(
        week_start_date=None
    ).values_list("activity_id", "week_start_date", "cost_setting_key"):
        weeks[activity_id].add(week)
        if "#m" in (key or ""):
            period_split_activities.add(activity_id)
    split = [
        a
        for a, w in weeks.items()
        if len(w) > 1 and a not in period_split_activities
    ]

    return {
        **_issue(
            "split_week_cost_lines",
            "high",
            len(split),
            f"{len(split)} activity/activities have cost lines in more than "
            "one week, so no single weekly request carries the full cost.",
            "Re-price the activity so its lines share one week.",
        ),
        "samples": split[:10],
    }


def double_funded_budget_lines() -> dict:
    """One budget line claimed by more than one live weekly request."""
    from apps.fund_requests.models import WeeklyFundRequestLine

    claims = defaultdict(set)
    for request_id, line_id in (
        WeeklyFundRequestLine.objects.exclude(activity_budget_line=None)
        .exclude(weekly_fund_request__status__in=_DEAD_REQUEST_STATUSES)
        .values_list("weekly_fund_request_id", "activity_budget_line_id")
    ):
        claims[line_id].add(request_id)
    doubled = [line for line, requests in claims.items() if len(requests) > 1]

    return {
        **_issue(
            "double_funded_budget_lines",
            "critical",
            len(doubled),
            f"{len(doubled)} budget line(s) are claimed by more than one live "
            "weekly fund request — the same work funded twice.",
            "Return the duplicate request, then re-sync the activity so only "
            "the week it is actually planned in carries its cost.",
        ),
        "samples": doubled[:10],
    }


def partner_lines_in_staff_funding() -> dict:
    """Partner-delivered cost lines sitting in a staff funding channel.

    The one payable path for partner work is the post-IA PartnerPayment
    workflow. A partner activity's cost line carried in a WeeklyFundRequest
    line or mirrored as an AdvanceRequest is the double-funding seam the
    2026-07-30 audit closed: the same cost would be advanced to the managing
    staff member AND paid to the partner."""
    from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequestLine

    in_weekly = set(
        WeeklyFundRequestLine.objects.filter(
            activity_budget_line__activity__delivery_type="partner"
        )
        .exclude(weekly_fund_request__status__in=_DEAD_REQUEST_STATUSES)
        .values_list("activity_budget_line_id", flat=True)
    )
    in_advance = set(
        AdvanceRequest.objects.filter(activity__delivery_type="partner").values_list(
            "budget_line_id", flat=True
        )
    )
    offenders = sorted(in_weekly | in_advance)
    return {
        **_issue(
            "partner_lines_in_staff_funding",
            "critical",
            len(offenders),
            f"{len(offenders)} partner-delivered cost line(s) sit in a staff "
            "weekly fund request or advance — partner work must be paid only "
            "through the Partner Payment workflow.",
            "Run repair_costing_pipeline (or re-sync the activity) so the "
            "staff channels drop the partner lines.",
        ),
        "samples": offenders[:10],
    }


def payable_lines_without_approved_advance() -> dict:
    """Payable parent requests whose line ledger cannot safely release money.

    A period or weekly parent is only ready for the Accountant when every
    budget line has one approved AdvanceRequest. Missing rows and non-payable
    states (self-funded, not requested, returned, cancelled, already paid)
    would otherwise let the parent channel bypass the shared money ledger.
    """
    from apps.fund_requests.funding_guard import (
        DISBURSABLE_ADVANCE_STATUSES,
        PERIOD_DISBURSABLE_ADVANCE_STATUSES,
    )
    from apps.fund_requests.models import (
        AdvanceRequest,
        FundRequestItem,
        WeeklyFundRequestLine,
    )

    period_line_ids = set(
        FundRequestItem.objects.filter(
            fund_request__status__in=("approved", "sent_to_accountant")
        )
        .exclude(activity_schedule_cost_line_id="")
        .values_list("activity_schedule_cost_line_id", flat=True)
    )
    weekly_line_ids = set(
        WeeklyFundRequestLine.objects.filter(
            weekly_fund_request__status="confirmed_for_advance"
        ).values_list("activity_budget_line_id", flat=True)
    )
    eligible_period = set(
        AdvanceRequest.objects.filter(
            budget_line_id__in=period_line_ids,
            status__in=PERIOD_DISBURSABLE_ADVANCE_STATUSES,
        ).values_list("budget_line_id", flat=True)
    )
    eligible_weekly = set(
        AdvanceRequest.objects.filter(
            budget_line_id__in=weekly_line_ids,
            status__in=DISBURSABLE_ADVANCE_STATUSES,
        ).values_list("budget_line_id", flat=True)
    )
    blocked = sorted(
        str(line_id)
        for line_id in (period_line_ids - eligible_period)
        | (weekly_line_ids - eligible_weekly)
    )
    return {
        **_issue(
            "payable_lines_without_approved_advance",
            "critical",
            len(blocked),
            f"{len(blocked)} payable budget line(s) have no approved advance "
            "ledger row, so disbursement must remain blocked.",
            "Return or regenerate the affected request after reconciling its "
            "funding choice; do not release it outside the shared ledger.",
        ),
        "samples": blocked[:10],
    }


def dangling_fund_request_items() -> dict:
    """Monthly FundRequestItems whose source cost line no longer exists.

    FundRequestItem references its ActivityScheduleCostLine by a bare
    CharField, so a re-price's delete+rebuild orphans the payable item row
    silently (no CASCADE)."""
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import FundRequestItem

    item_line_ids = set(
        FundRequestItem.objects.exclude(activity_schedule_cost_line_id=None)
        .exclude(activity_schedule_cost_line_id="")
        .values_list("activity_schedule_cost_line_id", flat=True)
    )
    live = set(
        ActivityScheduleCostLine.objects.filter(id__in=item_line_ids).values_list(
            "id", flat=True
        )
    )
    dangling = sorted(item_line_ids - live)
    return {
        **_issue(
            "dangling_fund_request_items",
            "high",
            len(dangling),
            f"{len(dangling)} monthly fund-request item(s) reference a cost "
            "line that no longer exists — a payable amount with no source.",
            "Regenerate the affected monthly draft requests; submitted ones "
            "need accountant review before correction.",
        ),
        "samples": dangling[:10],
    }


def money_moved_on_cancelled_work() -> dict:
    """Disbursed/accounted advances whose activity was later cancelled.

    Cancellation deliberately preserves money-moved advances (they settle
    through return/accountability, never silent deletion). Each one is real
    cash in the field for work that will not happen — it must be actively
    settled, and until 2026-08-12 it also vanished from every budget rollup
    (the aggregates excluded cancelled activities before summing the ledger),
    so nobody was chasing it."""
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.fund_requests.models import (
        MONEY_MOVED_ADVANCE_STATUSES,
        AdvanceRequest,
    )

    open_rows = list(
        AdvanceRequest.objects.filter(
            status__in=MONEY_MOVED_ADVANCE_STATUSES,
            activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES,
        )
        # Fully settled money needs no chasing even if the work was cancelled.
        .exclude(status__in=("accounted", "reimbursed"))
        .values_list("id", flat=True)
    )
    return {
        **_issue(
            "money_moved_on_cancelled_work",
            "critical",
            len(open_rows),
            f"{len(open_rows)} advance(s) with money out of the account belong "
            "to cancelled/deferred/rejected activities and are not yet "
            "settled.",
            "Have each responsible user submit accountability (or the "
            "Accountant verify the return) so the cash comes back; the work "
            "itself will not happen.",
        ),
        "samples": [str(pk) for pk in open_rows[:10]],
    }


# There was a `duplicate_weekly_requests` check here. It is gone because it
# could never fire: WeeklyFundRequest carries a database UniqueConstraint on
# (responsible_user, week_start_date) named `uniq_weekly_request_owner_week`,
# so a second live request for one person-week cannot be written at all.
#
# A health check that cannot fire is worse than no check — it occupies a line
# on a page people scan for real problems, and its permanent green implies
# something is being watched when nothing is. The constraint is the stronger
# guarantee; `test_finance_integrity_health` proves it still bites.


def finance_integrity_health() -> dict:
    """Every finance-integrity check, for the System Health page."""
    checks = []
    for check in (
        cost_line_period_drift,
        split_week_cost_lines,
        double_funded_budget_lines,
        partner_lines_in_staff_funding,
        payable_lines_without_approved_advance,
        dangling_fund_request_items,
        money_moved_on_cancelled_work,
    ):
        try:
            checks.append(check())
        except Exception as exc:  # noqa: BLE001 — the page must still render
            checks.append(
                {
                    "key": check.__name__,
                    "severity": "unknown",
                    "count": None,
                    "current_state": f"Check failed to run: {exc}",
                    "recommended_action": "Investigate the check itself.",
                }
            )
    return {"checks": checks}
