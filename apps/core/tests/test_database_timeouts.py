"""Three ways a database session can wait forever, and the ceilings on each.

Postgres defaults `statement_timeout`, `lock_timeout` and
`idle_in_transaction_session_timeout` to zero, which means no limit. Each of
those defaults turns a local problem into a shared one:

  A query with a bad plan runs until somebody notices, holding a connection out
  of a small pool the whole time — so one slow page degrades every page.

  A request waiting on a locked row waits indefinitely. Postgres detects and
  breaks true deadlocks; ordinary contention is not a deadlock and nothing
  breaks it, so the request simply never answers.

  A worker that wedges mid-transaction holds its locks and its snapshot until
  the process dies, and autovacuum cannot clean up behind it for as long as it
  sits there.

These are asserted against the live session rather than against the settings
dict, because the failure that matters is the setting being present and not
reaching Postgres — a `DATABASE_URL` carrying `?schema=` already writes to the
same `OPTIONS["options"]` string, and an assignment there instead of an append
would drop these silently.
"""

from __future__ import annotations

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.test import TestCase, TransactionTestCase


def _setting(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return cursor.fetchone()[0]


class TimeoutsReachThePostgresSessionTest(TestCase):
    def test_a_statement_cannot_run_forever(self):
        self.assertNotEqual(_setting("statement_timeout"), "0")

    def test_a_lock_wait_cannot_last_forever(self):
        self.assertNotEqual(_setting("lock_timeout"), "0")

    def test_the_search_path_survived(self):
        """The regression this guards: `OPTIONS["options"]` is where a
        `?schema=` in DATABASE_URL puts the search_path. Assigning the timeouts
        rather than appending them would point the whole application at the
        wrong schema, which is not the kind of thing that fails loudly."""
        configured = settings.DATABASES["default"]["OPTIONS"].get("options", "")
        if "search_path" in configured:
            self.assertIn("statement_timeout", configured)
            self.assertNotEqual(_setting("search_path"), "")


class TimeoutsActuallyFireTest(TransactionTestCase):
    """A configured limit that does not interrupt anything is decoration."""

    def test_a_runaway_statement_is_interrupted(self):
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = 150")
            with self.assertRaises(OperationalError):
                cursor.execute("SELECT pg_sleep(3)")
        connection.close()

    def test_a_lock_wait_gives_up_rather_than_hanging(self):
        """Two sessions, one row. The second must be refused, not parked."""
        from django.contrib.auth import get_user_model
        from django.db import connections

        from apps.core.rbac import EdifyRole

        User = get_user_model()
        user = User.objects.create_user(
            email="locktimeout@edify.test",
            password="password123",
            name="Lock",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )

        other = connections.create_connection("default")
        try:
            with transaction.atomic():
                # Hold the row.
                User.objects.select_for_update().get(pk=user.pk)

                with other.cursor() as cursor:
                    cursor.execute("SET lock_timeout = 200")
                    with self.assertRaises(Exception) as caught:
                        cursor.execute(
                            'SELECT 1 FROM "user" WHERE id = %s FOR UPDATE',
                            [user.pk],
                        )
            self.assertIn("lock", str(caught.exception).lower())
        finally:
            other.close()

    def test_an_abandoned_transaction_is_reaped(self):
        """Only meaningful outside tests, where the harness deliberately holds
        a transaction open for the length of each test — so this asserts the
        production value rather than trying to trip it here."""
        configured = settings.DATABASES["default"]["OPTIONS"]["options"]
        self.assertIn("idle_in_transaction_session_timeout", configured)


class TheCeilingsAreCeilingsTest(TestCase):
    """Numbers loose enough to be pathology-only, tight enough to be a limit.

    A statement timeout in the same range as a normal page would turn a slow
    afternoon into errors; one measured in minutes would not save the pool.
    """

    def test_the_statement_ceiling_is_in_a_sane_range(self):
        seconds = _seconds(_setting("statement_timeout"))
        self.assertGreaterEqual(seconds, 10)
        self.assertLessEqual(seconds, 300)

    def test_the_lock_ceiling_is_shorter_than_the_statement_ceiling(self):
        """Waiting on a lock is never progress. It should give up first, and
        say so, rather than being cut off later by the statement limit with a
        less specific error."""
        self.assertLess(
            _seconds(_setting("lock_timeout")),
            _seconds(_setting("statement_timeout")),
        )


def _seconds(value: str) -> float:
    value = value.strip()
    if value.endswith("ms"):
        return float(value[:-2]) / 1000
    if value.endswith("min"):
        return float(value[:-3]) * 60
    if value.endswith("s"):
        return float(value[:-1])
    return float(value) / 1000
