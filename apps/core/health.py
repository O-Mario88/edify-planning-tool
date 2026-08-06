"""platform_health() — the infrastructure conditions that fail quietly.

Wired into apps.system_health.services.report() as data["platform"]. Same check
shape as apps.accounts.health and apps.realtime.health: key, severity,
component, current_state, expected_state, last_check, owner,
recommended_action, resolution_link.

Everything here shares one property: the application keeps serving pages while
it is wrong. Nothing 500s, no alert fires from the request path, and the first
symptom is somebody unable to do their job for a reason they cannot see.

  Migration drift      An image whose code expects a table the database has
                       not got. Most pages carry on working; the ones that
                       touch the new column fail, one at a time, as people
                       reach them.

  Delivery channels    A deploy that forgets RESEND_API_KEY silently falls
                       back to the console mailer. Invitations and password
                       resets stop arriving. Worse since two-step verification
                       shipped: every enrolled account is locked out, because
                       the code is only ever sent, never shown.

  Cache reachability   Redis unreachable degrades to a per-process LocMemCache,
                       which works — differently — on each worker. Sessions
                       still function because SESSION_ENGINE follows the same
                       signal, but every cached figure is now per-worker, so
                       the same page can show two different numbers depending
                       on which worker answers.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone


def platform_health() -> dict:
    now = timezone.now()
    return {
        "checks": [
            _migration_drift_check(now),
            _email_delivery_check(now),
            _sms_delivery_check(now),
            _cache_backend_check(now),
        ]
    }


def _migration_drift_check(now) -> dict:
    """Migrations this code expects but the database has not applied.

    Asked of the migration loader rather than of `showmigrations`, so it is the
    running process's own view — which is the one that matters. A deploy that
    skipped its migrate step looks entirely healthy until someone opens the
    page that uses the new column.
    """
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        pending = executor.migration_plan(targets)
        names = [f"{migration.app_label}.{migration.name}" for migration, _ in pending]
    except Exception as exc:  # noqa: BLE001 — the health page must render
        return {
            "key": "migration_drift",
            "severity": "warning",
            "component": "Database Migrations",
            "current_state": f"Could not be determined: {exc}",
            "expected_state": "Every migration in this build is applied",
            "last_check": now,
            "owner": "Platform/Ops",
            "recommended_action": (
                "Run 'python manage.py showmigrations' against this database by "
                "hand — this check could not answer, which is not the same as a "
                "clean answer."
            ),
            "resolution_link": "/system-health",
        }

    clean = not names
    return {
        "key": "migration_drift",
        "severity": "ok" if clean else "critical",
        "component": "Database Migrations",
        "current_state": (
            "All migrations applied"
            if clean
            else f"{len(names)} unapplied: {', '.join(names[:5])}"
            + ("…" if len(names) > 5 else "")
        ),
        "expected_state": "Every migration in this build is applied",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if clean
            else "Run 'python manage.py migrate'. Until then this build is "
            "serving pages against a schema it was not written for, and the "
            "failures will arrive one page at a time."
        ),
        "resolution_link": "/system-health",
    }


def _email_delivery_check(now) -> dict:
    """Whether email can actually reach anyone.

    Only a defect in production. Locally the console provider is the point.
    """
    from apps.core.email import mailer

    configured = mailer.is_configured
    in_production = bool(getattr(settings, "IS_PRODUCTION", False))
    broken = in_production and not configured

    mfa_users = 0
    try:
        from apps.accounts.models import User

        mfa_users = User.objects.filter(
            mfa_enabled=True, deleted_at__isnull=True
        ).count()
    except Exception:  # noqa: BLE001
        pass

    consequence = (
        "Invitations and password resets are not being delivered"
        if not mfa_users
        else f"Invitations and password resets are not being delivered, and "
        f"{mfa_users} account(s) with two-step verification cannot sign in at "
        "all — the code is only ever sent, never shown."
    )
    return {
        "key": "email_delivery_configured",
        "severity": "critical" if broken else "ok",
        "component": "Email Delivery",
        "current_state": (
            f"provider={mailer.provider}" + (f" — {consequence}" if broken else "")
        ),
        "expected_state": "A real provider in production (EMAIL_PROVIDER=resend + RESEND_API_KEY)",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if not broken
            else "Set EMAIL_PROVIDER=resend and RESEND_API_KEY. The console "
            "provider is the silent fallback, so nothing has been erroring."
        ),
        "resolution_link": "/system-health",
    }


def _sms_delivery_check(now) -> dict:
    """SMS is optional, so this is only ever a warning — unless somebody has
    enrolled onto it, in which case those accounts have no way in."""
    from apps.core.sms import sms

    configured = sms.is_configured
    enrolled = 0
    try:
        from apps.accounts.models import User

        enrolled = User.objects.filter(
            mfa_enabled=True, mfa_channel="sms", deleted_at__isnull=True
        ).count()
    except Exception:  # noqa: BLE001
        pass

    stranded = enrolled and not configured
    if stranded:
        severity = "critical"
    elif configured:
        severity = "ok"
    else:
        severity = "warning"

    return {
        "key": "sms_delivery_configured",
        "severity": severity,
        "component": "SMS Delivery",
        "current_state": (
            f"provider={sms.provider}, {enrolled} account(s) enrolled on SMS"
        ),
        "expected_state": ("Configured, or no account enrolled on the SMS channel"),
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else (
                f"{enrolled} account(s) expect their sign-in code by text and "
                "no provider can send one. Configure SMS_PROVIDER, or move "
                "those accounts to email."
                if stranded
                else "Optional. Two-step verification falls back to email, so "
                "nobody is stranded; SMS simply is not offered."
            )
        ),
        "resolution_link": "/system-health",
    }


def _cache_backend_check(now) -> dict:
    """Reachable, and shared rather than per-process.

    A read-back rather than a ping: a cache that accepts writes and returns
    nothing is the failure that matters, and it does not announce itself.
    """
    backend = settings.CACHES["default"]["BACKEND"]
    shared = "locmem" not in backend.lower()

    key = "system-health:cache-probe"
    try:
        cache.set(key, "ok", timeout=30)
        reachable = cache.get(key) == "ok"
        cache.delete(key)
    except Exception:  # noqa: BLE001
        reachable = False

    if not reachable:
        severity = "critical"
    elif not shared:
        severity = "warning" if getattr(settings, "IS_PRODUCTION", False) else "ok"
    else:
        severity = "ok"

    return {
        "key": "cache_backend",
        "severity": severity,
        "component": "Cache",
        "current_state": (
            f"{backend.rsplit('.', 1)[-1]}, "
            + ("read-back OK" if reachable else "READ-BACK FAILED")
        ),
        "expected_state": "A reachable cache, shared across workers in production",
        "last_check": now,
        "owner": "Platform/Ops",
        "recommended_action": (
            "OK"
            if severity == "ok"
            else (
                "The cache accepted a write and did not return it. Everything "
                "cached is being recomputed on every request."
                if not reachable
                else "Redis was unreachable at boot so the cache fell back to "
                "LocMemCache, which is per-process. Cached figures now differ "
                "between workers, so the same page can show two answers — and "
                "the login rate limit is counted per worker, so it is only the "
                "configured number per minute while this app runs a single "
                "instance. Provision Redis before raising instance_count."
            )
        ),
        "resolution_link": "/system-health",
    }


__all__ = ["platform_health"]
