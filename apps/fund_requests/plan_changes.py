"""A plan that changes takes its unpaid weekly fund request back (owner,
2026-10-07).

"When you click complete or submit fund request and did not complete fund
request or it is returned … it blocks it from editing. Can you lift it so
that there is no restriction."

A weekly request that has left its owner's hands is a frozen snapshot. The
cost writer and the day's visit batch both refuse to rebuild a line under it
(``apps.budget.costing_service.apply_to_activity``,
``apps.daily_visit_batches.services._is_locked``), which is right while
somebody is approving it: nobody signs a figure that is moving. It also meant
the plan under it could not move, until an approver sent the request back.

The plan now comes first. When an activity is edited or moved in a week whose
request has been sent and not paid, the request comes back to its owner the
way a returned one does: it is rebuilt from the changed plan and sent again
with the new figures, and whoever was asked to approve or pay it is told why
it left their list. Nothing is approved on figures that have since changed.

A request that has been paid is not touched here. Money that has moved is a
record, and the cost writer keeps refusing to rebuild under it: that change
is a budget amendment.

The month's request follows the plan (owner, 2026-10-08: "lift the monthly
one too"). A Programme Lead's team request for the month is a different
document: one snapshot of a whole team, read by the Country Director, while
the General Budget it feeds is computed from the live cost lines and the
weekly request is what the accountant pays from. Taking it back on every
officer's change would un-send a team's month because one visit moved. So it
stays where it is, with its reviewer or approved, and its lines and total are
brought up to date with the changed plan in the same save
(``carry_monthly_requests``). Its preparer, and whoever approved it, are told
when its total moved, and every such change is in the audit log.

Only a planner's own change does this (``planner_change``). A re-pricing
sweep that meets a monthly request in its approval chain is still refused.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from datetime import timedelta

from django.db import transaction

from .models import (
    FundRequestItem,
    FundRequestPeriod,
    FundRequestStatus,
    WeeklyFundRequest,
)

logger = logging.getLogger("edify.weekly_fund_request")

#: The owner's own draft: where a request taken back returns to.
DRAFT_STATUS = "pending_responsible_confirmation"

#: Sent and not paid: with its approver, approved and waiting for the
#: accountant, or set aside by its owner ("No Advance This Week").
SENT_UNPAID_STATUSES = (
    "submitted_to_pl",
    "submitted_to_cd",
    "confirmed_for_advance",
    "not_requested",
)

TAKEN_BACK_EVENT = "weekly_fund_request_taken_back"


def _week_of(day):
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def sent_unpaid_requests(activity, days=()):
    """The weekly requests a change to ``activity`` would run into: the ones
    carrying its cost lines, and its owner's requests for the weeks of
    ``days`` (the day it leaves and the day it moves to), where they have
    been sent and not paid.

    Partner-delivered work is paid through the partner's invoice and sits in
    no staff request, so it meets none.
    """
    if getattr(activity, "delivery_type", "") == "partner":
        return WeeklyFundRequest.objects.none()
    from django.db.models import Q

    from apps.activities.models import ActivityScheduleCostLine
    from apps.activities.services import _funding_owner_id

    wanted = Q(lines__activity_budget_line__activity=activity)
    owners = set(
        ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
            "responsible_user", flat=True
        )
    )
    owners.add(_funding_owner_id(activity))
    owners.discard(None)
    owners.discard("")
    for day in {day for day in days if day}:
        week_start, _week_end = _week_of(day)
        wanted |= Q(responsible_user__in=owners, week_start_date=week_start)
    return WeeklyFundRequest.objects.filter(
        id__in=WeeklyFundRequest.objects.filter(wanted).values("id"),
        status__in=SENT_UNPAID_STATUSES,
    )


def will_take_back(activity, days=()) -> list[WeeklyFundRequest]:
    """What a drawer shows before the save: the requests that will come back."""
    return list(sent_unpaid_requests(activity, days).order_by("week_start_date"))


def take_back_for_plan_change(activity, principal, *, days=()) -> list:
    """Bring the unpaid requests a change to ``activity`` runs into back to
    their owner, so the change can be priced and the week rebuilt.

    Call it inside the transaction that makes the change, before the cost
    lines are touched: a refusal further on then puts the requests back where
    they were, and the notices below are never sent.
    """
    from .weekly_service import _sync_advances

    taken = []
    requests = list(
        WeeklyFundRequest.objects.select_for_update()
        .filter(id__in=sent_unpaid_requests(activity, days).values("id"))
        .order_by("week_start_date", "id")
    )
    for wfr in requests:
        if wfr.status not in SENT_UNPAID_STATUSES:
            continue
        was = wfr.status
        wfr.status = DRAFT_STATUS
        wfr.confirmed_at = None
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])
        # The lines go back to pending with the request, as on a return.
        # An advance whose money has moved is left exactly as it is.
        _sync_advances(wfr, DRAFT_STATUS, "advance")
        taken.append((wfr, was))

    if not taken:
        return []

    for wfr, _was in taken:
        # The freeze has lifted: repair a day's pool left over-allocated by a
        # cancellation made while the week was locked, as a return does.
        from apps.daily_visit_batches.services import resync_stale_batches

        resync_stale_batches(
            wfr.responsible_user, wfr.week_start_date, wfr.week_end_date
        )

    transaction.on_commit(lambda: _tell(taken, _named(activity), principal))
    return [wfr for wfr, _was in taken]


def _named(activity) -> str:
    """The activity as a notice names it: what it is, and where."""
    if activity is None:
        return "A planned activity"
    what = activity.activity_name_snapshot or activity.get_activity_type_display()
    if activity.school_id:
        return f"{what} at {activity.school.name}"
    if activity.cluster_id:
        return f"{what} for {activity.cluster.name}"
    return what


def _tell(taken, what: str, principal) -> None:
    """After the change has landed: the audit entry, the owner's notice and a
    word to whoever had the request on their list."""
    for wfr, was in taken:
        still_there = WeeklyFundRequest.objects.filter(id=wfr.id).first()
        _audit(principal, wfr, was, what)
        _notify_owner(wfr, was, what, still_there)
        _notify_reviewers(wfr, was, what)


def _audit(principal, wfr, was: str, what: str) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="weekly_fund_request.taken_back",
            subject_kind="WeeklyFundRequest",
            subject_id=wfr.id,
            actor_id=getattr(principal, "user_id", None)
            or str(getattr(principal, "id", "") or ""),
            actor_role=getattr(principal, "active_role", None),
            success=True,
            reason="A planned activity in this week was changed.",
            payload={
                "week_start": wfr.week_start_date.isoformat(),
                "from_status": was,
                "total_when_sent": wfr.total_amount,
                "activity": what,
            },
        )
    except Exception:  # noqa: BLE001 - the audit entry never blocks the edit
        logger.exception("weekly fund request take-back audit failed")


def _week_label(wfr) -> str:
    return f"{wfr.week_start_date:%-d %b} – {wfr.week_end_date:%-d %b}"


def _notify_owner(wfr, was: str, what: str, still_there) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        if still_there is None:
            body = (
                f"{what} changed after the fund request for {_week_label(wfr)} "
                "was sent. Nothing is left to fund in that week, so the "
                "request has been withdrawn."
            )
        elif was == "not_requested":
            body = (
                f"{what} changed in {_week_label(wfr)}, a week you had set to "
                "No Advance. The week's request is open again with the new "
                "figures: send it for approval, or choose No Advance again."
            )
        else:
            body = (
                f"{what} changed after the fund request for {_week_label(wfr)} "
                "was sent, so the request has come back to you with the new "
                "figures. Send it for approval again."
            )
        WorkflowNotificationService.trigger(
            event_type=TAKEN_BACK_EVENT,
            category="finance",
            priority="high",
            title="Weekly fund request came back to you",
            body=body,
            context_type="WeeklyFundRequest",
            context_id=wfr.id if still_there is not None else None,
            recipients=[wfr.responsible_user],
        )
    except Exception:  # noqa: BLE001 - a notice never blocks the edit
        logger.exception("weekly fund request take-back owner notice failed")


def _notify_reviewers(wfr, was: str, what: str) -> None:
    """Whoever had the request on their list is told why it is gone."""
    try:
        from apps.accounts.models import StaffSupervisorAssignment, User
        from apps.notifications.services import WorkflowNotificationService

        if was == "submitted_to_pl":
            ids = list(
                StaffSupervisorAssignment.objects.filter(
                    supervisee__user_id=wfr.responsible_user
                ).values_list("supervisor__user_id", flat=True)
            )
            waiting = "approve"
        elif was == "submitted_to_cd":
            ids = list(
                User.objects.filter(
                    active_role="CountryDirector", is_active=True
                ).values_list("id", flat=True)
            )
            waiting = "approve"
        elif was == "confirmed_for_advance":
            ids = list(
                User.objects.filter(
                    active_role="Accountant", is_active=True
                ).values_list("id", flat=True)
            )
            waiting = "disburse"
        else:
            return
        ids = [i for i in ids if i and i != wfr.responsible_user]
        if not ids:
            return
        owner = User.objects.filter(id=wfr.responsible_user).first()
        name = getattr(owner, "name", "") or "A staff member"
        WorkflowNotificationService.trigger(
            event_type=TAKEN_BACK_EVENT,
            category="finance",
            priority="normal",
            title="Weekly fund request taken back",
            body=(
                f"{name}'s fund request for {_week_label(wfr)} "
                f"(UGX {wfr.total_amount:,}) went back to them because {what} "
                f"in that week changed. There is nothing to {waiting} until "
                "it is sent again with the new figures."
            ),
            context_type="WeeklyFundRequest",
            context_id=None,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001 - a notice never blocks the edit
        logger.exception("weekly fund request take-back reviewer notice failed")


# ── The month's request follows the plan ────────────────────────────────────
#: A monthly request in its approval chain: sent to a reviewer, or approved by
#: one, and not yet with the accountant. Approved-for-payment, held and paid
#: requests are money on its way out or gone, and are not in this set.
MONTHLY_IN_CHAIN_STATUSES = frozenset(
    {
        FundRequestStatus.SUBMITTED,
        FundRequestStatus.SUBMITTED_TO_PL,
        FundRequestStatus.APPROVED_BY_PL,
        FundRequestStatus.SUBMITTED_TO_CD,
        FundRequestStatus.APPROVED_BY_CD,
        FundRequestStatus.SUBMITTED_TO_RVP,
        FundRequestStatus.APPROVED_BY_RVP,
    }
)

MONTHLY_FOLLOWED_EVENT = "monthly_fund_request_followed_plan"

#: The planner's change in hand: who is making it, what it is called, and the
#: total each monthly request had before the change touched it.
_change_in_hand: contextvars.ContextVar = contextvars.ContextVar(
    "edify_planner_change", default=None
)


@contextlib.contextmanager
def planner_change(principal=None, activity=None):
    """A planner is changing their own plan: an edit, a new date.

    Inside this block a monthly request in its approval chain does not refuse
    the re-pricing the change needs; it follows the plan. Blocks nest (Edit
    calls Reschedule); the outermost one reports what moved, once, when it
    ends without an error.
    """
    outer = _change_in_hand.get()
    if outer is not None:
        yield outer
        return
    change = {"principal": principal, "what": _named(activity), "totals": {}}
    token = _change_in_hand.set(change)
    try:
        yield change
    finally:
        _change_in_hand.reset(token)
    if change["totals"]:
        transaction.on_commit(lambda: _tell_monthly(change))


def follows_plan_change(fund_request) -> bool:
    """Whether a frozen monthly request lets this re-pricing through: only
    for a planner's own change, and only while the request is in its approval
    chain. The cost writer asks; a paid request is never asked about."""
    return (
        _change_in_hand.get() is not None
        and fund_request.period == FundRequestPeriod.MONTHLY
        and fund_request.status in MONTHLY_IN_CHAIN_STATUSES
    )


def _lines_the_request_holds(fund_request, activity):
    """The activity's cost lines that belong in this request, by the rule of
    whoever built it: a Programme Lead's team month holds every staff line of
    scheduled work, any other request the staff-fundable ones."""
    from apps.activities.facilitation import PARTNER_FEE_LINES
    from apps.activities.models import ActivityScheduleCostLine
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

    from .fundable import fundable_lines

    fy, _sep, month = (fund_request.period_key or "").rpartition("-M")
    if not month.isdigit():
        return ActivityScheduleCostLine.objects.none()
    lines = ActivityScheduleCostLine.objects.filter(
        activity=activity, fiscal_year=fy, month=int(month)
    )
    if fund_request.scope == "team":
        return (
            lines.filter(
                activity__deleted_at__isnull=True,
                activity__scheduled_date__isnull=False,
            )
            .exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
            .exclude(PARTNER_FEE_LINES)
        )
    return fundable_lines(lines)


def carry_monthly_requests(activity, fund_requests, old_line_ids) -> None:
    """Point the monthly requests that carried an activity's old cost lines
    at the lines just written in their place.

    A request item names its cost line by id, with no foreign key, so a
    rebuild used to leave it naming a line that no longer existed: a figure in
    the request with nothing behind it, and a request page that listed fewer
    lines than its total. Called by the cost writer inside its transaction,
    with the requests already locked. A request's own draft is left to the
    sync that rebuilds it whole.
    """
    old_line_ids = [str(line_id) for line_id in old_line_ids]
    change = _change_in_hand.get()
    for fund_request in fund_requests:
        if fund_request.period != FundRequestPeriod.MONTHLY:
            continue
        if (
            fund_request.scope == "own"
            and fund_request.status == FundRequestStatus.DRAFT
        ):
            continue
        stale = FundRequestItem.objects.filter(
            fund_request=fund_request,
            activity_schedule_cost_line_id__in=old_line_ids,
        )
        if not stale.exists():
            continue
        if change is not None and fund_request.status in MONTHLY_IN_CHAIN_STATUSES:
            change["totals"].setdefault(
                fund_request.id, (fund_request, int(fund_request.total_amount or 0))
            )
        stale.delete()
        FundRequestItem.objects.bulk_create(
            [
                FundRequestItem(
                    fund_request=fund_request,
                    activity_id=activity.id,
                    activity_schedule_cost_line_id=line.id,
                    amount=int(line.amount or 0),
                    period=fund_request.period,
                    period_key=fund_request.period_key,
                    added_after_generation=True,
                )
                for line in _lines_the_request_holds(fund_request, activity)
            ]
        )
        items = list(fund_request.items.values_list("activity_id", "amount"))
        fund_request.total_amount = sum(int(amount or 0) for _id, amount in items)
        fund_request.activity_count = len({activity_id for activity_id, _a in items})
        fund_request.save(
            update_fields=["total_amount", "activity_count", "updated_at"]
        )


def _month_label(fund_request) -> str:
    import calendar

    fy, _sep, month = (fund_request.period_key or "").rpartition("-M")
    if not month.isdigit():
        return fund_request.period_key or "the month"
    return f"{calendar.month_name[int(month)]} FY {fy}"


def _tell_monthly(change) -> None:
    """After the change has landed: one audit entry for each monthly request
    it carried along, and a word to its preparer and its approver where the
    total moved."""
    from .models import FundRequest

    principal, what = change["principal"], change["what"]
    for request_id, (_request, before) in change["totals"].items():
        fund_request = FundRequest.objects.filter(id=request_id).first()
        if fund_request is None:
            continue
        after = int(fund_request.total_amount or 0)
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="fund_request.followed_plan_change",
                subject_kind="FundRequest",
                subject_id=fund_request.id,
                actor_id=getattr(principal, "user_id", None)
                or str(getattr(principal, "id", "") or ""),
                actor_role=getattr(principal, "active_role", None),
                success=True,
                reason="A planned activity in this month was changed.",
                payload={
                    "period_key": fund_request.period_key,
                    "status": fund_request.status,
                    "total_before": before,
                    "total_after": after,
                    "activity": what,
                },
            )
        except Exception:  # noqa: BLE001 - the audit entry never blocks the edit
            logger.exception("monthly fund request follow audit failed")
        if after == before:
            continue
        try:
            from apps.notifications.services import WorkflowNotificationService

            recipients = [fund_request.submitted_by_user_id]
            if fund_request.status in (
                FundRequestStatus.APPROVED_BY_PL,
                FundRequestStatus.APPROVED_BY_CD,
                FundRequestStatus.APPROVED_BY_RVP,
            ):
                recipients.append(fund_request.reviewed_by_user_id)
            WorkflowNotificationService.trigger(
                event_type=MONTHLY_FOLLOWED_EVENT,
                category="finance",
                priority="normal",
                title="Monthly request total changed",
                body=(
                    f"{what} changed, so the {_month_label(fund_request)} "
                    f"request now totals UGX {after:,} (it was UGX {before:,}). "
                    "It stays where it is; nothing needs sending again."
                ),
                context_type="FundRequest",
                context_id=fund_request.id,
                recipients=[r for r in recipients if r],
            )
        except Exception:  # noqa: BLE001 - a notice never blocks the edit
            logger.exception("monthly fund request follow notice failed")


__all__ = [
    "DRAFT_STATUS",
    "MONTHLY_FOLLOWED_EVENT",
    "MONTHLY_IN_CHAIN_STATUSES",
    "SENT_UNPAID_STATUSES",
    "TAKEN_BACK_EVENT",
    "carry_monthly_requests",
    "follows_plan_change",
    "planner_change",
    "sent_unpaid_requests",
    "take_back_for_plan_change",
    "will_take_back",
]
