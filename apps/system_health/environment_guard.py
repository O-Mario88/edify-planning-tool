"""Database environment-stamp guard.

Blocks the two directions of local↔production data contamination:
  1. A production server booting against a database stamped 'local'
     (someone restored a dev dump onto the live server).
  2. A local/dev process running against a database stamped 'production'
     (DATABASE_URL mispointed at the live database — the most destructive
     accident, since a habitual `manage.py seed --demo` would pour demo
     schools into real data).

The guard runs from SystemHealthConfig.ready(). It deliberately SKIPS
management commands that must work before/around the stamp (migrate creates
it; collectstatic runs at Docker build with no database; the stamp command
itself repairs it) and skips silently when the database is unreachable or
the table doesn't exist yet — an absent stamp is a first-boot condition,
not a violation. A PRESENT-but-mismatched stamp is always fatal.
"""

from __future__ import annotations

import sys

# argv[1] values that legitimately run before/around stamp enforcement.
_SKIP_COMMANDS = {
    "migrate",
    "makemigrations",
    "showmigrations",
    "sqlmigrate",
    "collectstatic",
    "check",
    "shell",
    "dbshell",
    "test",
    "stamp_environment",
    "compilemessages",
    "makemessages",
}


class EnvironmentMismatch(Exception):
    pass


def _should_skip() -> bool:
    argv = sys.argv
    if len(argv) > 1 and argv[1] in _SKIP_COMMANDS:
        return True
    # Test runners that don't go through manage.py test
    if any("pytest" in a for a in argv[:2]):
        return True
    return False


def validate_environment(*, force: bool = False) -> str:
    """Compare the database stamp with the process environment.

    Returns a short status string ('ok', 'stamped', 'skipped', 'unavailable').
    Raises EnvironmentMismatch on a stamp/process disagreement.
    """
    if not force and _should_skip():
        return "skipped"

    from django.conf import settings

    import warnings

    try:
        from apps.system_health.models import EnvironmentStamp

        # Deliberate boot-time DB access: failing at process start (not at
        # first request) is the point of this guard. Suppress Django's
        # ready()-query RuntimeWarning for this one query only.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            stamp = EnvironmentStamp.objects.filter(
                id=EnvironmentStamp.SINGLETON_ID
            ).first()
    except Exception:
        # Database unreachable or table not yet migrated (image build, first
        # boot). Nothing to validate against — migrate will write the stamp.
        return "unavailable"

    process_env = getattr(settings, "ENVIRONMENT", "local")

    if stamp is None:
        # First boot after migrate on a pre-guard database: adopt the
        # process identity. (The migration also does this; this is the
        # belt-and-suspenders path for databases migrated before the guard
        # existed.)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=RuntimeWarning)
                EnvironmentStamp.objects.create(
                    id=EnvironmentStamp.SINGLETON_ID,
                    environment=process_env,
                    stamped_by="first-boot",
                )
        except Exception:
            return "unavailable"
        return "stamped"

    if stamp.environment != process_env:
        raise EnvironmentMismatch(
            f"DATABASE/PROCESS ENVIRONMENT MISMATCH: this database is stamped "
            f"'{stamp.environment}' but the process is running as "
            f"'{process_env}'.\n"
            f"- If a dev/local dump was restored onto this server: restore the "
            f"correct production backup instead — local data must never reach "
            f"the live system.\n"
            f"- If your DATABASE_URL points at the wrong database: fix .env.\n"
            f"- If this is a deliberate promotion (e.g. staging→production), "
            f"run:  manage.py stamp_environment --to {process_env}  and type "
            f"the confirmation phrase."
        )
    return "ok"
