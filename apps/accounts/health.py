"""auth_lockout_health() — System Health checks for the unified authentication
lockout policy (Issue 3 of the audit). Wired into apps.system_health.services
.report() as data["authLockout"].

Same check shape as apps.realtime.health.background_automation_health():
key, severity ("ok"/"warning"/"critical"), component, current_state,
expected_state, last_check, owner, recommended_action, resolution_link.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def auth_lockout_health() -> dict:
    checks = []
    now = timezone.now()

    checks.append(_backend_unification_check(now))
    checks.append(_legacy_lock_record_check(now))
    checks.append(_escalated_accounts_check(now))

    return {"checks": checks}


def _backend_unification_check(now) -> dict:
    """Every login surface (web, API, Django admin) must authenticate through
    the ONE backend that enforces AuthenticationLockoutService — if this
    setting ever drifts (e.g. someone appends ModelBackend as a fallback),
    lockout silently stops applying to whichever path picks up the other
    backend."""
    backends = list(getattr(settings, "AUTHENTICATION_BACKENDS", []))
    expected = ["apps.accounts.auth_backend.LockoutEnforcingModelBackend"]
    unified = backends == expected
    return {
        "key": "auth_backend_unified",
        "severity": "ok" if unified else "critical",
        "component": "Authentication Backend",
        "current_state": f"AUTHENTICATION_BACKENDS = {backends}",
        "expected_state": f"AUTHENTICATION_BACKENDS = {expected} (exactly one entry)",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if unified
            else "Restore AUTHENTICATION_BACKENDS to only LockoutEnforcingModelBackend — "
            "any other/additional backend lets some login path bypass lockout enforcement."
        ),
        "resolution_link": "/system-health",
    }


def _legacy_lock_record_check(now) -> dict:
    """Detects accounts whose locked_until is a legacy ~100-year 'permanent
    lock' (the pre-Issue-3 convention) without the new lockout_escalated
    flag set — i.e. a row that means 'requires admin unlock' under the old
    system but wouldn't be recognized as such by the new one. Migration
    0016 fixed every row that existed at migration time; this check catches
    any future recurrence (e.g. a data import or fixture load using the old
    convention)."""
    from .models import User

    cutoff = now + timedelta(days=30)
    inconsistent = User.objects.filter(
        locked_until__gt=cutoff,
        lockout_escalated=False,
        deleted_at__isnull=True,
    )
    count = inconsistent.count()
    sample = list(inconsistent.values_list("email", flat=True)[:5])
    return {
        "key": "legacy_lock_records",
        "severity": "ok" if count == 0 else "critical",
        "component": "Legacy Lock Records",
        "current_state": (
            "No inconsistent legacy lock records found"
            if count == 0
            else f"{count} account(s) with a >30-day locked_until but lockout_escalated=False: "
            f"{', '.join(sample)}{'…' if count > len(sample) else ''}"
        ),
        "expected_state": "Zero rows using the pre-Issue-3 'far-future locked_until' convention",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if count == 0
            else "Run `python manage.py repair_legacy_lock_records` to migrate them to "
            "lockout_escalated=True (the same idempotent logic as migration 0016)."
        ),
        "resolution_link": "/system-health",
    }


def _escalated_accounts_check(now) -> dict:
    """Operational visibility only (not itself a defect) — surfaces accounts
    currently blocked pending an explicit admin unlock, so this doesn't sit
    invisible until a user complains."""
    from .models import User

    escalated = User.objects.filter(
        lockout_escalated=True,
        deleted_at__isnull=True,
    )
    count = escalated.count()
    sample = list(escalated.values_list("email", flat=True)[:5])
    return {
        "key": "escalated_accounts_pending_unlock",
        "severity": "ok" if count == 0 else "warning",
        "component": "Escalated Accounts",
        "current_state": (
            "No accounts currently require an admin unlock"
            if count == 0
            else f"{count} account(s) locked pending admin unlock: "
            f"{', '.join(sample)}{'…' if count > len(sample) else ''}"
        ),
        "expected_state": "Reviewed promptly — each represents a user who cannot log in",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if count == 0
            else "Review each account in Admin > User Management and unlock once identity is verified."
        ),
        "resolution_link": "/admin-panel/users",
    }
