"""Environment-stamp guard tests: the local↔production data barrier.

Covers both contamination directions (prod server on a local dump; local
shell on the live database), the deliberate re-stamp path, the seed
command's stamp-aware refusal, and the demo-data-on-production detector.
"""

from __future__ import annotations

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.system_health.environment_guard import (
    EnvironmentMismatch,
    validate_environment,
)
from apps.system_health.models import EnvironmentStamp


def _set_stamp(environment: str, **extra):
    stamp, _ = EnvironmentStamp.objects.update_or_create(
        id=EnvironmentStamp.SINGLETON_ID,
        defaults={"environment": environment, **extra},
    )
    return stamp


class EnvironmentGuardTest(TestCase):
    def test_matching_stamp_passes(self):
        _set_stamp("local")
        with override_settings(ENVIRONMENT="local"):
            self.assertEqual(validate_environment(force=True), "ok")

    def test_production_process_refuses_local_dump(self):
        _set_stamp("local")
        with override_settings(ENVIRONMENT="production"):
            with self.assertRaises(EnvironmentMismatch) as ctx:
                validate_environment(force=True)
        self.assertIn("stamped 'local'", str(ctx.exception))

    def test_local_process_refuses_production_database(self):
        _set_stamp("production")
        with override_settings(ENVIRONMENT="local"):
            with self.assertRaises(EnvironmentMismatch):
                validate_environment(force=True)

    def test_missing_stamp_adopts_process_identity(self):
        EnvironmentStamp.objects.all().delete()
        with override_settings(ENVIRONMENT="staging"):
            self.assertEqual(validate_environment(force=True), "stamped")
        self.assertEqual(
            EnvironmentStamp.objects.get(id=1).environment, "staging"
        )

    def test_guard_skips_under_test_runner_argv(self):
        # Default (non-forced) call inside the test runner must not enforce.
        _set_stamp("production")
        with override_settings(ENVIRONMENT="local"):
            self.assertEqual(validate_environment(), "skipped")


class StampCommandTest(TestCase):
    def test_wrong_phrase_refuses_and_preserves_stamp(self):
        _set_stamp("local")
        with self.assertRaises(CommandError):
            call_command(
                "stamp_environment", "--to", "production", "--confirm", "yes"
            )
        self.assertEqual(EnvironmentStamp.objects.get(id=1).environment, "local")

    def test_correct_phrase_restamps_and_audits(self):
        _set_stamp("local")
        call_command(
            "stamp_environment",
            "--to",
            "production",
            "--confirm",
            "STAMP production",
        )
        self.assertEqual(
            EnvironmentStamp.objects.get(id=1).environment, "production"
        )
        from apps.audit.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(action="environment.restamped").exists()
        )


class SeedStampGuardTest(TestCase):
    def test_demo_seed_refuses_production_stamped_database(self):
        _set_stamp("production")
        with self.assertRaises(CommandError) as ctx:
            call_command("seed", "--demo")
        self.assertIn("stamped", str(ctx.exception))
        # Nothing was seeded — the guard fires before any write.
        from apps.schools.models import School

        self.assertEqual(School.objects.count(), 0)

    def test_demo_seed_marks_local_database(self):
        _set_stamp("local")
        call_command("seed", "--demo")
        stamp = EnvironmentStamp.objects.get(id=1)
        self.assertIsNotNone(stamp.seeded_demo_at)


class DemoDataDetectorTest(TestCase):
    def test_detector_flags_seeded_production_database(self):
        from apps.system_health.services import _workflow_issues

        _set_stamp("production", seeded_demo_at=timezone.now())
        issues = _workflow_issues()
        self.assertGreaterEqual(issues["demoDataOnProduction"], 1)
        self.assertEqual(issues["environmentStampMissing"], 0)

    def test_detector_silent_on_local_database(self):
        from apps.system_health.services import _workflow_issues

        _set_stamp("local", seeded_demo_at=timezone.now())
        issues = _workflow_issues()
        self.assertEqual(issues["demoDataOnProduction"], 0)
