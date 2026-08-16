"""System Health contribution: is the event backbone moving?

Queue depth, oldest-pending age and the dead-letter count are the three
numbers that say whether "durable" is currently true. Every failure state
points at its replay path — a dead event is an exception to work, never a
silent loss.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import OutboxEvent, OutboxStatus


def outbox_health() -> dict:
    now = timezone.now()
    pending = OutboxEvent.objects.filter(status=OutboxStatus.PENDING)
    dead = OutboxEvent.objects.filter(status=OutboxStatus.DEAD).count()
    oldest_pending = (
        pending.order_by("next_attempt_at")
        .values_list("next_attempt_at", flat=True)
        .first()
    )
    oldest_minutes = (
        int((now - oldest_pending).total_seconds() // 60)
        if oldest_pending and oldest_pending < now
        else 0
    )
    checks = []
    if dead:
        checks.append(
            {
                "key": "outbox_dead_letters",
                "severity": "critical",
                "component": "Durable outbox",
                "current_state": f"{dead} dead-lettered event(s)",
                "expected_state": "0 — every event delivered or replayed",
                "last_check": now.isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "Read last_error on the dead events, fix the cause, then "
                    "replay with `manage.py outbox_requeue`."
                ),
                "resolution_link": "/system-health",
            }
        )
    if oldest_minutes > 30:
        checks.append(
            {
                "key": "outbox_backlog_stale",
                "severity": "warning",
                "component": "Durable outbox",
                "current_state": (
                    f"Oldest due event has waited {oldest_minutes} minutes"
                ),
                "expected_state": "Due events drain within minutes",
                "last_check": now.isoformat(),
                "owner": "Admin",
                "recommended_action": (
                    "Check the outbox_drain job in scheduler health — the "
                    "drain may be failing or the queue may need capacity."
                ),
                "resolution_link": "/system-health",
            }
        )
    from apps.realtime.models import ScheduledJobExecution

    drained_recently = ScheduledJobExecution.objects.filter(
        job_name="outbox_drain",
        status="success",
        started_at__gte=now - timedelta(minutes=15),
    ).exists()
    has_traffic = OutboxEvent.objects.exists()
    if has_traffic and not drained_recently:
        checks.append(
            {
                "key": "outbox_drain_stale",
                "severity": "warning",
                "component": "Durable outbox",
                "current_state": "No successful drain in 15 minutes",
                "expected_state": "outbox_drain runs every minute",
                "last_check": now.isoformat(),
                "owner": "Admin",
                "recommended_action": "Check the scheduler service is running.",
                "resolution_link": "/system-health",
            }
        )
    return {
        "checks": checks,
        "summary": {
            "pending": pending.count(),
            "processing": OutboxEvent.objects.filter(
                status=OutboxStatus.PROCESSING
            ).count(),
            "dead": dead,
            "succeeded24h": OutboxEvent.objects.filter(
                status=OutboxStatus.SUCCEEDED,
                succeeded_at__gte=now - timedelta(hours=24),
            ).count(),
            "oldestPendingMinutes": oldest_minutes,
        },
    }
