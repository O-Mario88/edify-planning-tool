from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.core.management.commands.seed import Command


@override_settings(IS_PRODUCTION=False)
class SeedResetOrderingTests(TestCase):
    def test_demo_reset_purges_before_rebuilding_geography_and_sample_data(self):
        calls = []

        def record(name):
            return lambda *args, **kwargs: calls.append(name)

        with (
            patch.object(Command, "_purge_operational", side_effect=record("purge")),
            patch.object(
                Command, "_seed_permissions", side_effect=record("permissions")
            ),
            patch.object(Command, "_seed_geography", side_effect=record("geography")),
            patch.object(Command, "_seed_super_admin", side_effect=record("admin")),
            patch.object(
                Command, "_seed_demo_accounts", side_effect=record("accounts")
            ),
            patch.object(Command, "_seed_sample_data", side_effect=record("sample")),
        ):
            call_command("seed", "--demo", "--reset", stdout=StringIO())

        self.assertEqual(
            calls,
            ["purge", "permissions", "geography", "admin", "accounts", "sample"],
        )
