"""A person changes their own password from their Profile, and an Admin is
never locked out by resetting their own.

Owner, 2026-11-16: "fix the admin password conflict. when the same password is
set twice it blocks the first one set from logging in. can you add the self
password reset from the user profile and make sure that the other is not
locked out. right now admin is locked out." Asked what happened: the Admin
reset their own password from the Users page, set it again on the
change-password page, and sign-in now answers "invalid password".

The server path itself held (reset, sign in, change, sign in again all pass).
What broke was around it: the Users page was the only place an Admin could
change their own password, and that is the reset an Admin gives somebody
else. It signs the Admin out on their very next click, while the toast says
"they" must change it on next login. The sign-in attempts that follow, with
the old or a browser-filled password, each count as a failure; a locked
account answers exactly as a wrong password does; and after three lock cycles
only an Admin may unlock it, so the sole Admin cannot. The emailed reset did
not lift a lock either: a new password against a door still bolted.
"""

from __future__ import annotations

import hashlib
import importlib
from datetime import timedelta

from django.apps import apps as django_apps
from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts import auth_services
from apps.accounts.models import RefreshToken, StaffProfile
from apps.core.rbac import EdifyRole
from apps.core.security import generate_token, hash_token
from apps.core.throttling import reset_throttle_state
from apps.frontend.views.staff_views import OWN_PASSWORD_CHANGES_PER_MIN

User = get_user_model()
PASSWORD = "StrongPassphrase!23"
NEW_PASSWORD = "Fresh-Passphrase!48"


def _user(email: str, role: str = EdifyRole.ADMIN.value) -> User:
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )
    StaffProfile.objects.create(user=user, country="Uganda", title=role)
    return user


def _escalate(user) -> None:
    """The state the live Admin is in: locked until an Admin unlocks it."""
    User.objects.filter(id=user.id).update(
        lockout_escalated=True,
        lockout_cycle_count=3,
        failed_login_count=0,
        last_lockout_at=timezone.now(),
    )


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class ProfileChangesOwnPasswordTests(TestCase):
    def setUp(self):
        # Each test its own documentation-only address and throttle window,
        # as apps/accounts/test_lockout_unification.py does, so one test's
        # attempts never count against another's (or another worker's).
        suffix = hashlib.sha256(self.id().encode()).hexdigest()[:16]
        ip = f"2001:db8::{suffix}"
        self.client.defaults["REMOTE_ADDR"] = ip
        keys = [f"auth.own_password:{ip}"]
        reset_throttle_state(keys)
        self.addCleanup(reset_throttle_state, keys)
        self.admin = _user("own-admin@edify.test")
        self.client.force_login(self.admin)

    def _change(self, current=PASSWORD, new=NEW_PASSWORD, confirm=None):
        return self.client.post(
            "/profile/password",
            {
                "current_password": current,
                "new_password": new,
                "confirm_password": new if confirm is None else confirm,
            },
            follow=True,
        )

    def test_the_profile_offers_a_change_password_form(self):
        page = self.client.get("/profile").content.decode()
        self.assertIn('action="/profile/password"', page)
        self.assertIn('id="change-password"', page)
        self.assertIn('name="current_password"', page)
        self.assertIn('name="new_password"', page)
        self.assertIn('name="confirm_password"', page)

    def test_the_new_password_signs_in_and_the_person_stays_signed_in(self):
        response = self._change()

        self.assertContains(response, "Your password has been changed")
        # Still signed in: the page after the change is the Profile, not the
        # sign-in page, and the next page opens too.
        self.assertEqual(response.redirect_chain[-1][0], "/profile")
        self.assertEqual(self.client.get("/profile").status_code, 200)
        self.assertIsNotNone(
            authenticate(email=self.admin.email, password=NEW_PASSWORD)
        )
        self.assertIsNone(authenticate(email=self.admin.email, password=PASSWORD))

    def test_setting_the_same_password_again_is_allowed(self):
        self._change(new=PASSWORD)

        self.assertIsNotNone(authenticate(email=self.admin.email, password=PASSWORD))

    def test_a_wrong_current_password_changes_nothing_and_locks_nothing(self):
        for _ in range(OWN_PASSWORD_CHANGES_PER_MIN):
            response = self._change(current="Not-The-Password!1")

        self.assertContains(response, "Your current password is not right.")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.failed_login_count, 0)
        self.assertFalse(self.admin.lockout_escalated)
        self.assertIsNone(self.admin.locked_until)
        self.assertIsNotNone(authenticate(email=self.admin.email, password=PASSWORD))

    def test_too_many_attempts_in_a_minute_are_refused(self):
        for _ in range(OWN_PASSWORD_CHANGES_PER_MIN):
            self._change(current="Not-The-Password!1")

        response = self._change()

        self.assertContains(response, "Too many attempts")
        self.assertIsNotNone(authenticate(email=self.admin.email, password=PASSWORD))

    def test_a_mismatch_or_a_weak_password_is_refused(self):
        response = self._change(confirm="Something-Else!9")
        self.assertContains(response, "The new passwords do not match.")

        response = self._change(new="short")
        self.assertContains(response, "at least 8 characters")
        self.assertIsNotNone(authenticate(email=self.admin.email, password=PASSWORD))

    def test_the_change_signs_out_the_app(self):
        RefreshToken.objects.create(
            user=self.admin,
            token_hash=hash_token(generate_token()),
            expires_at=timezone.now() + timedelta(days=1),
        )

        self._change()

        self.assertFalse(
            RefreshToken.objects.filter(
                user=self.admin, revoked_at__isnull=True
            ).exists()
        )

    def test_a_get_does_not_change_anything(self):
        response = self.client.get("/profile/password")
        self.assertEqual(response.status_code, 405)


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class UsersPageNeverResetsYourOwnPasswordTests(TestCase):
    def setUp(self):
        self.admin = _user("users-admin@edify.test")
        self.cceo = _user("users-cceo@edify.test", EdifyRole.CCEO.value)
        self.client.force_login(self.admin)

    def _reset(self, account, password=NEW_PASSWORD):
        return self.client.post(
            f"/admin-panel/users/{account.id}",
            {"action": "reset_password", "new_password": password, "next": "users"},
            HTTP_HX_REQUEST="true",
        )

    def test_resetting_your_own_password_is_refused_and_points_to_the_profile(self):
        response = self._reset(self.admin)

        self.assertContains(response, "your own account")
        self.assertContains(response, "Profile")
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.must_change_password)
        self.assertIsNotNone(authenticate(email=self.admin.email, password=PASSWORD))
        # Still signed in: nothing changed the session's password.
        self.assertEqual(self.client.get("/profile").status_code, 200)

    def test_your_own_drawer_sends_you_to_the_profile_instead(self):
        drawer = self.client.get(
            f"/admin-panel/users/{self.admin.id}?drawer=password",
            HTTP_HX_REQUEST="true",
        ).content.decode()

        self.assertIn('href="/profile#change-password"', drawer)
        self.assertNotIn('name="new_password"', drawer)

    def test_your_own_account_page_sends_you_to_the_profile_instead(self):
        page = self.client.get(f"/admin-panel/users/{self.admin.id}").content.decode()

        self.assertIn('href="/profile#change-password"', page)
        self.assertNotIn('value="reset_password"', page)

    def test_another_persons_password_is_still_reset(self):
        self._reset(self.cceo)

        self.cceo.refresh_from_db()
        self.assertTrue(self.cceo.must_change_password)
        self.assertIsNotNone(authenticate(email=self.cceo.email, password=NEW_PASSWORD))


