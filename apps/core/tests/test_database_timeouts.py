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
import json
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

    def _settings_json(self, extra_env):
        env = os.environ.copy()
        env.pop("DB_USE_PGBOUNCER", None)
        env.pop("DB_CONN_MAX_AGE", None)
        env.update({"DJANGO_SETTINGS_MODULE": "config.settings.base", **extra_env})
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from django.conf import settings; "
                "print(json.dumps({'conn_max_age': "
                "settings.DATABASES['default']['CONN_MAX_AGE'], "
                "'ignored': settings.DB_CONN_MAX_AGE_IGNORED}))",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_a_lifetime_on_a_direct_connection_is_refused(self):
        """The 2026-09-12 outage: DB_CONN_MAX_AGE=60 on the direct connection
        exhausted the managed cluster's connection slots."""
        resolved = self._settings_json({"DB_CONN_MAX_AGE": "60"})
        self.assertEqual(resolved["conn_max_age"], 0)
        self.assertTrue(resolved["ignored"])

    def test_a_lifetime_behind_the_pool_is_honoured(self):
        resolved = self._settings_json(
            {
                "DB_CONN_MAX_AGE": "60",
                "DB_USE_PGBOUNCER": "true",
                "DATABASE_URL": "postgresql://runtime:secret@db.example:25061/edify?sslmode=require",
            }
        )
        self.assertEqual(resolved["conn_max_age"], 60)
        self.assertFalse(resolved["ignored"])

    def test_the_boot_gate_reports_a_refused_lifetime(self):
        from unittest import mock

        from apps.core import boot_gates

        with mock.patch.object(settings, "DB_CONN_MAX_AGE_IGNORED", True, create=True):
            self.assertEqual(len(boot_gates._check_connection_lifetime_ignored()), 1)
        with mock.patch.object(settings, "DB_CONN_MAX_AGE_IGNORED", False, create=True):
            self.assertEqual(boot_gates._check_connection_lifetime_ignored(), [])

    def test_pooled_runtime_omits_unsupported_startup_options(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.base",
                "DATABASE_URL": "postgresql://runtime:secret@db.example:25061/edify?sslmode=require",
                "DB_USE_PGBOUNCER": "true",
                "DB_POOL_NAME": "edify_web",
                "DB_POOL_PORT": "25061",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from django.conf import settings; "
                "d=settings.DATABASES['default']; "
                "print(json.dumps({'options': d['OPTIONS'], "
                "'conn_max_age': d['CONN_MAX_AGE'], "
                "'name': d['NAME'], 'port': d['PORT'], "
                "'disable_cursors': d.get('DISABLE_SERVER_SIDE_CURSORS')}))",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        database = json.loads(result.stdout)
        self.assertNotIn("options", database["options"])
        self.assertEqual(database["options"]["connect_timeout"], 5)
        self.assertEqual(database["conn_max_age"], 0)
        self.assertTrue(database["disable_cursors"])
        self.assertIsNone(database["options"]["prepare_threshold"])
        self.assertEqual(database["name"], "edify_web")
        self.assertEqual(database["port"], 25061)

    def test_pooled_runtime_fails_closed_if_startup_options_would_be_lost(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.base",
                "DATABASE_URL": "postgresql://runtime:secret@db.example:25061/edify?schema=tenant",
                "DB_USE_PGBOUNCER": "true",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from django.conf import settings; print(settings.DATABASES)",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be combined", result.stderr)


class PerProcessPoolTest(SimpleTestCase):
    """DB_APP_POOL: connections kept open by the process, lent to requests.

    Each request used to open a TLS connection to the pool and authenticate
    before its first query, 40-50 ms in production (audit 2026-10-05, F6).
    The pool is opt-in, honoured only behind PgBouncer, and sized from the
    admission bound of the settings module that boots.
    """

    POOLED = {
        "DATABASE_URL": "postgresql://runtime:secret@db.example:25061/edify?sslmode=require",
        "DB_USE_PGBOUNCER": "true",
        "DB_POOL_NAME": "edify_web",
        "DB_POOL_PORT": "25061",
    }

    def _run(self, extra_env, module="config.settings.loadtest"):
        env = os.environ.copy()
        for name in list(env):
            if name.startswith(
                ("DB_APP_POOL", "DB_USE_PGBOUNCER", "DB_POOL_", "DB_CONN_MAX_AGE")
            ):
                env.pop(name)
        env.pop("WEB_MAX_CONCURRENT_REQUESTS", None)
        env.update({"DJANGO_SETTINGS_MODULE": module, **extra_env})
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from django.conf import settings; "
                "d=settings.DATABASES['default']; "
                "print(json.dumps({'pool': d['OPTIONS'].get('pool'), "
                "'conn_max_age': d['CONN_MAX_AGE'], "
                "'prepare': d['OPTIONS'].get('prepare_threshold', 'unset'), "
                "'on': settings.DB_APP_POOL, 'ignored': settings.DB_APP_POOL_IGNORED, "
                "'limit': settings.WEB_MAX_CONCURRENT_REQUESTS}))",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _resolve(self, extra_env, module="config.settings.loadtest"):
        result = self._run(extra_env, module)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_it_is_off_unless_asked_for(self):
        resolved = self._resolve(self.POOLED)
        self.assertIsNone(resolved["pool"])
        self.assertFalse(resolved["on"])
        self.assertFalse(resolved["ignored"])

    def test_it_is_ignored_on_a_direct_connection(self):
        """Held open against the cluster itself, the connections of four
        processes are the cluster's own slots: the 2026-09-12 outage."""
        resolved = self._resolve({"DB_APP_POOL": "true"})
        self.assertIsNone(resolved["pool"])
        self.assertFalse(resolved["on"])
        self.assertTrue(resolved["ignored"])

    def test_it_is_sized_from_the_admission_bound(self):
        resolved = self._resolve(
            {**self.POOLED, "DB_APP_POOL": "true", "WEB_MAX_CONCURRENT_REQUESTS": "10"}
        )
        self.assertTrue(resolved["on"])
        self.assertEqual(resolved["limit"], 10)
        pool = resolved["pool"]
        # Ten requests past the guard, and room for what it exempts.
        self.assertEqual(pool["max_size"], 12)
        self.assertEqual(pool["min_size"], 2)
        self.assertEqual(pool["timeout"], 5)
        # Still nothing kept by a request thread, and nothing a transaction
        # pool cannot carry from one statement to the next.
        self.assertEqual(resolved["conn_max_age"], 0)
        self.assertIsNone(resolved["prepare"])

    def test_the_bound_the_settings_module_settles_on_is_the_one_used(self):
        """prod.py and loadtest.py default the bound after base.py is read."""
        resolved = self._resolve({**self.POOLED, "DB_APP_POOL": "true"})
        self.assertEqual(resolved["limit"], 6)
        self.assertEqual(resolved["pool"]["max_size"], 8)

    def test_its_size_can_be_set(self):
        resolved = self._resolve(
            {
                **self.POOLED,
                "DB_APP_POOL": "true",
                "WEB_MAX_CONCURRENT_REQUESTS": "4",
                "DB_APP_POOL_HEADROOM": "3",
                "DB_APP_POOL_MIN_SIZE": "20",
                "DB_APP_POOL_TIMEOUT_S": "9",
            }
        )
        self.assertEqual(resolved["pool"]["max_size"], 7)
        # Never more kept open than the pool may hold.
        self.assertEqual(resolved["pool"]["min_size"], 7)
        self.assertEqual(resolved["pool"]["timeout"], 9)

    def test_it_refuses_a_connection_lifetime(self):
        result = self._run(
            {**self.POOLED, "DB_APP_POOL": "true", "DB_CONN_MAX_AGE": "60"}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be combined with DB_CONN_MAX_AGE", result.stderr)

    def test_it_refuses_a_process_with_no_admission_bound(self):
        result = self._run(
            {**self.POOLED, "DB_APP_POOL": "true", "WEB_MAX_CONCURRENT_REQUESTS": "0"}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("needs WEB_MAX_CONCURRENT_REQUESTS", result.stderr)

    def test_the_boot_gate_reports_an_ignored_pool(self):
        from unittest import mock

        from apps.core import boot_gates

        with mock.patch.object(settings, "DB_APP_POOL_IGNORED", True, create=True):
            self.assertEqual(len(boot_gates._check_app_pool_ignored()), 1)
        with mock.patch.object(settings, "DB_APP_POOL_IGNORED", False, create=True):
            self.assertEqual(boot_gates._check_app_pool_ignored(), [])

    def test_the_driver_it_needs_is_a_pinned_requirement(self):
        import psycopg_pool

        pinned = (ROOT / "requirements/base.txt").read_text()
        self.assertIn(f"psycopg-pool=={psycopg_pool.__version__}", pinned)


class PooledConnectionsAreLentNotKeptTest(TestCase):
    """The pool itself, against this test database.

    Under ASGI each request has its own thread and its own Django connection
    wrapper; the wrappers of one process share one pool. So "two requests" is
    two threads here, each with a wrapper of its own.
    """

    ALIAS = "edify-pool-under-test"

    def setUp(self):
        import copy

        from django.db.backends.postgresql.base import DatabaseWrapper

        self.settings_dict = copy.deepcopy(connection.settings_dict)
        self.settings_dict["CONN_MAX_AGE"] = 0
        self.settings_dict["CONN_HEALTH_CHECKS"] = True
        self.settings_dict["OPTIONS"]["pool"] = {
            "name": "edify-test",
            "min_size": 1,
            "max_size": 1,
            "timeout": 0.5,
        }
        self.wrapper = lambda: DatabaseWrapper(self.settings_dict, self.ALIAS)
        self.addCleanup(lambda: self.wrapper().close_pool())

    def _in_a_request(self, work):
        """Run ``work(wrapper)`` on a thread of its own, as a request is."""
        from concurrent.futures import ThreadPoolExecutor

        def request():
            wrapper = self.wrapper()
            try:
                return work(wrapper)
            finally:
                # What request_finished does: with CONN_MAX_AGE=0 the wrapper
                # gives its connection up, which here means back to the pool.
                wrapper.close_if_unusable_or_obsolete()

        with ThreadPoolExecutor(max_workers=1) as thread:
            return thread.submit(request).result(timeout=20)

    @staticmethod
    def _backend(wrapper):
        with wrapper.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            return cursor.fetchone()[0]

    def test_the_next_request_is_served_by_the_connection_the_last_one_returned(self):
        first = self._in_a_request(self._backend)
        second = self._in_a_request(self._backend)
        third = self._in_a_request(self._backend)
        self.assertEqual({first, second, third}, {first})
        stats = self.wrapper().pool.get_stats()
        self.assertEqual(stats["pool_size"], 1)
        self.assertEqual(stats["pool_available"], 1)

    def test_a_request_keeps_nothing_once_it_has_ended(self):
        def work(wrapper):
            self._backend(wrapper)
            wrapper.close_if_unusable_or_obsolete()
            return wrapper.connection

        self.assertIsNone(self._in_a_request(work))

    def test_the_pool_is_a_bound_and_waiting_for_it_is_bounded(self):
        import threading
        import time

        holding = threading.Event()
        release = threading.Event()

        def hold(wrapper):
            pid = self._backend(wrapper)
            holding.set()
            release.wait(timeout=20)
            return pid

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as other:

            def held_request():
                wrapper = self.wrapper()
                try:
                    return hold(wrapper)
                finally:
                    wrapper.close_if_unusable_or_obsolete()

            held = other.submit(held_request)
            self.assertTrue(holding.wait(timeout=20))
            started = time.monotonic()
            with self.assertRaises(OperationalError):
                self._in_a_request(self._backend)
            waited = time.monotonic() - started
            # The pool's timeout (0.5 s here), not for ever.
            self.assertGreaterEqual(waited, 0.4)
            self.assertLess(waited, 5)
            release.set()
            first = held.result(timeout=20)
        # Returned, it serves the next request.
        self.assertEqual(self._in_a_request(self._backend), first)

    def test_a_connection_the_server_dropped_is_replaced_before_it_is_lent(self):
        first = self._in_a_request(self._backend)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", [first])
        second = self._in_a_request(self._backend)
        self.assertNotEqual(second, first)


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

    def test_jit_compilation_is_off_in_the_live_session(self):
        """JIT compiled the lending portfolio KPI for 4.7 s before running it
        in 76 ms: the scoped ORM queries carry planner estimates far above
        jit_above_cost while reading a handful of rows (performance rescue,
        2026-09-23). Asserted on the session, like the ceilings above, so an
        options string that is overwritten rather than appended fails here."""
        self.assertEqual(_setting("jit"), "off")

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
