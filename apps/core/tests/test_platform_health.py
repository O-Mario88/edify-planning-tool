"""Each platform check has to flip when its condition is real.

A health check that is green because it cannot go red is worse than no check —
it is read as assurance. So every one of these is tested twice: once in the
healthy state, and once with the failure actually induced.

The conditions here share a property that makes them worth checking at all:
the application keeps serving pages while they hold. Nothing 500s, nothing
appears in an error budget, and the first symptom is a person unable to do
their job for a reason they cannot see.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.core.health import platform_health
from apps.core.rbac import EdifyRole


def _check(key: str) -> dict:
    for check in platform_health()["checks"]:
        if check["key"] == key:
            return check
    raise AssertionError(f"no check named {key}")


def _mfa_user(email, *, channel="email"):
    user = get_user_model().objects.create_user(
        email=email,
        password="password123",
        name="Enrolled",
        roles=[EdifyRole.CCEO.value],
        active_role=EdifyRole.CCEO.value,
        is_active=True,
    )
    user.mfa_enabled = True
    user.mfa_channel = channel
    user.phone = "+256700000000"
    user.save(update_fields=["mfa_enabled", "mfa_channel", "phone"])
    return user


class ShapeTest(TestCase):
    def test_every_check_carries_what_an_operator_needs(self):
        """Severity with no owner and no action is a notification, not a
        check — somebody has to be able to act on it at 3am."""
        required = {
            "key",
            "severity",
            "component",
            "current_state",
            "expected_state",
            "last_check",
            "owner",
            "recommended_action",
            "resolution_link",
        }
        checks = platform_health()["checks"]
        self.assertGreaterEqual(len(checks), 4)
        for check in checks:
            with self.subTest(key=check.get("key")):
                self.assertEqual(required - set(check), set())
                self.assertIn(check["severity"], {"ok", "warning", "critical"})

    def test_it_is_reachable_from_the_system_health_report(self):
        """Wired in, not merely written."""
        from apps.system_health.services import report

        self.assertIn("platform", report())


class MigrationDriftTest(TestCase):
    def test_a_fully_migrated_database_is_clean(self):
        self.assertEqual(_check("migration_drift")["severity"], "ok")

    def test_an_unapplied_migration_is_critical(self):
        """The deploy that skipped its migrate step. Every page that does not
        touch the new column keeps working, so nothing looks wrong."""
        # A plain object, not Mock(name=...) — that argument names the mock
        # itself, so `.name` comes back as a child mock and the assertion below
        # passes against a repr rather than against the migration name.
        pending = SimpleNamespace(app_label="accounts", name="0099_new")
        with mock.patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            return_value=[(pending, False)],
        ):
            check = _check("migration_drift")
        self.assertEqual(check["severity"], "critical")
        self.assertIn("accounts.0099_new", check["current_state"])

    def test_being_unable_to_answer_is_not_reported_as_healthy(self):
        """The difference between 'clean' and 'could not tell' is the whole
        value of the check."""
        with mock.patch(
            "django.db.migrations.executor.MigrationExecutor.migration_plan",
            side_effect=RuntimeError("no connection"),
        ):
            check = _check("migration_drift")
        self.assertNotEqual(check["severity"], "ok")


class EmailDeliveryTest(TestCase):
    def test_the_console_provider_is_fine_outside_production(self):
        self.assertEqual(_check("email_delivery_configured")["severity"], "ok")

    @override_settings(IS_PRODUCTION=True)
    def test_falling_back_to_console_in_production_is_critical(self):
        """A deploy that forgets RESEND_API_KEY does not error. It just stops
        delivering, quietly, forever."""
        self.assertEqual(_check("email_delivery_configured")["severity"], "critical")

    @override_settings(IS_PRODUCTION=True)
    def test_it_says_who_is_locked_out(self):
        """Since two-step verification shipped, an undelivered email is not an
        inconvenience — the code is only ever sent, never shown, so an enrolled
        account has no way in at all. The check should say so."""
        _mfa_user("stranded@edify.test")
        state = _check("email_delivery_configured")["current_state"]
        self.assertIn("two-step", state)
        self.assertIn("1 account", state)

    @override_settings(IS_PRODUCTION=True)
    def test_a_configured_provider_is_healthy(self):
        with mock.patch(
            "apps.core.email.MailerService.is_configured",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            self.assertEqual(_check("email_delivery_configured")["severity"], "ok")


class SmsDeliveryTest(TestCase):
    def test_unconfigured_with_nobody_enrolled_is_only_a_warning(self):
        """Optional. Two-step verification falls back to email, so nobody is
        stranded — SMS simply is not offered."""
        self.assertEqual(_check("sms_delivery_configured")["severity"], "warning")

    def test_unconfigured_with_someone_enrolled_is_critical(self):
        """These accounts expect a text that cannot be sent."""
        _mfa_user("sms-enrolled@edify.test", channel="sms")
        check = _check("sms_delivery_configured")
        self.assertEqual(check["severity"], "critical")
        self.assertIn("1 account", check["recommended_action"])

    def test_configured_is_healthy(self):
        with mock.patch(
            "apps.core.sms.SmsService.is_configured",
            new_callable=mock.PropertyMock,
            return_value=True,
        ):
            self.assertEqual(_check("sms_delivery_configured")["severity"], "ok")


class CacheTest(TestCase):
    def test_a_working_cache_reads_back(self):
        self.assertIn(_check("cache_backend")["severity"], {"ok", "warning"})

    def test_a_cache_that_swallows_writes_is_critical(self):
        """The failure that matters: it accepts everything and returns
        nothing, so every cached figure is silently recomputed on every
        request and the only symptom is the site being slow."""
        with mock.patch("apps.core.health.cache.get", return_value=None):
            self.assertEqual(_check("cache_backend")["severity"], "critical")

    def test_a_cache_that_raises_is_critical(self):
        with mock.patch(
            "apps.core.health.cache.set", side_effect=ConnectionError("refused")
        ):
            self.assertEqual(_check("cache_backend")["severity"], "critical")

    @override_settings(
        IS_PRODUCTION=True,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "probe",
            }
        },
    )
    def test_a_per_process_cache_in_production_is_flagged(self):
        """Redis unreachable at boot degrades to LocMemCache, which works —
        differently — on each worker. The same page can then show two
        different numbers depending on which one answers."""
        check = _check("cache_backend")
        self.assertEqual(check["severity"], "warning")
        self.assertIn("per-process", check["recommended_action"])
