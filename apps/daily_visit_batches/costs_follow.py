"""A save answers first; its costs follow.

Scheduling, moving or cancelling a school visit changes who shares a day, so
every visit on that day is priced again, and the owner's week and month are
filed again from the new lines. Read from production on 2026-10-13, after the
work had been cut to under half its statements: a reschedule still took 2.0
to 2.6 seconds and a new visit 1.9 to 3.1, at about nine milliseconds a
statement. The person who pressed Save was waiting for the other visits of
the day to be priced, not for their own change to be stored.

Inside `costs_follow` a save does what decides whether it stands: the record
is changed, the visit leaves and joins its days, every rule is asked. The
re-pricing of those days, the re-filing of the week and month and the note a
move writes on its lines are kept, and the save then:

1. **asks what the pricing would have refused** (`_assert_days_can_follow`):
   a day whose rates are missing, a day whose transport has been paid, a
   member whose advance, weekly request or monthly request has moved. The
   same rows are read and locked, and the same words are raised, as when the
   pricing asks, so a save that would have been refused still is;
2. **writes down what it kept** (`CostsToFollow`), in its own transaction: a
   crash between the answer and the pricing loses nothing;
3. **answers**, and prices in a thread of its own once it has committed.

What was kept is done exactly as the save would have done it: the same days
in the same order, read from the same members, then the week and month, then
the note. `test_costs_follow` holds the two ways to each other across the
whole database.

Whoever needs the figures has them settled first (`settled_first`):

* the person who saved, on their next request (a cookie says there is
  something to wait for, so a request without it asks nothing);
* any step that sends, confirms or pays a fund request;
* the next save in the same request.

A refusal met after the answer cannot undo the save. It can only come from
money that moved in the moment between the save and its pricing; the row is
then held with the reason, the day stays as `batch_needs_repricing` finds
it, and `resync_stale_batches` repairs it when the request comes back, as
for a visit cancelled inside a locked week.

`SAVES_ANSWER_FIRST=false` prices inside the save again. It is off under the
test runner, and nothing is kept outside a request (a command, a scheduled
job, a script): there is nobody to answer.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime

from django.conf import settings
from django.db import OperationalError, connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, EdifyAPIException

logger = logging.getLogger(__name__)

#: The cookie that tells the next request there may be costs to wait for.
COOKIE = "edify_costs_following"
COOKIE_SECONDS = 120

#: How many times a row is tried before it is held for a person to look at.
MAX_ATTEMPTS = 5

#: True while kept work is being done: nothing done then is kept again.
_settling: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "costs_follow_settling", default=False
)
#: The rows this request has written down, for the cookie.
_asked_here: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "costs_follow_asked_here", default=None
)

_running: list[threading.Thread] = []
_running_lock = threading.Lock()


class _Kept:
    """What one save keeps for after its answer."""

    def __init__(self, principal) -> None:
        self.principal = principal
        #: The days are a group's: each is read from its members while the
        #: others are priced (`each_day_priced_once(leaving_too=True)`).
        self.together = False
        #: Something in the save needs the figures before it ends.
        self.priced_here = False


def answers_first() -> bool:
    """Whether a save started now keeps its costs for after its answer."""
    from apps.core.request_context import get_request_context

    return (
        bool(getattr(settings, "SAVES_ANSWER_FIRST", False))
        and not _settling.get()
        and get_request_context() is not None
    )


@contextmanager
def costs_follow(principal=None, *, when: bool = True):
    """Keep the pricing this block asks for until the save has answered.

    Use it inside the save's transaction, around everything that changes who
    is on a day. `when=False` is a plain block: for a door that sometimes
    sits inside a larger change which reports once for all of it.

    Blocks nest, and the outermost keeps. Inside a block that already prices
    a day once (`each_day_priced_once`) or files once
    (`fund_requests_follow_once`) this one keeps nothing: that caller reads
    the result before it ends.
    """
    from apps.budget.costing_service import rate_cards_held
    from apps.fund_requests.follow import fund_requests_kept

    from . import services

    outer = services._kept_for_later.get()
    if outer is not None:
        if outer.principal is None:
            # A group opens its block before it knows who is asking.
            outer.principal = principal
        yield
        return
    connection = transaction.get_connection()
    if (
        not when
        or not answers_first()
        or services._days_to_price.get() is not None
        or not connection.in_atomic_block
    ):
        yield
        return
    _settle_what_this_request_asked()
    kept = _Kept(principal)
    days: dict = {}
    afterwards: list = []
    with rate_cards_held(), fund_requests_kept() as waiting:
        if waiting is None:
            # Someone outside is already filing once, and reads the result.
            yield
            return
        tokens = (
            services._kept_for_later.set(kept),
            services._days_to_price.set(days),
            services._after_pricing.set(afterwards),
        )
        try:
            yield
        finally:
            services._after_pricing.reset(tokens[2])
            services._days_to_price.reset(tokens[1])
            services._kept_for_later.reset(tokens[0])
        _hand_over(kept, days, afterwards, waiting)


def price_on_its_way(activity) -> bool:
    """Whether this activity's day is written down to be priced, or kept by
    the save in hand: it has no lines yet because they are on their way, not
    because it was never priced."""
    from . import services
    from .models import CostsToFollow

    batch_id = getattr(activity, "daily_visit_batch_id", None)
    if not batch_id:
        return False
    if batch_id in (services._days_to_price.get() or {}):
        return True
    return any(
        batch_id == day
        for steps in CostsToFollow.objects.values_list("steps", flat=True)
        for day, _owner in steps.get("days", ())
    )


def priced_in_this_save() -> None:
    """Say that the save in hand needs its figures before it ends: it is
    priced inside the save, as every save was. For a step whose own notices
    are written from the result (a weekly request taken back for the change
    tells its owner what was left in it)."""
    from . import services

    kept = services._kept_for_later.get()
    if kept is not None:
        kept.priced_here = True


def _do_now(kept: _Kept, days: dict, afterwards: list, waiting: dict) -> None:
    """Price, file and note inside the save, in the order it always did."""
    from apps.fund_requests.follow import refile

    from .services import price_kept_days

    price_kept_days(days, together=kept.together)
    if kept.together:
        for then, _note in afterwards:
            then()
        refile(waiting)
    else:
        refile(waiting)
        for then, _note in afterwards:
            then()


def _hand_over(kept: _Kept, days: dict, afterwards: list, waiting: dict) -> None:
    """The block has ended without an error: check, write down, and leave
    the rest for after the answer; or do it now where it cannot be left."""
    if not (days or afterwards or waiting["weeks"] or waiting["months"]):
        return
    notes = [note for _then, note in afterwards]
    if kept.priced_here or any(note is None for note in notes):
        _do_now(kept, days, afterwards, waiting)
        return

    _assert_days_can_follow(days, together=kept.together)

    from apps.core.acting import _STAMP_MEMO
    from apps.core.request_cache import store
    from apps.core.request_context import get_request_context
    from apps.fund_requests.plan_changes import change_in_hand

    from .models import CostsToFollow

    principal = kept.principal
    asked_by = getattr(principal, "user_id", None) or str(
        getattr(principal, "id", "") or ""
    )
    owners = {owner for _catalogue, owner in days.values()}
    owners.update(owner for owner, _week in waiting["weeks"])
    owners.update(owner for owner, _fy, _month in waiting["months"])
    owners.discard(None)
    owners.discard("")
    context = get_request_context()
    acting = (store() or {}).get(_STAMP_MEMO)
    change = change_in_hand()
    row = CostsToFollow.objects.create(
        owners=sorted(owners),
        asked_by=asked_by or "",
        asked_by_role=str(getattr(principal, "active_role", "") or ""),
        steps={
            "days": [[batch_id, owner] for batch_id, (_c, owner) in days.items()],
            "together": kept.together,
            "weeks": [[owner, week.isoformat()] for owner, week in waiting["weeks"]],
            "months": [list(period) for period in waiting["months"]],
            "notes": notes,
            "change": change["what"] if change is not None else None,
        },
        provenance={
            "ip": context.ip_address if context else None,
            "agent": context.user_agent if context else None,
            "correlation": context.correlation_id if context else None,
            "acting": list(acting) if acting else None,
        },
    )
    asked = _asked_here.get()
    if asked is None:
        asked = []
        _asked_here.set(asked)
    asked.append(row.id)
    _when_the_save_commits(row.id)


def _assert_days_can_follow(days: dict, *, together: bool) -> None:
    """Refuse the save for what pricing these days would have refused.

    Each day is worked out as the pricing will find it (`_plan_day`), its
    transport is asked whether it has been paid, and its members are asked
    the finance guards. What all of them need is read once; the refusal
    raised is the first the pricing would have met, day by day in the order
    the days will be priced, and within a day in the order it asks."""
    if not days:
        return
    from apps.budget.costing_service import _ask_money_guards, _money_under
    from apps.fund_requests.vendor_channel import (
        TRANSPORT_PAID,
        paid_transport_amounts,
        school_transport_amount,
    )

    from .models import DailyVisitBatch
    from .return_day import days_standing
    from .services import _plan_day, _where_days_stand

    batches = {
        batch.id: batch for batch in DailyVisitBatch.objects.filter(id__in=list(days))
    }
    # A day that follows another in the same save is priced after it: it
    # reads that day as the pricing will have left it, and the days after it
    # as they were last priced. A group's days are all read from their
    # members (`price_kept_days`).
    everywhere = _where_days_stand(days) if together else None
    standing: dict = {}
    planned = []
    for batch_id, (catalogue, owner) in days.items():
        batch = batches.get(batch_id)
        if batch is None:
            continue
        refusal = None
        day = None
        try:
            with days_standing(everywhere if together else standing):
                day = _plan_day(batch, catalogue, owner, with_recipes=False)
        except BadRequest as refused:
            refusal = refused
        else:
            standing[(batch.responsible_user, batch.visit_date)] = day["is_away"]
        planned.append((batch, day, refusal))

    paid = paid_transport_amounts([batch.id for batch, _day, _refusal in planned])
    members = [
        member
        for _batch, day, _refusal in planned
        if day is not None
        for member in day["activities"]
    ]
    money = _money_under([member.id for member in members]) if members else None
    for batch, day, refusal in planned:
        if refusal is not None:
            raise refusal
        if batch.id in paid and paid[batch.id] != school_transport_amount(
            batch, day["pool"]
        ):
            raise BadRequest(TRANSPORT_PAID)
        if day["activities"]:
            _ask_money_guards(day["activities"], money)


# ── After the answer ────────────────────────────────────────────────────────


class _SettleOnCommit:
    """The rows to settle when the transaction in hand commits."""

    def __init__(self) -> None:
        self.rows: list = []

    def __call__(self) -> None:
        rows, self.rows = list(self.rows), []
        if rows:
            _settle_in_a_thread(rows)


def _when_the_save_commits(row_id) -> None:
    connection = transaction.get_connection()
    waiting = next(
        (
            callback
            for _sids, callback, _robust in connection.run_on_commit
            if isinstance(callback, _SettleOnCommit)
        ),
        None,
    )
    if waiting is None:
        waiting = _SettleOnCommit()
        transaction.on_commit(waiting, robust=True)
    waiting.rows.append(row_id)


def _settle_in_a_thread(row_ids) -> None:
    def run() -> None:
        try:
            for attempt in range(3):
                try:
                    settle(ids=row_ids)
                    break
                except OperationalError:
                    # A deadlock or a lost connection: what was kept is
                    # still written down. Try again on a fresh connection.
                    logger.warning(
                        "Costs to follow %s: retrying after a database error",
                        row_ids,
                        exc_info=True,
                    )
                    connections.close_all()
                    time.sleep(0.2 * (attempt + 1))
        except Exception:  # noqa: BLE001 — the sweep takes what is left
            logger.exception("Costs to follow %s were not settled", row_ids)
        finally:
            connections.close_all()
            with _running_lock:
                if threading.current_thread() in _running:
                    _running.remove(threading.current_thread())

    thread = threading.Thread(target=run, name="edify-costs-follow", daemon=True)
    with _running_lock:
        _running.append(thread)
    thread.start()


def wait(timeout: float = 30.0) -> None:
    """Let the settling still running finish (tests, scripts)."""
    with _running_lock:
        threads = list(_running)
    for thread in threads:
        thread.join(timeout)


def _settle_what_this_request_asked() -> None:
    """A second save in one request starts from settled figures, as it would
    have when the first priced its days itself. What the transaction in
    hand has itself written down is left: an in-school training and its
    visit are two records of one save, and both are done after its answer,
    in the order they were written."""
    asked = _asked_here.get()
    if not asked:
        return
    connection = transaction.get_connection()
    in_hand = {
        row_id
        for _sids, callback, _robust in connection.run_on_commit
        if isinstance(callback, _SettleOnCommit)
        for row_id in callback.rows
    }
    earlier = [row_id for row_id in asked if row_id not in in_hand]
    if earlier:
        settle(ids=earlier)


def settled_first(*, owner: str | None = None, user: str | None = None) -> int:
    """Settle what is written down before the caller reads or commits the
    figures: for `owner`'s days, for whatever `user` asked or owns, or, with
    neither, for everyone. One read where nothing is waiting, which is
    nearly always. Waits for a settling already under way."""
    return settle(owner=owner, user=user)


def settle(
    *,
    ids=None,
    owner: str | None = None,
    user: str | None = None,
    older_than=None,
    held_too: bool = False,
) -> int:
    """Do what the saves wrote down, oldest first; the number of rows done.

    Each row is done in a block of its own inside one transaction that holds
    the rows locked, so two settlers never do the same row and the second
    waits for the first. A row that is refused, or fails `MAX_ATTEMPTS`
    times, is held and no longer tried here (`held_too` tries it again).
    """
    from .models import CostsToFollow

    rows = CostsToFollow.objects.all()
    if not held_too:
        rows = rows.filter(held_at__isnull=True)
    if ids is not None:
        rows = rows.filter(id__in=list(ids))
    if owner:
        rows = rows.filter(owners__contains=[owner])
    if user:
        rows = rows.filter(Q(asked_by=user) | Q(owners__contains=[user]))
    if older_than is not None:
        rows = rows.filter(created_at__lte=timezone.now() - older_than)
    done = 0
    with transaction.atomic():
        found = list(rows.select_for_update().order_by("id"))
        # A day that a later row prices again is left to that row: priced
        # here as well it would be written twice with the same members. So
        # three visits scheduled onto one day by one save are priced once,
        # as a cluster's day is (`each_day_priced_once`).
        again: set = set()
        leave = {}
        for row in reversed(found):
            days = {batch_id for batch_id, _owner in row.steps.get("days", ())}
            leave[row.id] = days & again
            again |= days
        for row in found:
            try:
                with transaction.atomic():
                    _do(row, leave=leave[row.id])
                    row.delete()
                done += 1
            except EdifyAPIException as refused:
                _hold(row, f"Refused: {refused}")
            except OperationalError:
                raise
            except Exception as error:  # noqa: BLE001 — kept for another try
                logger.exception("Costs to follow %s failed", row.id)
                row.attempts += 1
                if row.attempts >= MAX_ATTEMPTS:
                    _hold(row, f"Failed: {error!r}"[:500])
                else:
                    row.save(update_fields=["attempts", "updated_at"])
    return done


def _hold(row, reason: str) -> None:
    logger.error(
        "Costs to follow %s held for %s: %s", row.id, ", ".join(row.owners), reason
    )
    row.held_at = timezone.now()
    row.held_reason = reason[:500]
    row.attempts += 1
    row.save(update_fields=["held_at", "held_reason", "attempts", "updated_at"])


class _Asker:
    """The person who saved, as the notices and the audit read a principal."""

    def __init__(self, user_id: str, role: str) -> None:
        self.id = user_id
        self.user_id = user_id
        self.active_role = role or None


@contextmanager
def _as_it_was_asked(row):
    """The request the save came in on, for the audit rows the pricing
    writes: its address, its correlation id and the acting capacity it was
    made in. Whatever request or thread is doing the work is put back."""
    from apps.core import request_cache, request_context
    from apps.core.acting import _STAMP_MEMO
    from apps.fund_requests import follow, plan_changes

    from . import services

    provenance = row.provenance or {}
    before_context = request_context._current.get()
    before_store = request_cache.store()
    token = _settling.set(True)
    # Nothing a save in hand is collecting takes what is done here.
    apart = [
        (var, var.set(None))
        for var in (
            services._kept_for_later,
            services._days_to_price,
            services._after_pricing,
            follow._waiting,
            plan_changes._change_in_hand,
        )
    ]
    request_context._current.set(
        request_context.RequestContext(
            ip_address=provenance.get("ip"),
            user_agent=provenance.get("agent"),
            correlation_id=provenance.get("correlation")
            or request_context.new_correlation_id(),
        )
    )
    request_cache.begin()
    acting = provenance.get("acting")
    if acting:
        request_cache.store()[_STAMP_MEMO] = (acting[0], acting[1])
    try:
        yield
    finally:
        for var, var_token in reversed(apart):
            var.reset(var_token)
        request_cache._local.store = before_store
        request_context._current.set(before_context)
        _settling.reset(token)


def _reschedule_note(note: dict) -> None:
    from apps.activities.models import Activity
    from apps.hr.leave_services import LeaveBudgetImpactService

    activity = Activity.objects.filter(id=note["activity"]).first()
    if activity is None:
        return
    LeaveBudgetImpactService.handle_reschedule(
        activity,
        datetime.fromisoformat(note["old"]),
        datetime.fromisoformat(note["new"]),
        note["reason"],
    )


#: What a save may leave to be done once its days are priced, by kind.
NOTES = {"reschedule_note": _reschedule_note}


def reschedule_note(activity, old_date, new_date, reason) -> dict:
    """The note a move writes on the lines it leaves the visit with, as
    plain data (`once_days_are_priced(note=...)`)."""
    return {
        "kind": "reschedule_note",
        "activity": activity.id,
        "old": old_date.isoformat(),
        "new": new_date.isoformat(),
        "reason": reason,
    }


def _do(row, *, leave=frozenset()) -> None:
    """Price, file and note what one save kept, in the order it would have.
    `leave`: days a later row prices again, not priced here."""
    from apps.fund_requests.follow import fund_requests_kept, refile
    from apps.fund_requests.plan_changes import planner_change

    from .models import DailyVisitBatch
    from .services import price_kept_days

    steps = row.steps
    there = set(
        DailyVisitBatch.objects.filter(
            id__in=[batch_id for batch_id, _owner in steps["days"]]
        ).values_list("id", flat=True)
    )
    asked = {
        batch_id: (None, owner)
        for batch_id, owner in steps["days"]
        if batch_id in there
    }
    days = {batch_id: day for batch_id, day in asked.items() if batch_id not in leave}

    def notes() -> None:
        for note in steps["notes"]:
            NOTES[note["kind"]](note)

    change = (
        planner_change(_Asker(row.asked_by, row.asked_by_role), what=steps["change"])
        if steps.get("change")
        else contextlib.nullcontext()
    )
    with _as_it_was_asked(row), change:
        with fund_requests_kept() as waiting:
            price_kept_days(days, together=bool(steps["together"]), beside=asked)
            if steps["together"]:
                notes()
        for owner, week in steps["weeks"]:
            waiting["weeks"][(owner, date.fromisoformat(week))] = None
        for owner, fy, month in steps["months"]:
            waiting["months"][(owner, fy, int(month))] = None
        refile(waiting)
        if not steps["together"]:
            notes()


# ── The person who saved waits for their own figures ───────────────────────


class CostsFollowMiddleware:
    """A request from someone whose save is still being priced waits for it.

    The answer to a save that kept its costs sets a short cookie. A request
    carrying it settles what that person asked, or owns, before the view
    runs: it waits for the thread already doing it, or does it itself where
    the thread was lost. Nothing waiting, the cookie is taken away. A
    request without the cookie asks nothing at all.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _asked_here.set([])
        waited = False
        if request.COOKIES.get(COOKIE):
            user_id = str(getattr(getattr(request, "user", None), "id", "") or "")
            if user_id:
                waited = True
                try:
                    settle(user=user_id)
                except Exception:  # noqa: BLE001 — never blocks the page
                    logger.exception("Costs to follow: settling first failed")
        response = self.get_response(request)
        if _asked_here.get():
            response.set_cookie(
                COOKIE,
                "1",
                max_age=COOKIE_SECONDS,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure(),
            )
        elif waited:
            response.delete_cookie(COOKIE, samesite="Lax")
        return response


def sweep() -> dict:
    """The scheduled safety net: settle what a lost thread left behind, and
    try again what was held for a failure rather than a refusal."""
    from datetime import timedelta

    from .models import CostsToFollow

    settled = settle(older_than=timedelta(seconds=30))
    retried = 0
    for row in CostsToFollow.objects.filter(
        held_at__isnull=False,
        held_reason__startswith="Failed",
        attempts__lt=MAX_ATTEMPTS * 3,
    ):
        row.held_at = None
        row.save(update_fields=["held_at", "updated_at"])
        retried += settle(ids=[row.id])
    held = CostsToFollow.objects.filter(held_at__isnull=False).count()
    return {"settled": settled, "retried": retried, "held": held}


__all__ = [
    "COOKIE",
    "CostsFollowMiddleware",
    "NOTES",
    "answers_first",
    "costs_follow",
    "price_on_its_way",
    "priced_in_this_save",
    "reschedule_note",
    "settle",
    "settled_first",
    "sweep",
    "wait",
]
