"""`migrate`, serialised across processes by a PostgreSQL advisory lock.

The platform runs migrations in a PRE_DEPLOY job precisely so that only one
process migrates. But `RUN_MIGRATIONS` defaults to true in the entrypoint, and
`.do/README.md` records the live web service running with it *on* — which makes
`instance_count: 1` load-bearing, while a second record of the same app reports
two web instances. Two containers booting together then run `migrate` against
one database at the same time, and Django's migration machinery is not written
to survive that: both read the same unapplied plan, both try to apply it, and
the loser fails somewhere mid-plan with the schema half-moved.

The lock removes the dependency on a single instance. It is deliberately
blocking rather than a try-lock: the second container should wait for the first
to finish and then run `migrate` itself, which finds nothing to do and starts
normally. Failing fast instead would turn a routine simultaneous boot into a
crash loop.

Two honest limits. The lock is session-scoped, so it is released if the
connection drops mid-migration — the window narrows but does not close, and the
real answer remains one migration runner (`RUN_MIGRATIONS=false` on the web
service plus the PRE_DEPLOY job). And it only serialises processes reaching the
database this way; a `manage.py migrate` run by hand elsewhere still bypasses
it, which is why the command name says what it does.
"""

from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS, connections

# "EDIFYMIG", signed-bigint safe — same construction as _AUDIT_CHAIN_LOCK_ID
# (apps/audit/services.py) and _RECONCILE_LOCK_ID.
MIGRATION_LOCK_ID = 0x45444946594D4947


class Command(MigrateCommand):
    """Every option `migrate` accepts, because this subclasses it."""

    help = "Apply migrations while holding a cross-process advisory lock."

    def handle(self, *args, **options):
        connection = connections[options.get("database") or DEFAULT_DB_ALIAS]

        # Advisory locks are PostgreSQL's. On any other backend this is a plain
        # migrate rather than a refusal — the guard exists for the deployment,
        # and a developer on SQLite is not the race it protects against.
        if connection.vendor != "postgresql":
            return super().handle(*args, **options)

        verbosity = options.get("verbosity", 1)
        if verbosity:
            self.stdout.write("Waiting for the migration advisory lock…")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [MIGRATION_LOCK_ID])
        if verbosity:
            self.stdout.write("Migration lock held; applying migrations.")

        try:
            return super().handle(*args, **options)
        finally:
            # Released explicitly rather than left to session teardown, so a
            # long-lived process that migrates and then serves does not hold it
            # for its whole life.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [MIGRATION_LOCK_ID])
