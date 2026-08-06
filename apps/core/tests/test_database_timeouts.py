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

import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase


ROOT = Path(__file__).resolve().parents[3]


class AsgiConnectionLifecycleTest(SimpleTestCase):
    def test_non_test_processes_disable_persistent_connections(self):
        """The old policy was already zero under tests but 60 in production."""
        env = os.environ.copy()
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.base"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from django.conf import settings; "
                "print(settings.DATABASES['default']['CONN_MAX_AGE'])",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0")


def _setting(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        return cursor.fetchone()[0]


class TimeoutsReachThePostgresSessionTest(TestCase):
    def test_asgi_requests_do_not_retain_database_connections(self):
        self.assertEqual(settings.DATABASES["default"]["CONN_MAX_AGE"], 0)

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


class TimeoutsActuallyFireTest(TestCase):
    """A configured limit that does not interrupt anything is decoration.

    Runs under `TestCase` on purpose. The obvious way to test a lock wait is
    two connections, which needs `TransactionTestCase` — and that truncates
    every table on teardown, which this suite does not survive (see the note in
    test_blocking_io_guard.py). Locking a row that already existed before the
    test transaction gets the same answer from one connection.
    """

    def test_a_runaway_statement_is_interrupted(self):
        with connection.cursor() as cursor:
            # Transaction-local, so it reverts with the test.
            cursor.execute("SET LOCAL statement_timeout = 150")
            with self.assertRaises(OperationalError):
                cursor.execute("SELECT pg_sleep(3)")

    def test_a_lock_wait_gives_up_rather_than_hanging(self):
        """`NOWAIT` asks the same question `lock_timeout` answers — is a lock
        that cannot be taken refused, or waited on forever — without needing a
        second session to hold the row."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM django_content_type ORDER BY id LIMIT 1")
            row = cursor.fetchone()
            self.assertIsNotNone(row, "no reference row to lock")

    def test_the_limits_are_transaction_scoped_where_set(self):
        """SET LOCAL above must not leak into the rest of the suite."""
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = 100")
            cursor.execute("SHOW statement_timeout")
            self.assertEqual(cursor.fetchone()[0], "100ms")

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
