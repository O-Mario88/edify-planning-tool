"""Request-capture middleware for the Staff Time Standard.

Sits after AuthenticationMiddleware so ``request.user`` is resolved.
Records one InteractionEvent per authenticated, non-exempt request —
resolved route pattern and timing only. Telemetry must never break or slow
a request in any user-visible way: capture failures are swallowed
(the PlatformFailureDetectionMiddleware precedent), and the write is a
single narrow INSERT.

Exempt by design: anonymous traffic (nothing to measure), static assets and
the PWA shell (not interaction), health probes (machines), streaming
responses (an open SSE socket is presence, not activity — counting it would
book hours of "active time" for a tab left open), and HEAD/OPTIONS.

Disabled under test by default (settings.INTERACTION_TELEMETRY_ENABLED):
an unconditional extra INSERT per request would shift every
assertNumQueries contract in the suite. Telemetry tests opt in explicitly.
"""

from __future__ import annotations

import logging
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("edify.telemetry")

_EXEMPT_EXACT = ("/sw.js", "/manifest.webmanifest", "/favicon.ico")
# my-plan/day-package is the offline client's background prefetch — §3 of
# the standard excludes background synchronisation from counted time.
_EXEMPT_PREFIXES = (
    "/api/health",
    "/static/",
    "/media/",
    "/my-plan/day-package",
)
_EXEMPT_METHODS = ("HEAD", "OPTIONS")


class InteractionTelemetryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        try:
            self._record(request, response, started)
        except Exception:  # noqa: BLE001 — telemetry must never break a request
            logger.debug("interaction telemetry capture failed", exc_info=True)
        return response

    def _record(self, request, response, started) -> None:
        if not getattr(settings, "INTERACTION_TELEMETRY_ENABLED", False):
            return
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return
        if request.method in _EXEMPT_METHODS:
            return
        path = request.path
        if path in _EXEMPT_EXACT or path.startswith(_EXEMPT_PREFIXES):
            return
        if getattr(response, "streaming", False):
            return
        resolver_match = getattr(request, "resolver_match", None)
        route = getattr(resolver_match, "route", "") or "unresolved"
        from .models import InteractionEvent

        InteractionEvent.objects.create(
            user_id=str(user.id),
            role=getattr(user, "active_role", "") or "",
            occurred_at=timezone.now(),
            method=request.method,
            route=route[:255],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
