"""SEC-01 — production boot gates that need the app registry / a live DB
connection (database availability, applied-migration state, collected
static assets), so unlike config/settings/prod.py's import-time checks
(which run before the app registry is ready) these run from
apps.core.apps.CoreConfig.ready() instead — once, in every production
process that boots the Django app (gunicorn/daphne workers), but skipped
for management commands that legitimately manage the DB schema themselves
(migrate/makemigrations) or only introspect it.

Fail-closed: any violation here means the process refuses to start, exactly
like the settings-import-time checks in prod.py.

The fourth SEC-01 condition — "scheduler disabled" — is deliberately NOT a
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
