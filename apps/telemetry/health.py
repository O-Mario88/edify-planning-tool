"""System Health contribution: the Staff Time Standard report + liveness.

Returns the standard ``{"checks": [...]}`` shape beside the aggregate
report payload. The one integrity check here is about the INSTRUMENT
(is telemetry actually recording?), never about people.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import InteractionDay, InteractionEvent
from .services import interaction_report


def interaction_telemetry_health(*, window_days: int = 14) -> dict:
    report = interaction_report(window_days=window_days)
    checks = []
    enabled = bool(getattr(settings, "INTERACTION_TELEMETRY_ENABLED", False))
    recent_events = InteractionEvent.objects.filter(
        occurred_at__gte=timezone.now() - timedelta(hours=24)
    ).exists()
    rollup_current = InteractionDay.objects.filter(
        day__gte=timezone.localdate() - timedelta(days=2)
    ).exists()
    if not enabled:
        checks.append(
            {
                "key": "interaction_telemetry_disabled",
                "severity": "warning",
                "component": "Interaction telemetry",
                "current_state": "Capture disabled",
                "expected_state": "INTERACTION_TELEMETRY_ENABLED=1 in production",
                "last_check": timezone.now().isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "The Staff Time Standard cannot be measured while capture "
                    "is off. Enable the flag."
                ),
                "resolution_link": "/system-health",
            }
        )
    elif not recent_events:
        checks.append(
            {
                "key": "interaction_telemetry_silent",
                "severity": "warning",
                "component": "Interaction telemetry",
                "current_state": "No events recorded in 24h",
                "expected_state": "Continuous capture on authenticated traffic",
                "last_check": timezone.now().isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "Capture is enabled but silent — check the middleware is "
                    "installed and the application is receiving traffic."
                ),
                "resolution_link": "/system-health",
            }
        )
    if enabled and recent_events and not rollup_current:
        checks.append(
            {
                "key": "interaction_rollup_stale",
                "severity": "warning",
                "component": "Interaction telemetry",
                "current_state": "Daily rollup has not run in 2+ days",
                "expected_state": "interaction_day rows current to yesterday",
                "last_check": timezone.now().isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "Check the interaction_rollup scheduled job in the "
                    "scheduler health panel."
                ),
                "resolution_link": "/system-health",
            }
        )
    return {"checks": checks, "report": report, "enabled": enabled}
