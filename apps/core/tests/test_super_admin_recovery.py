"""The bootstrap account must be recoverable without already being signed in.

Every remedy for a blocked sign-in lived behind a sign-in. An escalated lockout
is cleared at /admin-panel/users/<id>, which requires an authenticated Admin —
so when the only Admin is the locked account, the person who can lift the lock
is the person it is applied to.

Re-seeding was the documented way out, and it reset the password while leaving
the lockout untouched: new credentials against a door that was still bolted.
Seeding now clears the super-admin's lockout too, and `manage.py account_access`
gives the same repair for any account from a shell.
"""

from __future__ import annotations

from django.contrib.auth import authenticate
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User

PASSWORD = "recovery-bootstrap-secret-1!"


@override_settings(
    SUPER_ADMIN_EMAIL="recovery-boot@edify.org",
    SUPER_ADMIN_PASSWORD=PASSWORD,
)
class SuperAdminRecoveryTest(TestCase):
    def _lock_out(self, user):
        """The dead end: escalated lockout, which only an Admin may clear."""
        user.lockout_escalated = True
        user.lockout_cycle_count = 3
        user.failed_login_count = 9
        user.failed_login_streak_started_at = timezone.now()
        user.must_change_password = True
        user.save()

    def test_reseeding_restores_a_locked_out_super_admin(self):
        call_command("seed")
        user = User.objects.get(email="recovery-boot@edify.org")
        self._lock_out(user)

        # The state that used to survive a re-seed.
        self.assertIsNone(authenticate(email=user.email, password=PASSWORD))

        call_command("seed")

        user.refresh_from_db()
        self.assertFalse(user.lockout_escalated)
        self.assertEqual(user.failed_login_count, 0)
        self.assertEqual(user.lockout_cycle_count, 0)
        self.assertIsNone(user.locked_until)
        self.assertFalse(user.must_change_password)
        self.assertIsNotNone(
            authenticate(email=user.email, password=PASSWORD),
            "re-seeding must actually restore sign-in, not just the password",
        )

    def test_a_timed_lockout_is_cleared_too(self):
        call_command("seed")
        user = User.objects.get(email="recovery-boot@edify.org")
        user.locked_until = timezone.now() + timezone.timedelta(hours=6)
        user.save(update_fields=["locked_until"])

        call_command("seed")

        user.refresh_from_db()
        self.assertIsNone(user.locked_until)

    def test_the_repair_is_scoped_to_the_super_admin(self):
        """Everyone else keeps their lockout — it is brute-force protection
        doing its job, and a seed must not become a blanket amnesty."""
        call_command("seed")
        other = User.objects.create(
            id="recovery-other",
            email="recovery-other@edify.org",
            name="Other Locked User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        self._lock_out(other)

        call_command("seed")

        other.refresh_from_db()
        self.assertTrue(other.lockout_escalated)
        self.assertEqual(other.failed_login_count, 9)


class AccountAccessCommandTest(TestCase):
    """The shell-side repair, for any account and without a redeploy."""

    def setUp(self):
        self.user = User.objects.create(
            id="access-cmd-user",
            email="access-cmd@edify.org",
            name="Access Command User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        self.user.set_password("a-known-password-9!")
        self.user.save()

    def test_it_reports_without_changing_anything(self):
        self.user.lockout_escalated = True
        self.user.save(update_fields=["lockout_escalated"])

        call_command("account_access", "access-cmd@edify.org")

        self.user.refresh_from_db()
        self.assertTrue(
            self.user.lockout_escalated,
            "a diagnostic must not repair as a side effect of looking",
        )

    def test_unlock_restores_sign_in(self):
        self.user.lockout_escalated = True
        self.user.failed_login_count = 7
        self.user.save()
        self.assertIsNone(
            authenticate(email=self.user.email, password="a-known-password-9!")
        )

        call_command("account_access", "access-cmd@edify.org", "--unlock")

        self.user.refresh_from_db()
        self.assertFalse(self.user.lockout_escalated)
        self.assertEqual(self.user.failed_login_count, 0)
        self.assertIsNotNone(
            authenticate(email=self.user.email, password="a-known-password-9!")
        )

    def test_activate_revives_a_disabled_account(self):
        User.objects.filter(id=self.user.id).update(status="disabled", is_active=False)

        call_command("account_access", "access-cmd@edify.org", "--activate")

        self.user.refresh_from_db()
        self.assertEqual(self.user.status, "active")
        self.assertTrue(self.user.is_active)

    def test_an_unknown_email_is_an_error_not_a_silent_no_op(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("account_access", "nobody-here@edify.org")
