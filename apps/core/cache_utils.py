"""Small cache primitives for expensive, read-only dashboard snapshots."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from django.core.cache import cache

T = TypeVar("T")
_MISSING = object()
logger = logging.getLogger(__name__)
_BUILD_NAMESPACE: str | None = None


def build_namespace() -> str:
    """A short identity for the running build, prefixed onto every snapshot key.

    A deploy replaces the code that computes these snapshots, but it does not
    touch the cache holding yesterday's answers — so for the whole of a TTL
    the new build can serve the old build's figures, and "the change did not
    take effect" is indistinguishable from "the deploy did not happen".

    Several call sites already solved this by hand, with a version segment in
    the key (`impact-dashboard:v3:…`) bumped when the shape changed. That works
    exactly as often as somebody remembers, and it answers a different question:
    the shape may be unchanged while the NUMBERS move, which is what the SSA
    band change of 2026-09-18 did to the Country Director's priority list.

    Namespacing by the build answers it once for every caller: a deploy cannot
    serve a snapshot computed by the build before it. The cost is one rebuild
    per key per deploy, which the stampede lock already bounds.

    Resolved once per process and never raised from: a cache namespace that
    could break a page would be worse than the staleness it prevents.
    """
    global _BUILD_NAMESPACE
    if _BUILD_NAMESPACE is None:
        release = "unknown"
        try:
            from apps.core.build_info import build_info

            release = str(build_info().get("release") or "unknown")
        except Exception:  # noqa: BLE001 - provenance must not break the cache
            logger.warning("Could not read build info for cache namespace")
        _BUILD_NAMESPACE = hashlib.sha256(release.encode()).hexdigest()[:8]
    return _BUILD_NAMESPACE


def _read(key: str) -> tuple[bool, object]:
    try:
        return True, cache.get(key, _MISSING)
    except Exception:  # noqa: BLE001 - cache loss must degrade to computation
        logger.warning(
            "Cache read failed for %s; computing directly", key, exc_info=True
        )
        return False, _MISSING


def cached_role_dashboard(kind: str, user, parts, build):
    """Reuse a role dashboard's computed payload for DASHBOARD_CACHE_SECONDS.

    These pages are the heaviest reads in the product — the Country Director's
    is ~96 queries and over a second even with warm request-scoped caches
    (2026-09-12) — and they are opened repeatedly by the same person as they
    move between tabs. One rebuild serves all of those loads, and the
    stampede lock means a cold cache under concurrent traffic rebuilds once
    rather than once per waiting request, which is what turned a slow page
    into a frozen one on a single worker.

    Keyed by the viewer, because every figure on them is scope-bounded.
    Zero timeout (the test settings) computes directly, so tests always see
    fresh figures.
    """
    timeout = _dashboard_timeout()
    if timeout <= 0:
        return build()
    return stampede_safe_get_or_compute(
        _role_dashboard_key(kind, user, parts), build, timeout=timeout
    )


def role_dashboard_ready(kind: str, user, parts) -> bool:
    """Whether `cached_role_dashboard` would answer now without building."""
    return snapshot_ready(
        _role_dashboard_key(kind, user, parts), timeout=_dashboard_timeout()
    )


def _dashboard_timeout() -> int:
    from django.conf import settings

    return int(getattr(settings, "DASHBOARD_CACHE_SECONDS", 0) or 0)


def _role_dashboard_key(kind: str, user, parts) -> str:
    signature = hashlib.sha256(
        repr(
            (getattr(user, "id", ""), getattr(user, "active_role", ""), parts)
        ).encode()
    ).hexdigest()[:16]
    return f"dashboard:{kind}:{signature}"


def snapshot_ready(key: str, *, timeout: int) -> bool:
    """Whether `stampede_safe_get_or_compute(key, ...)` holds a snapshot now.

    A page uses this to paint its shell first and fetch a slow panel after,
    only when that panel would otherwise be built inside the request (P-2,
    owner-approved 2026-09-25). True when caching is off or the backend cannot
    be read: the build then runs inline, as it always did, so there is
    nothing to gain by deferring it.
    """
    if timeout <= 0:
        return True
    backend_ok, value = _read(snapshot_key(key))
    return not backend_ok or value is not _MISSING


def snapshot_key(key: str) -> str:
    """The key a snapshot is actually stored under: every snapshot belongs to
    the build that computed it — see `build_namespace`."""
    return f"{build_namespace()}:{key}"


def forget_snapshot(key: str) -> None:
    """Drop the snapshot `stampede_safe_get_or_compute(key, ...)` stored.

    A bare ``cache.delete(key)`` misses it, because the stored key carries the
    build namespace: the To-Do queue's "forget" did exactly that and deleted
    nothing, so a decision stayed on the queue until the snapshot expired."""
    try:
        cache.delete(snapshot_key(key))
    except Exception:  # noqa: BLE001 - the cache is an optimisation only
        logger.warning("Cache delete failed for %s", key, exc_info=True)


def stampede_safe_get_or_compute(
    key: str,
    compute: Callable[[], T],
    *,
    timeout: int,
    wait_seconds: float | None = None,
) -> T:
    """Return a cached snapshot while allowing only one concurrent rebuild.

    The lock and every wait are bounded. Cache loss is fail-open because these
    snapshots are an optimization over authoritative database reads, never the
    source of truth.

    A request that finds another one rebuilding waits for that answer while
    the rebuild lock is held — at most `wait_seconds`, which defaults to the
    lock's own lifetime — and computes itself only if the owner finished
    without publishing (its write failed) or the wait ran out.
    """
    if timeout <= 0:
        return compute()

    # Applied here rather than at each call site so a new cached surface
    # cannot forget the build namespace.
    key = snapshot_key(key)

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

    # Waiters used to give up after a flat three seconds and compute
    # themselves. Any snapshot slower than that to build — System Health cold
    # (~6 s), the impact dashboard — then ran once per waiter, all at the same
    # time on one CPU, which is the stampede the lock exists to prevent
    # (performance rescue, 2026-09-23). Waiting for the owner costs nothing
    # and answers sooner than a duplicate build would.
    if wait_seconds is None:
        wait_seconds = lock_timeout
    deadline = time.monotonic() + max(wait_seconds, 0)
    while time.monotonic() < deadline:
        time.sleep(0.05)
        backend_ok, value = _read(key)
        if not backend_ok:
            break
        if value is not _MISSING:
            return value  # type: ignore[return-value]
        if not _lock_held(lock_key):
            # The owner is done but published nothing (its write failed or
            # the value was evicted), or it died and the lock expired: one
            # last look, then build it here.
            backend_ok, value = _read(key)
            if backend_ok and value is not _MISSING:
                return value  # type: ignore[return-value]
            break

    # Availability beats an indefinite wait if the rebuilding process died or
    # the backend lost the value. Duplicate work remains bounded by the wait.
    return compute()


def _lock_held(lock_key: str) -> bool:
    try:
        return cache.get(lock_key) is not None
    except Exception:  # noqa: BLE001 - treat an unreadable lock as released
        return False
