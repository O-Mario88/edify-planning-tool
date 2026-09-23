"""Where a request's time went, in production, without an APM.

The live deployment has no tracing product and no paid log destination
(.do/README.md), so a slow page and a page that waited its turn behind a busy
worker looked identical: both were just "slow". This middleware measures every
request as three parts —

* ``queue``: time spent waiting for a database admission slot
  (apps.core.concurrency sets it on the request);
* ``db``: time inside SQL on the default connection, and how many statements;
* ``app``: everything else — Python, templates, serialisation.

and reports them two ways:

* a ``Server-Timing`` header on responses to signed-in users, which every
  browser's network panel draws as a breakdown bar;
* one structured ``edify.perf`` log line for any request slower than
  ``SLOW_REQUEST_MS`` or heavier than ``SLOW_REQUEST_QUERIES`` statements.

The log line carries the resolved route PATTERN, never the concrete path, query
string, user, school or payload — the same privacy rule as the interaction
telemetry (apps.telemetry.models). The probe is also left on the request so the
telemetry middleware can persist the same numbers per route.
"""

from __future__ import annotations

import json
import logging
import os
import time

from django.conf import settings
from django.db import connection

logger = logging.getLogger("edify.perf")


class QueryProbe:
    """``connection.execute_wrapper`` callable: counts statements and time."""

    __slots__ = ("count", "seconds")

    def __init__(self):
        self.count = 0
        self.seconds = 0.0

    def __call__(self, execute, sql, params, many, context):
        started = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.seconds += time.perf_counter() - started
            self.count += 1

    @property
    def ms(self) -> float:
        return self.seconds * 1000


def _release() -> str:
    return (os.environ.get("RELEASE") or os.environ.get("GIT_COMMIT") or "")[:12]


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.slow_ms = int(getattr(settings, "SLOW_REQUEST_MS", 1500))
        self.slow_queries = int(getattr(settings, "SLOW_REQUEST_QUERIES", 150))
        self.release = _release()

    def __call__(self, request):
        started = time.perf_counter()
        probe = QueryProbe()
        request.edify_query_probe = probe
        with connection.execute_wrapper(probe):
            response = self.get_response(request)
        total_ms = (time.perf_counter() - started) * 1000
        queue_ms = float(getattr(request, "edify_queue_wait_ms", 0.0) or 0.0)
        db_ms = probe.ms
        app_ms = max(0.0, total_ms - db_ms - queue_ms)

        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False) and not response.has_header(
            "Server-Timing"
        ):
            response["Server-Timing"] = (
                f"app;dur={app_ms:.0f}, "
                f'db;dur={db_ms:.0f};desc="{probe.count} queries", '
                f"queue;dur={queue_ms:.0f}, total;dur={total_ms:.0f}"
            )

        if total_ms >= self.slow_ms or probe.count >= self.slow_queries:
            resolver_match = getattr(request, "resolver_match", None)
            logger.warning(
                "slow_request %s",
                json.dumps(
                    {
                        "route": (getattr(resolver_match, "route", "") or "unresolved")[
                            :200
                        ],
                        "method": request.method,
                        "status": response.status_code,
                        "role": getattr(user, "active_role", "") or "",
                        "htmx": request.headers.get("HX-Request") == "true",
                        "total_ms": round(total_ms),
                        "app_ms": round(app_ms),
                        "db_ms": round(db_ms),
                        "queue_ms": round(queue_ms),
                        "queries": probe.count,
                        "bytes": 0
                        if getattr(response, "streaming", False)
                        else len(response.content),
                        "release": self.release,
                        "cid": getattr(request, "correlation_id", ""),
                    },
                    sort_keys=True,
                ),
            )
        return response
