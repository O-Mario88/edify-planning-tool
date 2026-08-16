"""
Per (route-name + client IP) rate limiting for `auth/login` (10/min) and
`auth/forgot-password` (4/10min).

Counted in the shared cache when one is configured, and in a per-process
sliding window when it is not.

That split is the whole point. This was a module-level Python dict, which is
correct at exactly one process and silently wrong at two: each worker keeps its
own counter, so "10 per minute" becomes 10 per minute *per instance* and the
limit quietly weakens in proportion to how far the app has been scaled. Nothing
failed, nothing logged — the number in the settings file simply stopped being
true. Production runs a single Daphne instance today, so the in-process window
was accurate; raising `instance_count` in .do/app.yaml is a one-line change
that would have made it inaccurate with no other signal.

Provisioning Redis now fixes the throttle as well as the cache, together,
instead of fixing the cache and leaving this behind.

Note on what this is and is not: this bounds request *volume* from an address.
The per-account brute-force bound is AuthenticationLockoutService, which counts
in the database under select_for_update and is unaffected by process count.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Iterable

from rest_framework.throttling import SimpleRateThrottle


#: How often to drop buckets that have gone quiet. Cheap relative to the
#: request rate, and the window it sweeps against is the widest any caller has
#: asked for, so a long-window route can never have its history swept early.
_SWEEP_INTERVAL_MS = 60_000


class _SlidingWindow:
    """Thread-safe sliding window counter."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._max_window_ms = 0
        self._last_sweep_ms = 0.0

    def _sweep(self, now_ms: float) -> None:
        """Drop buckets whose every hit has aged out.

        `hit` prunes timestamps *inside* a bucket but never removed the bucket
        itself, and the key is `route:client_ip` — so a long-lived worker
        accumulated one permanent entry per distinct client address. An
        IP-rotating credential-probe run against the login route grew it
        without bound.
        """
        self._last_sweep_ms = now_ms
        cutoff = now_ms - self._max_window_ms
        for key in [
            k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff
        ]:
            del self._hits[key]

    def hit(self, key: str, *, window_ms: int, limit: int) -> bool:
        """Record a hit; return True if allowed (under limit), False if blocked."""
        now_ms = time.time() * 1000
        cutoff = now_ms - window_ms
        with self._lock:
            self._max_window_ms = max(self._max_window_ms, window_ms)
            if now_ms - self._last_sweep_ms > _SWEEP_INTERVAL_MS:
                self._sweep(now_ms)
            bucket = self._hits[key]
            # Drop expired entries.
            self._hits[key] = bucket = [t for t in bucket if t > cutoff]
            if len(bucket) >= limit:
                return False
            bucket.append(now_ms)
            return True


_window = _SlidingWindow()


def _cache_is_shared() -> bool:
    """True when the configured cache is visible to every worker.

    LocMemCache and DummyCache are per-process, so counting in them is no
    better than counting in a module-level dict — and worse, because it would
    look like it had been fixed. Anything else (Redis here) is shared.
    """
    from django.core.cache import cache

    backend = type(cache).__module__.lower()
    return "locmem" not in backend and "dummy" not in backend


