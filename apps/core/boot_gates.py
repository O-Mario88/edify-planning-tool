"""SEC-01 — production boot gates that need the app registry / a live DB
connection (database availability, applied-migration state, collected
static assets), so unlike config/settings/prod.py's import-time checks
(which run before the app registry is ready) these run from the explicit
``production_preflight`` management command after Django has completed app
initialization and before the production server process starts.

Fail-closed: any violation here means the process refuses to start, exactly
like the settings-import-time checks in prod.py.

The scheduler-disabled SEC-01 condition is deliberately NOT a
boot gate here: a web worker cannot reliably tell whether its sibling
scheduler process/container is running at its own boot time without false
positives on a cold deploy (no job has run yet). It's covered instead as a
System Health CRITICAL check (apps.realtime.health.background_automation_
health, wired into apps.system_health.services.report()) — the documented
"health-critical runtime gate" alternative.
"""

from __future__ import annotations

import sys


def verify_or_exit() -> None:
    issues: list[str] = []
    issues += _check_database_available()
    # A dead/unreachable database makes the migration-state check itself
    # unreliable (it would just fail the same connection again) — no point
    # piling on a second, redundant failure message.
    if not issues:
        issues += _check_no_pending_migrations()
    issues += _check_static_assets_collected()

    # Email is a DEGRADATION, not a boot blocker. Refusing to start without a
    # mail provider trades a broken channel for a dead site: the container
    # would not boot at all, taking down Planning, finance and every other
    # workflow to protect invitations and password resets. The condition is
    # still reported here at boot and stays visible as a standing System
    # Health finding (`apps/core/health.py`), so it can never pass silently.
    warnings = _check_email_delivery_configured()
    if warnings:
        sys.stderr.write(
            "Production environment warnings (not blocking boot):\n"
            + "\n".join(warnings)
            + "\n"
        )

    if issues:
        sys.stderr.write(
            "Production environment is not safe:\n" + "\n".join(issues) + "\n"
        )
        raise SystemExit(1)


def _check_database_available() -> list[str]:
    from django.db import connections
    from django.db.utils import OperationalError

    try:
        connections["default"].ensure_connection()
    except OperationalError as exc:
        return [f"Database is unavailable at boot: {exc}"]
    except Exception as exc:  # noqa: BLE001 — any connection failure must fail closed
        return [f"Database connectivity check failed: {exc}"]
    return []


def _check_no_pending_migrations() -> list[str]:
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    try:
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:  # noqa: BLE001 — can't determine migration state -> fail closed
        return [f"Could not determine migration state: {exc}"]
    if plan:
        pending = ", ".join(
            f"{migration.app_label}.{migration.name}" for migration, _backwards in plan
        )
        return [
            "Pending database migrations must be applied before boot "
            f"(run `python manage.py migrate`): {pending}"
        ]
    return []


def _check_static_assets_collected() -> list[str]:
    import os

    from django.conf import settings

    static_root = getattr(settings, "STATIC_ROOT", None)
    if not static_root:
        return ["STATIC_ROOT is not configured — collectstatic has nowhere to write."]
    if not os.path.isdir(static_root) or not os.listdir(static_root):
        return [
            f"Static assets are missing at STATIC_ROOT ({static_root}) — run "
            "`python manage.py collectstatic --noinput` before starting the server."
        ]
    return []


def _check_email_delivery_configured() -> list[str]:
    """Report — but do not block on — a production process that cannot send mail.

    The console provider is a useful local fallback; in production it silently
    strands invitations, password resets, scheduled reports and any account
    enrolled in email MFA. That is a real degradation and it must be loud,
    which is why this is written to stderr at every boot and surfaced as a
    standing System Health finding.

    It is deliberately NOT a boot blocker. An unsendable email leaves one
    channel broken; a container that refuses to start leaves the whole
    platform down. Callers that need a hard gate should read this list
    explicitly rather than relying on `verify_or_exit`.
    """
    from django.conf import settings

    if not getattr(settings, "IS_PRODUCTION", False):
        return []
    provider = str(getattr(settings, "EMAIL_PROVIDER", "")).strip().lower()
    api_key = str(getattr(settings, "RESEND_API_KEY", "")).strip()
    if provider == "resend" and api_key:
        return []
    return [
        "Production email delivery is not configured — set "
        "EMAIL_PROVIDER=resend and a non-empty RESEND_API_KEY before boot."
    ]
