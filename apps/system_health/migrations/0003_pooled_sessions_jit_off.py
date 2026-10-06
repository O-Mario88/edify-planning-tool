"""Pooled sessions run with JIT off, as direct ones already do.

``config/settings/base.py`` sends ``-c jit=off`` on every direct connection, for
the reason recorded there (one lending KPI: 4.8 s with JIT, 76 ms without). The
web service connects through PgBouncer, which refuses startup options, so its
sessions take the role's default instead — and on the live cluster that default
had never been set: ``/api/health/ready`` answered ``"db_jit": "on"`` and
``"status": "degraded"`` (audit, 2026-10-05).

The role is whichever one runs the migration, which in production is the only
role there is, and the setting is scoped to this database. It can only make a
session match what the settings already ask for. A role that may not change its
own default is told so and the migration carries on: readiness goes on
reporting the truth either way, and one setting is not worth a failed deploy.
"""

from django.db import migrations

SET_JIT_OFF = """
DO $$
BEGIN
  EXECUTE format(
    'ALTER ROLE %I IN DATABASE %I SET jit = %L',
    current_user, current_database(), 'off'
  );
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'jit default left as it is for role %: insufficient privilege', current_user;
END
$$;
"""

RESET_JIT = """
DO $$
BEGIN
  EXECUTE format(
    'ALTER ROLE %I IN DATABASE %I RESET jit',
    current_user, current_database()
  );
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'jit default left as it is for role %: insufficient privilege', current_user;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("system_health", "0002_stamp_environment"),
    ]

    operations = [
        migrations.RunSQL(SET_JIT_OFF, RESET_JIT),
    ]
