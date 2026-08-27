"""The migrate lock must be held WHILE migrating, and released afterwards.

Both halves matter and fail differently. A lock taken and released before the
work does nothing at all; a lock never released is worse than none, because the
process that holds it goes on to serve traffic and every later deploy waits on
it. So the test probes from inside the migration itself.

`migrate` is not actually run — the point under test is the wrapper, and
re-running migrations inside a test would prove nothing about the lock.
"""

from __future__ import annotations

from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase

from apps.core.management.commands.migrate_locked import MIGRATION_LOCK_ID


def _lock_is_held() -> bool:
    """Ask PostgreSQL whether our advisory lock is currently held.

    A bigint advisory key is split across pg_locks: the high 32 bits land in
    classid and the low 32 in objid.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM pg_locks
            WHERE locktype = 'advisory' AND classid = %s AND objid = %s
            """,
            [MIGRATION_LOCK_ID >> 32, MIGRATION_LOCK_ID & 0xFFFFFFFF],
        )
        return cursor.fetchone()[0] > 0


class MigrateLockedTest(TransactionTestCase):
    def test_the_lock_is_held_during_the_migration_and_released_after(self):
        if connection.vendor != "postgresql":
            self.skipTest("advisory locks are a PostgreSQL feature")

        self.assertFalse(_lock_is_held(), "the lock was already held before the run")

        held_during = {}

        def _probe(self_, *args, **options):
            held_during["value"] = _lock_is_held()

        with mock.patch(
            "django.core.management.commands.migrate.Command.handle", _probe
        ):
            call_command("migrate_locked", verbosity=0)

        self.assertTrue(
            held_during.get("value"),
            "migrations ran without the advisory lock — two containers booting "
            "together would still migrate the same database at once",
        )
        self.assertFalse(
            _lock_is_held(),
            "the advisory lock leaked past the migration; the process holding "
            "it goes on to serve traffic and every later deploy waits on it",
        )

    def test_the_lock_is_released_when_the_migration_raises(self):
        """The failure path is the one that strands a deploy."""
        if connection.vendor != "postgresql":
            self.skipTest("advisory locks are a PostgreSQL feature")

        def _boom(self_, *args, **options):
            raise RuntimeError("migration exploded")

        with mock.patch(
            "django.core.management.commands.migrate.Command.handle", _boom
        ):
            with self.assertRaises(RuntimeError):
                call_command("migrate_locked", verbosity=0)

        self.assertFalse(
            _lock_is_held(),
            "a failed migration kept the lock, so every later deploy blocks",
        )
