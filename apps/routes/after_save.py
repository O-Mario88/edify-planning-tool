"""The route check of a day follows the save that changed the day.

Every time a day's visits are priced, the day's route is worked out again:
which schools, in what order, how far, whether it fits the day, what to
suggest (`DailyVisitRouteBatchService.rebuild_for`). It is advice beside the
plan, written to tables of its own, and the save has always ignored its
failure ("a route problem must never break pricing"). It was nevertheless
done inside the save: about thirty statements for a day of school visits,
and an in-school training moved between two days paid for it twice
(profiled 2026-10-13, when production took 2.0 to 2.6 s for such a move).

The days are now only remembered while the save runs, and worked out once
it has committed, off the request: the answer does not wait for them. A day
changed several times by one save is worked out once.

`ROUTE_CHECK_AFTER_SAVE=false` works the route out inside the save again,
which is also what happens under the test runner (where a test's transaction
never commits) and wherever no transaction is open.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings
from django.db import connections, transaction

logger = logging.getLogger(__name__)

_running: list[threading.Thread] = []
_running_lock = threading.Lock()


def _rebuild(days) -> None:
    from apps.routes.engine import DailyVisitRouteBatchService

    for responsible_user, visit_date in days:
        try:
            DailyVisitRouteBatchService.rebuild_for(responsible_user, visit_date)
        except Exception:  # noqa: BLE001 — route intelligence is advisory
            logger.warning(
                "Route check failed for %s on %s",
                responsible_user,
                visit_date,
                exc_info=True,
            )


class _RoutesOnCommit:
    """The days whose route is worked out when the transaction commits."""

    def __init__(self) -> None:
        self.days: dict[tuple, None] = {}

    def __call__(self) -> None:
        days, self.days = list(self.days), {}
        if not days:
            return

        def run() -> None:
            try:
                _rebuild(days)
            finally:
                connections.close_all()
                with _running_lock:
                    if threading.current_thread() in _running:
                        _running.remove(threading.current_thread())

        thread = threading.Thread(target=run, name="edify-route", daemon=True)
        with _running_lock:
            _running.append(thread)
        thread.start()


def _waits_for_commit(connection) -> bool:
    return bool(getattr(settings, "ROUTE_CHECK_AFTER_SAVE", False)) and any(
        not getattr(block, "_from_testcase", False)
        for block in connection.atomic_blocks
    )


def rebuild_after_save(responsible_user, visit_date) -> None:
    """Work out this day's route once the save in hand has committed; now,
    where there is no save in hand."""
    connection = transaction.get_connection()
    if not _waits_for_commit(connection):
        _rebuild([(responsible_user, visit_date)])
        return
    waiting = next(
        (
            callback
            for _sids, callback, _robust in connection.run_on_commit
            if isinstance(callback, _RoutesOnCommit)
        ),
        None,
    )
    if waiting is None:
        waiting = _RoutesOnCommit()
        transaction.on_commit(waiting, robust=True)
    waiting.days[(responsible_user, visit_date)] = None


def wait(timeout: float = 30.0) -> None:
    """Let the route checks still running finish (tests, scripts)."""
    with _running_lock:
        threads = list(_running)
    for thread in threads:
        thread.join(timeout)


__all__ = ["rebuild_after_save", "wait"]
