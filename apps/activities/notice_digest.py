"""One summary notice for many hand-ins at once.

A completion tells its reviewer that work has arrived (services
._notify_completion_routed, ._notify_ia_submitted). A bulk upload hands in
hundreds of activities in one go, and a Programme Lead sent one notice per
activity could not find anything else in their list. Inside
``collected_hand_in_notices()`` those notices are counted per recipient
instead of sent, and the caller sends each recipient one summary
(apps.bulk_completion.apply). The drawers, which hand in one activity at a
time, never enter it and notify exactly as before.
"""

from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar

_collected: ContextVar[dict | None] = ContextVar("hand_in_notices", default=None)


@contextmanager
def collected_hand_in_notices():
    """Yield ``{"review": Counter, "verification": Counter}`` of recipients."""
    bucket = {"review": Counter(), "verification": Counter()}
    token = _collected.set(bucket)
    try:
        yield bucket
    finally:
        _collected.reset(token)


def collect(kind: str, recipients) -> bool:
    """Count the notice instead of sending it; False when nothing collects."""
    bucket = _collected.get()
    if bucket is None:
        return False
    bucket[kind].update(r for r in (recipients or []) if r)
    return True
