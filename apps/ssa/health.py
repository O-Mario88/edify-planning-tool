"""unmatched_ssa_health() — System Health checks for the /ssa/unmatched
queue (Issue 5 of the audit: size/performance visibility). Wired into
apps.system_health.services.report() as data["unmatchedSsa"].

Same check shape as apps.realtime.health.background_automation_health()/
apps.accounts.health.auth_lockout_health(): key, severity
("ok"/"warning"/"critical"), component, current_state, expected_state,
last_check, owner, recommended_action, resolution_link.
"""

from __future__ import annotations

from django.utils import timezone

QUEUE_WARNING_THRESHOLD = 200
QUEUE_CRITICAL_THRESHOLD = 1000
STALE_DAYS_WARNING = 30


def unmatched_ssa_health() -> dict:
    checks = []
    now = timezone.now()

    checks.append(_queue_size_check(now))
    checks.append(_stale_records_check(now))
    checks.append(_missing_suggestions_check(now))

    return {"checks": checks}


def _queue_size_check(now) -> dict:
    from apps.schools.models import UnmatchedSSARecord

    count = UnmatchedSSARecord.objects.filter(status__in=["pending", "hold"]).count()
    if count >= QUEUE_CRITICAL_THRESHOLD:
        severity = "critical"
    elif count >= QUEUE_WARNING_THRESHOLD:
        severity = "warning"
    else:
        severity = "ok"
    return {
        "key": "unmatched_queue_size",
        "severity": severity,
        "component": "Unmatched SSA Queue",
        "current_state": f"{count} record(s) pending/hold",
        "expected_state": f"Below {QUEUE_WARNING_THRESHOLD} — a growing queue means uploads "
        "keep referencing School IDs that aren't in the directory",
        "last_check": now,
        "owner": "IA/Admin",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else "Review /ssa/unmatched — link, create, or ignore the backlog before it grows further."
        ),
        "resolution_link": "/ssa/unmatched",
    }


def _stale_records_check(now) -> dict:
    from datetime import timedelta

    from apps.schools.models import UnmatchedSSARecord

    cutoff = now - timedelta(days=STALE_DAYS_WARNING)
    stale = UnmatchedSSARecord.objects.filter(
        status__in=["pending", "hold"],
        created_at__lt=cutoff,
    )
    count = stale.count()
    return {
        "key": "unmatched_stale_records",
        "severity": "ok" if count == 0 else "warning",
        "component": "Unmatched SSA Queue",
        "current_state": (
            f"No record older than {STALE_DAYS_WARNING} days"
            if count == 0
            else f"{count} record(s) unresolved for over {STALE_DAYS_WARNING} days"
        ),
        "expected_state": f"Every record resolved within {STALE_DAYS_WARNING} days",
        "last_check": now,
        "owner": "IA/Admin",
        "recommended_action": (
            "OK"
            if count == 0
            else "Review /ssa/unmatched?date_to= to find and resolve the oldest entries."
        ),
        "resolution_link": "/ssa/unmatched",
    }


def _missing_suggestions_check(now) -> dict:
    from apps.schools.models import UnmatchedSSARecord

    no_suggestion = UnmatchedSSARecord.objects.filter(
        status__in=["pending", "hold"],
        suggested_school__isnull=True,
    ).count()
    return {
        "key": "unmatched_missing_suggestions",
        "severity": "ok" if no_suggestion == 0 else "warning",
        "component": "Unmatched SSA Queue",
        "current_state": (
            "Every pending/hold record has a suggested match"
            if no_suggestion == 0
            else f"{no_suggestion} record(s) with no suggested match — fully manual review required"
        ),
        "expected_state": "Most rows carry a fuzzy-match suggestion (School Name/District were "
        "in the upload, or a trigram match was found above threshold)",
        "last_check": now,
        "owner": "IA/Admin",
        "recommended_action": (
            "OK"
            if no_suggestion == 0
            else "Run `python manage.py recompute_unmatched_ssa_suggestions` if these predate the "
            "write-time suggestion computation, otherwise review manually."
        ),
        "resolution_link": "/ssa/unmatched",
    }
