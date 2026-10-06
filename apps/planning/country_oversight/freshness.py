"""Keeping Country Planning Oversight's figures current with the plan.

The page's figures are kept for ``DASHBOARD_CACHE_SECONDS`` and rebuilt by the
warmer every few minutes, so a visit scheduled now could stay off the Country
Director's page for five minutes (owner audit, 2026-10-01: "the data the CD
sees ... reflect the actual planned activities").

Whenever a record the figures are built from is saved or deleted — an
activity, a Partner hand-over, a cluster roster row, a school — the moment is
noted. A reader served a snapshot older than the last noted change gets it
rebuilt, but never more often than ``SETTLE_SECONDS``: a morning of planning
is hundreds of saves, and each rebuild reads the whole country.

Best-effort throughout: if the cache cannot be reached the figures are
served as they were, on the timings they always had.
"""

from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

CHANGED_KEY = "cpo:changed-at:v1"
#: The youngest a snapshot may be and still be rebuilt for a later change.
SETTLE_SECONDS = 20
#: How long a noted change is remembered: well past any snapshot's life.
REMEMBER_SECONDS = 60 * 60


def _enabled() -> bool:
    from django.conf import settings

    return int(getattr(settings, "DASHBOARD_CACHE_SECONDS", 0) or 0) > 0


def note_change(*_args, **_kwargs) -> None:
    """A record the figures read has changed. Signal-receiver shaped."""
    if not _enabled():
        return
    from django.core.cache import cache

    try:
        cache.set(CHANGED_KEY, timezone.now().timestamp(), timeout=REMEMBER_SECONDS)
    except Exception:  # noqa: BLE001 - the figures then follow their own timings
        logger.warning("Could not note a planning change", exc_info=True)


def overtaken(built_at) -> bool:
    """Has the plan changed since this snapshot was built, long enough ago
    that rebuilding it now is not rebuilding it on every save?"""
    if not _enabled() or built_at is None:
        return False
    from django.core.cache import cache

    try:
        changed = cache.get(CHANGED_KEY)
    except Exception:  # noqa: BLE001 - served as it was
        return False
    if not changed:
        return False
    built = built_at.timestamp()
    return changed > built and timezone.now().timestamp() - built >= SETTLE_SECONDS


#: The soonest a page served figures the plan has overtaken asks again.
RECHECK_FLOOR_SECONDS = 5


def settles_in(built_at) -> int:
    """Seconds until a reader of this snapshot would be given newer figures;
    0 when the plan has not changed since it was built.

    A page that follows the plan live (static/js/live-regions.js) reads
    itself again the moment something changes, and inside the settle window
    that read is served the figures as they were. This is how long it waits
    before asking once more, so the last change of a busy minute is not the
    one that never shows (owner, 2026-10-05: "Every event should update ...
    in real time").
    """
    if not _enabled() or built_at is None:
        return 0
    from django.core.cache import cache

    try:
        changed = cache.get(CHANGED_KEY)
    except Exception:  # noqa: BLE001 - served as it was, and not asked again
        return 0
    built = built_at.timestamp()
    if not changed or changed <= built:
        return 0
    left = SETTLE_SECONDS - (timezone.now().timestamp() - built)
    return max(RECHECK_FLOOR_SECONDS, int(left) + 1)


def live_read(request) -> bool:
    """Is this the page reading itself again because the plan changed?

    Such a read is never a forced rebuild, whatever the address says: a
    reader who pressed "read again" keeps ``refresh=1`` in the address, and
    every change in the country would otherwise rebuild the whole fold.
    """
    return request.headers.get("X-Requested-With") == "EdifyLive"


def claim(name: str) -> bool:
    """One reader at a time rebuilds a country's facts; the others are served
    what there is until it is done."""
    from django.core.cache import cache

    try:
        return bool(cache.add(f"cpo:rebuilding:{name}", 1, timeout=SETTLE_SECONDS))
    except Exception:  # noqa: BLE001 - then nobody rebuilds early
        return False


def connect() -> None:
    """Note a change whenever one of the records the figures read is written."""
    from django.db.models.signals import post_delete, post_save

    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.partners.models import PartnerAssignment
    from apps.schools.models import School

    for model in (Activity, ClusterActivityAttendance, PartnerAssignment, School):
        for signal in (post_save, post_delete):
            signal.connect(
                note_change,
                sender=model,
                dispatch_uid=f"cpo_freshness_{model.__name__}_{id(signal)}",
                weak=False,
            )
