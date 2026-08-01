"""
In-memory sliding-window rate limiting.

A faithful port of the NestJS `RateLimitGuard`: a per (route-name + client IP)
sliding window. Applied to `auth/login` (10/min) and `auth/forgot-password`
(4/10min). Single-instance only — multi-instance would need Redis (noted in
the legacy code as the future swap).
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
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
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
        if not _window.hit(key, window_ms=self.rate_window_ms, limit=self.rate_limit):
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


def reset_throttle_state(keys: Iterable[str] = ()) -> None:
    """Test helper: clear the in-memory window (all keys, or a subset)."""
    with _window._lock:  # noqa: SLF001
        if not keys:
            _window._hits.clear()  # noqa: SLF001
        else:
            for k in keys:
                _window._hits.pop(k, None)  # noqa: SLF001


__all__ = [
    "RouteRateThrottle",
    "LoginRateThrottle",
    "ForgotPasswordRateThrottle",
    "reset_throttle_state",
]
