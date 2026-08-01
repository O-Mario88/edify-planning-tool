"""Regression test for the day-1 production login blocker found in the
2026-07-15 deployment-readiness audit: the super-admin block lived inside
_seed_demo_accounts() (demo-only, refuses production), so a plain
`manage.py seed` on a fresh production database created ZERO login-able
users — prod.py demanded SUPER_ADMIN_PASSWORD to boot, then nothing
consumed it. The super-admin must now be created by the always-run path.
"""

from django.contrib.auth import authenticate, get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

User = get_user_model()


@override_settings(
    SUPER_ADMIN_EMAIL="ops-boot@edify.org",
    SUPER_ADMIN_PASSWORD="a-strong-day1-secret",
)
class SeedSuperAdminTest(TestCase):
    def test_plain_seed_creates_a_login_able_super_admin(self):
        call_command("seed")  # no --demo — the production form

        u = User.objects.get(email="ops-boot@edify.org")
        self.assertTrue(u.is_active)
        self.assertEqual(u.active_role, "Admin")
        # Must be able to reach Django /admin/ — the day-1 bootstrap surface
        # for geography reference data.
        self.assertTrue(u.is_staff)
        self.assertTrue(u.is_superuser)

    def test_super_admin_carries_both_the_admin_and_field_hats(self):
        """The same person runs the platform and works the field as a CCEO, so
        the account holds both and switches between them. It lands on Admin —
        the field hat is chosen deliberately, never by default."""
        call_command("seed")

        u = User.objects.get(email="ops-boot@edify.org")
        self.assertEqual(u.roles, ["Admin", "CCEO"])
        self.assertEqual(u.active_role, "Admin")

    def test_the_field_hat_has_a_staff_profile_to_work_through(self):
        """Targets, visit plans and assignments key off StaffProfile rather
        than the User row. Without one the CCEO hat opens onto surfaces that
        cannot be populated."""
        from apps.accounts.models import StaffProfile

        call_command("seed")

        u = User.objects.get(email="ops-boot@edify.org")
        self.assertTrue(StaffProfile.objects.filter(user=u).exists())

    def test_reseeding_leaves_the_field_hat_on(self):
        """Someone part-way through a field shift must not be pulled back into
        the admin workspace by a deploy."""
        call_command("seed")
        User.objects.filter(email="ops-boot@edify.org").update(active_role="CCEO")

        call_command("seed")

        self.assertEqual(
            User.objects.get(email="ops-boot@edify.org").active_role, "CCEO"
        )

    def test_reseeding_corrects_a_role_the_account_may_not_wear(self):
        call_command("seed")
        User.objects.filter(email="ops-boot@edify.org").update(
            active_role="PartnerAdmin"
        )

        call_command("seed")

        u = User.objects.get(email="ops-boot@edify.org")
        self.assertEqual(u.roles, ["Admin", "CCEO"])
        self.assertEqual(u.active_role, "Admin")
        # And actually log in through the shared lockout-enforcing backend.
        self.assertIsNotNone(
            authenticate(email="ops-boot@edify.org", password="a-strong-day1-secret")
        )

    def test_seed_is_idempotent_and_rotates_the_password(self):
        call_command("seed")
        with override_settings(SUPER_ADMIN_PASSWORD="rotated-day2-secret"):
            call_command("seed")

        self.assertEqual(User.objects.filter(email="ops-boot@edify.org").count(), 1)
        self.assertIsNotNone(
            authenticate(email="ops-boot@edify.org", password="rotated-day2-secret")
        )

    def test_seed_without_password_skips_quietly(self):
        with override_settings(SUPER_ADMIN_PASSWORD=""):
            call_command("seed")
        self.assertFalse(User.objects.filter(email="ops-boot@edify.org").exists())
