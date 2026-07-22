"""SEC-01 — production boot gates (apps.core.boot_gates), the four
conditions the prior audit found missing from config/settings/prod.py's
import-time checks: DB-unavailable-at-boot, pending migrations, missing
static assets. (The fourth, scheduler-disabled, is covered as a System
Health CRITICAL check instead — see apps.realtime.health — and is verified
in apps/realtime/tests.py, not here.)

These call the module's functions directly rather than actually booting
under config.settings.prod, since prod settings perform their own
import-time SystemExit checks (JWT secret strength, SUPER_ADMIN_PASSWORD,
etc.) unrelated to what's under test here.
"""

from __future__ import annotations

import shutil
import tempfile
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.core import boot_gates


class DatabaseAvailabilityGateTest(SimpleTestCase):
    def test_passes_when_connection_succeeds(self):
        with patch("django.db.connections") as mock_connections:
            mock_connections.__getitem__.return_value.ensure_connection.return_value = (
                None
            )
            self.assertEqual(boot_gates._check_database_available(), [])

    def test_fails_closed_when_connection_raises(self):
        from django.db.utils import OperationalError

        with patch("django.db.connections") as mock_connections:
            mock_connections.__getitem__.return_value.ensure_connection.side_effect = (
                OperationalError("could not connect to server")
            )
            issues = boot_gates._check_database_available()
        self.assertEqual(len(issues), 1)
        self.assertIn("Database is unavailable", issues[0])


class MigrationStateGateTest(TestCase):
    """Uses the REAL test database — after Django's test runner applies all
    migrations to build it, there must be nothing pending."""

    def test_passes_when_no_pending_migrations(self):
        self.assertEqual(boot_gates._check_no_pending_migrations(), [])

    def test_fails_closed_when_migrations_are_pending(self):
        # MagicMock(name=...) is special-cased to set the mock's own repr,
        # not an attribute — set .name explicitly afterward instead.
        fake_migration = MagicMock(app_label="fake_app")
        fake_migration.name = "0099_pending"
        fake_executor = MagicMock()
        fake_executor.migration_plan.return_value = [(fake_migration, False)]
        with patch(
            "django.db.migrations.executor.MigrationExecutor",
            return_value=fake_executor,
        ):
            issues = boot_gates._check_no_pending_migrations()
        self.assertEqual(len(issues), 1)
        self.assertIn("fake_app.0099_pending", issues[0])


class StaticAssetsGateTest(SimpleTestCase):
    def test_passes_when_static_root_populated(self):
        tmp = tempfile.mkdtemp(prefix="edify-static-test-")
        try:
            with open(f"{tmp}/app.css", "w") as f:
                f.write("body{}")
            with self.settings(STATIC_ROOT=tmp):
                self.assertEqual(boot_gates._check_static_assets_collected(), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_fails_closed_when_static_root_empty(self):
        tmp = tempfile.mkdtemp(prefix="edify-static-empty-")
        try:
            with self.settings(STATIC_ROOT=tmp):
                issues = boot_gates._check_static_assets_collected()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(len(issues), 1)
        self.assertIn("Static assets are missing", issues[0])

    def test_fails_closed_when_static_root_missing_entirely(self):
        # nosec B108 - a deliberately absent path; nothing is written here.
        with self.settings(
            STATIC_ROOT="/tmp/edify-static-does-not-exist-xyz"  # nosec B108
        ):
            issues = boot_gates._check_static_assets_collected()
        self.assertEqual(len(issues), 1)

    def test_fails_closed_when_static_root_unset(self):
        with self.settings(STATIC_ROOT=None):
            issues = boot_gates._check_static_assets_collected()
        self.assertEqual(len(issues), 1)
        self.assertIn("STATIC_ROOT is not configured", issues[0])


class VerifyOrExitTest(SimpleTestCase):
    def test_exits_when_any_gate_fails(self):
        with (
            patch.object(
                boot_gates, "_check_database_available", return_value=["db down"]
            ),
            patch.object(boot_gates, "_check_no_pending_migrations", return_value=[]),
            patch.object(boot_gates, "_check_static_assets_collected", return_value=[]),
        ):
            with self.assertRaises(SystemExit):
                boot_gates.verify_or_exit()

    def test_skips_migration_check_when_database_unavailable(self):
        """A dead DB makes the migration-state query itself unreliable — no
        point piling on a second, redundant failure from the same root
        cause."""
        migration_check = MagicMock(return_value=[])
        with (
            patch.object(
                boot_gates, "_check_database_available", return_value=["db down"]
            ),
            patch.object(boot_gates, "_check_no_pending_migrations", migration_check),
            patch.object(boot_gates, "_check_static_assets_collected", return_value=[]),
        ):
            with self.assertRaises(SystemExit):
                boot_gates.verify_or_exit()
        migration_check.assert_not_called()

    def test_passes_when_every_gate_is_clean(self):
        with (
            patch.object(boot_gates, "_check_database_available", return_value=[]),
            patch.object(boot_gates, "_check_no_pending_migrations", return_value=[]),
            patch.object(boot_gates, "_check_static_assets_collected", return_value=[]),
        ):
            boot_gates.verify_or_exit()  # must not raise


class AppReadySkipsForManagementCommandsTest(SimpleTestCase):
    """apps.core.apps.CoreConfig.ready() must not gate commands that
    legitimately manage/introspect the DB schema, or any non-production
    process (dev, test)."""

    def test_skip_list_covers_migrate_and_friends(self):
        from apps.core.apps import _SKIP_BOOT_GATES_FOR_COMMANDS

        for command in ("migrate", "makemigrations", "collectstatic", "test"):
            self.assertIn(command, _SKIP_BOOT_GATES_FOR_COMMANDS)

    @staticmethod
    def _core_config():
        # The already-registered instance from the live app registry —
        # calling .ready() on it again is safe (it's just a conditional
        # check + function call, no state mutation) and avoids re-running
        # Django's app-loading machinery via AppConfig.create().
        from django.apps import apps

        return apps.get_app_config("core")

    def test_ready_is_a_noop_outside_production(self):
        config = self._core_config()
        with (
            self.settings(IS_PRODUCTION=False),
            patch("apps.core.boot_gates.verify_or_exit") as mock_verify,
        ):
            config.ready()
        mock_verify.assert_not_called()

    def test_ready_runs_the_gates_in_production_for_the_server_process(self):
        import sys

        config = self._core_config()
        with (
            self.settings(IS_PRODUCTION=True),
            patch.object(sys, "argv", ["daphne", "config.asgi:application"]),
            patch("apps.core.boot_gates.verify_or_exit") as mock_verify,
        ):
            config.ready()
        mock_verify.assert_called_once()

    def test_ready_skips_gates_for_migrate_command_in_production(self):
        import sys

        config = self._core_config()
        with (
            self.settings(IS_PRODUCTION=True),
            patch.object(sys, "argv", ["manage.py", "migrate", "--noinput"]),
            patch("apps.core.boot_gates.verify_or_exit") as mock_verify,
        ):
            config.ready()
        mock_verify.assert_not_called()
