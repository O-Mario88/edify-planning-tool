"""A per-request memo store for values that cannot change mid-request.

Several hot paths re-read the same immutable-for-this-request data dozens of
times: the public-holiday calendar, a staff member's approved leave, the org's
target-area configuration. Caching those at module level would be faster but
introduces a whole class of staleness bug — a management command that runs for
an hour would never see a new public holiday, and a test that creates a
holiday, reads it back, and rolls back would leak into the next test.

So the store is bound to a request and only exists while one is being handled.
Outside a request (tests calling services directly, management commands,
scheduled jobs) `store()` returns None and every caller falls through to the
live query. That keeps the production win without ever serving stale data to
code that runs outside the request cycle.
"""

from __future__ import annotations

import threading

_local = threading.local()


def store() -> dict | None:
    """The memo dict for the request being handled, or None if not in one."""
    return getattr(_local, "store", None)


def begin() -> None:
    _local.store = {}


def end() -> None:
    _local.store = None


def memoize(key, compute):
    """Return `compute()`, caching it under `key` for the rest of the request.

    `compute` is always called when there is no active request, so behaviour
    outside the request cycle is identical to having no cache at all.
    """
    bucket = store()
    if bucket is None:
        return compute()
    if key not in bucket:
        bucket[key] = compute()
    return bucket[key]
