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


class _SlidingWindow:
    """Thread-safe sliding window counter."""

    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def hit(self, key: str, *, window_ms: int, limit: int) -> bool:
        """Record a hit; return True if allowed (under limit), False if blocked."""
        now_ms = time.time() * 1000
        cutoff = now_ms - window_ms
        with self._lock:
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
    rate_limit = 10
    rate_window_ms = 60_000


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