class EmailedResetLiftsTheLockTests(TestCase):
    def test_a_locked_account_signs_in_with_the_password_its_reset_link_set(self):
        admin = _user("reset-admin@edify.test")
        _escalate(admin)
        token = generate_token()
        User.objects.filter(id=admin.id).update(
            password_reset_token_hash=hash_token(token),
            password_reset_expires=timezone.now() + timedelta(minutes=30),
        )
        self.assertIsNone(authenticate(email=admin.email, password=PASSWORD))

        auth_services.reset_password(token, NEW_PASSWORD, NEW_PASSWORD)

        self.assertIsNotNone(authenticate(email=admin.email, password=NEW_PASSWORD))


class LockedAdminsAreUnlockedOnDeployTests(TestCase):
    def test_every_admin_is_unlocked_and_nobody_else(self):
        migration = importlib.import_module(
            "apps.accounts.migrations.0040_unlock_admin_accounts"
        )
        admin = _user("deploy-admin@edify.test")
        cceo = _user("deploy-cceo@edify.test", EdifyRole.CCEO.value)
        _escalate(admin)
        _escalate(cceo)
        User.objects.filter(id=admin.id).update(
            locked_until=timezone.now() + timedelta(minutes=10), failed_login_count=4
        )

        migration.unlock_admin_accounts(django_apps, None)

        admin.refresh_from_db()
        cceo.refresh_from_db()
        self.assertFalse(admin.lockout_escalated)
        self.assertIsNone(admin.locked_until)
        self.assertEqual(admin.failed_login_count, 0)
        self.assertEqual(admin.lockout_cycle_count, 0)
        self.assertIsNotNone(authenticate(email=admin.email, password=PASSWORD))
        # Every other account keeps its lock: that is the brute-force
        # protection doing its job.
        self.assertTrue(cceo.lockout_escalated)