def _shared_hit(key: str, *, window_ms: int, limit: int) -> bool:
    """Fixed-window counter in the shared cache.

    Fixed rather than sliding: a sliding window needs read-modify-write on a
    list, which is not atomic across workers and would let simultaneous
    requests both read N-1 and both pass — exactly the race this is meant to
    close. incr() is atomic, so the count is exact. The cost is the standard
    fixed-window boundary burst (up to 2x the limit across two adjacent
    windows), which is the right trade against a limit that does not hold at
    all under concurrency.
    """
    from django.core.cache import cache

    window_s = max(1, window_ms // 1000)
    # Bucketing by window number lets the key expire on its own — no sweep,
    # and no unbounded growth from IP-rotating probes.
    bucket = int(time.time() // window_s)
    cache_key = f"throttle:{key}:{bucket}"
    try:
        cache.add(cache_key, 0, timeout=window_s + 5)
        count = cache.incr(cache_key)
    except ValueError:
        # The key expired between add and incr — treat as the first hit of a
        # fresh window rather than failing the request.
        cache.set(cache_key, 1, timeout=window_s + 5)
        count = 1
    except Exception:  # noqa: BLE001
        # A degraded cache must not lock everyone out of login. Fall back to
        # the in-process window: weaker across workers, but still a limit.
        return _window.hit(key, window_ms=window_ms, limit=limit)
    return count <= limit


def _hit(key: str, *, window_ms: int, limit: int) -> bool:
    if _cache_is_shared():
        return _shared_hit(key, window_ms=window_ms, limit=limit)
    return _window.hit(key, window_ms=window_ms, limit=limit)


class RouteRateThrottle(SimpleRateThrottle):
    """Per (route-name + client IP) sliding-window throttle. Views set
    `rate_name`, `rate_limit`, and `rate_window_ms` as class attributes.

    We do our own in-memory sliding window (parity with the NestJS
    RateLimitGuard), so we bypass SimpleRateThrottle's rate-string parsing.
    """

    scope = "route"
    rate_name: str = "default"
    rate_limit: int = 10
    rate_window_ms: int = 60_000

    def __init__(self):
        # Skip the parent __init__ which calls get_rate() and requires a
        # DEFAULT_THROTTLE_RATES entry. We manage the window ourselves.
        self.throttle = False

    def get_rate(self):  # type: ignore[override]
        return None

    def parse_rate(self, rate):  # type: ignore[override]
        return None, None

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        view_name = getattr(view, "rate_name", self.rate_name)
        return f"{view_name}:{ident}"

    def allow_request(self, request, view):
        # Pull the view's configured limits if present.
        self.rate_name = getattr(view, "rate_name", self.rate_name)
        self.rate_limit = getattr(view, "rate_limit", self.rate_limit)
        self.rate_window_ms = getattr(view, "rate_window_ms", self.rate_window_ms)

        key = self.get_cache_key(request, view)
        if not _hit(key, window_ms=self.rate_window_ms, limit=self.rate_limit):
            self.throttle = True
            return False
        return True

    def wait(self):  # type: ignore[override]
        return self.rate_window_ms // 1000


class LoginRateThrottle(RouteRateThrottle):
    rate_name = "auth.login"
    rate_window_ms = 60_000

    def __init__(self):
        super().__init__()
        from django.conf import settings

        self.rate_limit = getattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 10)


class ForgotPasswordRateThrottle(RouteRateThrottle):
    rate_name = "auth.forgot-password"
    rate_limit = 4
    rate_window_ms = 10 * 60_000


def throttle_by_ip(request, *, name: str, limit: int, window_ms: int = 60_000) -> bool:
    """Per (name + client IP) window for plain Django views. True = allowed.

    DRF views get this through `RouteRateThrottle`; the server-rendered login
    form had no equivalent, so the two doors to the same credential check were
    protected asymmetrically — per-account lockout stopped a brute force
    against one account, but nothing bounded one guess each across many
    accounts from a single address (2026-08 audit, AUD-010).

    Shares the window backing and key shape with the DRF throttles, so the two
    doors count against the same budget rather than granting a second one.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ident = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
    return _hit(f"{name}:{ident}", window_ms=window_ms, limit=limit)


def reset_throttle_state(keys: Iterable[str] = ()) -> None:
    """Test helper: clear the window (all keys, or a subset).

    Clears both backings, because which one is live depends on whether a
    shared cache happens to be reachable — a test that only cleared the
    in-process dict would pass locally and leak state wherever Redis exists.
    """
    with _window._lock:  # noqa: SLF001
        if not keys:
            _window._hits.clear()  # noqa: SLF001
        else:
            for k in keys:
                _window._hits.pop(k, None)  # noqa: SLF001

    if not _cache_is_shared():
        return
    from django.core.cache import cache

    try:
        if not keys:
            cache.clear()
        else:
            # Delete the current and previous bucket for each key: a test that
            # resets mid-window must not be tripped by the count it just made.
            for k in keys:
                for window_s in (60, 600):
                    now_bucket = int(time.time() // window_s)
                    cache.delete_many(
                        [
                            f"throttle:{k}:{now_bucket}",
                            f"throttle:{k}:{now_bucket - 1}",
                        ]
                    )
    except Exception:  # noqa: BLE001 — a test helper must not fail the test
        pass


__all__ = [
    "RouteRateThrottle",
    "LoginRateThrottle",
    "ForgotPasswordRateThrottle",
    "reset_throttle_state",
]
