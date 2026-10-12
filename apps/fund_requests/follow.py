"""The weekly request and the monthly draft follow a save once, when it ends.

Both are totals over an owner's week and month, rebuilt whole from the cost
lines as they stand: the week's lines are deleted and written again, and so
are the month's. A reschedule between two days asked for that three times,
after the day the visit left was re-priced, after the day it joined, and once
more for the visit itself, and every time for the same owner, week and month.
In production the weekly rebuild writes about fifty rows a time and the
monthly about a hundred and seventy-five (pg_stat_statements, 2026-10-12), so
one reschedule deleted and wrote some 675 rows to end where the last rebuild
alone would have left it.

Inside `fund_requests_follow_once` the three askers only say which owner's
week and month they mean, and each is rebuilt once when the block ends, from
the lines the save ended with. The rebuild reads nothing but the lines and the
request's own status, so the last one is the only one whose answer is kept.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

#: The owner-weeks and owner-months waiting for the block in hand to end.
_waiting: ContextVar[dict | None] = ContextVar(
    "fund_requests_follow_once", default=None
)


@contextmanager
def fund_requests_follow_once():
    """Rebuild each weekly request and monthly draft asked for inside this
    block once, when it ends. It must sit inside the save's transaction: a
    block that ends in an error rebuilds nothing, and the save is undone
    with it. Blocks nest; the outermost one rebuilds."""
    if _waiting.get() is not None:
        yield
        return
    waiting: dict = {"weeks": {}, "months": {}}
    token = _waiting.set(waiting)
    try:
        yield
    finally:
        _waiting.reset(token)
    from .monthly_service import sync_monthly_periods
    from .weekly_service import generate_weekly_fund_request

    for owner, week_start in waiting["weeks"]:
        generate_weekly_fund_request(owner, week_start.isoformat())
    sync_monthly_periods(set(waiting["months"]))


def weeks_wait(buckets) -> bool:
    """Leave these owner-weeks for the block in hand; False outside one."""
    waiting = _waiting.get()
    if waiting is None:
        return False
    for bucket in buckets:
        waiting["weeks"][bucket] = None
    return True


def months_wait(periods) -> bool:
    """Leave these owner-months for the block in hand; False outside one."""
    waiting = _waiting.get()
    if waiting is None:
        return False
    for period in periods:
        waiting["months"][period] = None
    return True


__all__ = ["fund_requests_follow_once", "weeks_wait", "months_wait"]
