"""Route performance from the interaction telemetry: which pages are slow.

Production has no APM, so the question "which page is slow for whom, and is it
slow or queued?" had no answer outside a developer's laptop. Every
authenticated request already leaves one privacy-safe ``InteractionEvent``
(route pattern, role, duration); apps.core.request_timing adds the status,
statement count, database time and admission-queue wait to it. This reduces
those rows to per-route percentiles for System Health.

Aggregate only, like the Staff Time Standard report beside it: routes and
roles, never people or records.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Aggregate, Avg, Count, FloatField, Q
from django.utils import timezone

from .models import InteractionEvent

#: Release gate from the performance rescue brief (§7): a complex page's p95
#: must stay under 1.5 s; anything slower than this deserves a line on
#: System Health. Queueing above a second means the worker was saturated.
SLOW_ROUTE_P95_MS = 3000
QUEUE_P95_WARNING_MS = 1000
SERVER_ERROR_RATE_WARNING_PCT = 1.0


class Percentile(Aggregate):
    """PostgreSQL ``percentile_cont(p) WITHIN GROUP (ORDER BY expr)``."""

    function = "percentile_cont"
    template = "%(function)s(%(fraction)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, fraction: float, **extra):
        fraction = float(fraction)
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be between 0 and 1")
        super().__init__(expression, fraction=repr(fraction), **extra)


def route_performance(
    *, window_hours: int = 24, limit: int = 15, min_requests: int = 5
) -> dict:
    """The slowest routes by p95 over the window, with where the time went."""
    since = timezone.now() - timedelta(hours=window_hours)
    events = InteractionEvent.objects.filter(occurred_at__gte=since)
    totals = events.aggregate(
        requests=Count("id"),
        server_errors=Count("id", filter=Q(status_code__gte=500)),
        busy=Count("id", filter=Q(status_code=503)),
        p95=Percentile("duration_ms", 0.95),
        queue_p95=Percentile("queue_ms", 0.95),
    )
    rows = (
        events.values("method", "route")
        .annotate(
            requests=Count("id"),
            p50=Percentile("duration_ms", 0.5),
            p95=Percentile("duration_ms", 0.95),
            p99=Percentile("duration_ms", 0.99),
            db_p95=Percentile("db_ms", 0.95),
            queue_p95=Percentile("queue_ms", 0.95),
            queries=Avg("query_count"),
            server_errors=Count("id", filter=Q(status_code__gte=500)),
        )
        .filter(requests__gte=min_requests)
        .order_by("-p95")[:limit]
    )
    routes = [
        {
            "method": row["method"],
            "route": row["route"],
            "requests": row["requests"],
            "p50_ms": round(row["p50"] or 0),
            "p95_ms": round(row["p95"] or 0),
            "p99_ms": round(row["p99"] or 0),
            "db_p95_ms": round(row["db_p95"] or 0),
            "queue_p95_ms": round(row["queue_p95"] or 0),
            "mean_queries": round(row["queries"] or 0),
            "server_errors": row["server_errors"],
        }
        for row in rows
    ]
    requests = totals["requests"] or 0
    return {
        "window_hours": window_hours,
        "requests": requests,
        "p95_ms": round(totals["p95"] or 0),
        "queue_p95_ms": round(totals["queue_p95"] or 0),
        "server_errors": totals["server_errors"] or 0,
        "busy_503": totals["busy"] or 0,
        "server_error_rate_pct": round(
            (totals["server_errors"] or 0) / requests * 100, 2
        )
        if requests
        else 0.0,
        "routes": routes,
    }


def route_performance_health(*, window_hours: int = 24) -> dict:
    """System Health contribution: the report plus the checks an admin acts on."""
    report = route_performance(window_hours=window_hours)
    now = timezone.now().isoformat()
    checks = []
    slow = [r for r in report["routes"] if r["p95_ms"] >= SLOW_ROUTE_P95_MS]
    if slow:
        worst = slow[0]
        checks.append(
            {
                "key": "route_performance_slow_routes",
                "severity": "warning",
                "component": "Route performance",
                "current_state": (
                    f"{len(slow)} route(s) with p95 ≥ {SLOW_ROUTE_P95_MS} ms; "
                    f"slowest {worst['method']} {worst['route']} at "
                    f"{worst['p95_ms']} ms p95"
                ),
                "expected_state": "Every route p95 under the release budget",
                "last_check": now,
                "owner": "Admin",
                "recommended_action": (
                    "Compare db and queue time for the route below: high db "
                    "time is a query to optimise, high queue time is a "
                    "saturated worker."
                ),
                "resolution_link": "/system-health",
            }
        )
    if report["queue_p95_ms"] >= QUEUE_P95_WARNING_MS:
        checks.append(
            {
                "key": "route_performance_queueing",
                "severity": "warning",
                "component": "Worker saturation",
                "current_state": (
                    f"p95 wait for a database slot is {report['queue_p95_ms']} ms "
                    f"({report['busy_503']} requests refused as busy)"
                ),
                "expected_state": "Requests start immediately",
                "last_check": now,
                "owner": "Admin",
                "recommended_action": (
                    "The web tier is saturated: pages are waiting behind other "
                    "pages, not running slowly. Reduce per-request cost or add "
                    "web capacity (docs/performance-rescue-2026-09-23.md)."
                ),
                "resolution_link": "/system-health",
            }
        )
    if report["server_error_rate_pct"] >= SERVER_ERROR_RATE_WARNING_PCT:
        checks.append(
            {
                "key": "route_performance_server_errors",
                "severity": "critical",
                "component": "Server errors",
                "current_state": (
                    f"{report['server_error_rate_pct']}% of requests returned 5xx "
                    f"in the last {window_hours} h"
                ),
                "expected_state": f"Below {SERVER_ERROR_RATE_WARNING_PCT}%",
                "last_check": now,
                "owner": "Admin",
                "recommended_action": "Open Admin Ops incidents for the failing routes.",
                "resolution_link": "/admin-ops/incidents",
            }
        )
    return {"checks": checks, "report": report}
