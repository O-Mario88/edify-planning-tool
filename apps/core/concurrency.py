"""Bound how many requests use the database at once in one web process.

Django's ASGI handler gives every request its own thread (asgiref's
``ThreadSensitiveContext``), so a web process serves sync views concurrently,
and with ``CONN_MAX_AGE=0`` each of those threads opens its own database
connection. Nothing bounded that. At a peak — a Monday morning, a training day
when every CCEO opens My Plan — the number of simultaneous requests is the
number of simultaneous connections, and the managed Postgres cluster refuses
the ones past its limit ("remaining connection slots are reserved"). That is
the failure the 2026-09-12 outage showed from another angle: once the
connection slots are gone, every page on the platform fails at once, not just
the slow ones (docs: DEPLOY.md §3a-ter).

This middleware holds each process to ``WEB_MAX_CONCURRENT_REQUESTS``
requests past it at a time. A request beyond that waits for a slot, in
arrival order, for up to ``WEB_QUEUE_TIMEOUT_SECONDS``; a wait that long is
answered with a 503 and ``Retry-After`` rather than a database error, and the
page retries itself. Waiting holds no connection: Django opens one lazily, on
the first query, which only happens once the request is past this point.

Exempt: the realtime stream (long-lived, polls the bus rather than holding a
query) and the liveness probe (answers without the database, and must keep
answering while the process is busy, or the orchestrator restarts a healthy
process under load). Static files never reach here: WhiteNoise answers them.

Zero disables the guard (the development and test default).
"""

from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.http import HttpResponse, JsonResponse

logger = logging.getLogger("edify.concurrency")

DEFAULT_EXEMPT_PREFIXES = (
    "/api/realtime/",
    "/api/health/live",
    "/static/",
    "/favicon",
)


class DatabaseConcurrencyGuardMiddleware:
    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response
        limit = int(getattr(settings, "WEB_MAX_CONCURRENT_REQUESTS", 0) or 0)
        self.limit = limit
        self.semaphore = threading.BoundedSemaphore(limit) if limit > 0 else None
        self.timeout = float(getattr(settings, "WEB_QUEUE_TIMEOUT_SECONDS", 20) or 20)
        self.exempt = tuple(
            getattr(settings, "WEB_CONCURRENCY_EXEMPT_PREFIXES", DEFAULT_EXEMPT_PREFIXES)
        )
        self._waiting = 0
        self._lock = threading.Lock()

    def __call__(self, request):
        if self.semaphore is None or request.path.startswith(self.exempt):
            return self.get_response(request)
        started = time.monotonic()
        with self._lock:
            self._waiting += 1
        try:
            acquired = self.semaphore.acquire(timeout=self.timeout)
        finally:
            with self._lock:
                self._waiting -= 1
        waited = time.monotonic() - started
        if not acquired:
            logger.warning(
                "request refused after waiting %.1fs for one of %s slots: %s %s",
                waited,
                self.limit,
                request.method,
                request.path,
            )
            return busy_response(request, retry_after=5)
        try:
            response = self.get_response(request)
        finally:
            self.semaphore.release()
        if waited >= 1.0:
            # Visible in the browser's network panel and the access log, so a
            # slow page can be told apart from a page that waited its turn.
            logger.info(
                "request waited %.1fs for a slot: %s %s",
                waited,
                request.method,
                request.path,
            )
            response["X-Edify-Queue-Wait"] = f"{waited:.1f}"
        return response


def busy_response(request, *, retry_after: int) -> HttpResponse:
    """A 503 each kind of client can act on."""
    wants_json = request.path.startswith("/api/") or "application/json" in (
        request.headers.get("Accept") or ""
    )
    if wants_json:
        response = JsonResponse(
            {
                "error": "busy",
                "message": "The platform is busy. Try again in a few seconds.",
            },
            status=503,
        )
    elif request.headers.get("HX-Request") == "true":
        response = HttpResponse(
            '<div class="edify-note" data-tone="warning" role="status">'
            "The platform is busy right now. Try again in a few seconds."
            "</div>",
            status=503,
        )
    else:
        response = HttpResponse(
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f'<meta http-equiv="refresh" content="{retry_after}">'
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Busy · Edify</title></head>"
            '<body style="font-family:system-ui,sans-serif;padding:2rem;color:#1e293b">'
            "<h1 style=\"font-size:1.25rem\">The platform is busy</h1>"
            "<p>Many people are working at once. This page will try again in a "
            "few seconds.</p></body></html>",
            status=503,
        )
    response["Retry-After"] = str(retry_after)
    return response
