"""Small cache primitives for expensive, read-only dashboard snapshots."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from django.core.cache import cache

T = TypeVar("T")
_MISSING = object()
logger = logging.getLogger(__name__)


def _read(key: str) -> tuple[bool, object]:
    try:
        return True, cache.get(key, _MISSING)
    except Exception:  # noqa: BLE001 - cache loss must degrade to computation
        logger.warning(
            "Cache read failed for %s; computing directly", key, exc_info=True
        )
        return False, _MISSING


def stampede_safe_get_or_compute(
    key: str,
    compute: Callable[[], T],
    *,
    timeout: int,
    wait_seconds: float = 3.0,
) -> T:
    """Return a cached snapshot while allowing only one concurrent rebuild.

    The lock and every wait are bounded. Cache loss is fail-open because these
    snapshots are an optimization over authoritative database reads, never the
    source of truth.
    """
    if timeout <= 0:
        return compute()

    backend_ok, value = _read(key)
    if not backend_ok:
        return compute()
    if value is not _MISSING:
        return value  # type: ignore[return-value]

    lock_key = f"{key}:rebuild"
    lock_timeout = max(5, min(timeout, 30))
    try:
        owns_lock = cache.add(lock_key, 1, timeout=lock_timeout)
    except Exception:  # noqa: BLE001 - cache loss must not take down the page
        logger.warning(
            "Cache lock failed for %s; computing directly", key, exc_info=True
        )
        return compute()

    if owns_lock:
        try:
            value = compute()
            try:
                cache.set(key, value, timeout=timeout)
            except Exception:  # noqa: BLE001 - the computed response is still valid
                logger.warning("Cache write failed for %s", key, exc_info=True)
            return value
        finally:
            try:
                cache.delete(lock_key)
            except Exception:  # noqa: BLE001 - lock TTL bounds recovery
                logger.warning("Cache lock cleanup failed for %s", key, exc_info=True)

    deadline = time.monotonic() + max(wait_seconds, 0)
    while time.monotonic() < deadline:
        time.sleep(0.05)
        backend_ok, value = _read(key)
        if not backend_ok:
            break
        if value is not _MISSING:
            return value  # type: ignore[return-value]

    # Availability beats an indefinite wait if the rebuilding process died or
    # the backend lost the value. Duplicate work remains bounded by the wait.
    return compute()
