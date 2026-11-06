"""A partner's password saves, and says so at once.

Owner, 2026-11-06: "the partner password configuration is too slow not saving
and when the partner changes the password, it does not save ... The admin is
supposed to configure the login just like it is done for the staff." Asked
where, the owner named the Admin's Reset password, the Admin's Configure
login and the partner's first sign-in; asked what they saw: "no response".

The live log of that morning showed every save succeeding in about a third
of a second, and one Reset password sent about twelve times in fifteen
seconds. Nothing on screen said a save was under way: the reset drawer posted
a whole page and waited for the Users page to load again, the line that
answers a click is drawn under an open drawer, and the change-password button
had no busy state. So the drawer now saves in place and says so, keeps a
refused password inside itself, and every one of these buttons shows it is
working and cannot be pressed twice.
"""

from __future__ import annotations

from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import StaffProfile
from apps.core.rbac import EdifyRole
from apps.partners.models import Partner

User = get_user_model()
PASSWORD = "StrongPassphrase!23"
NEW_PASSWORD = "Fresh-Passphrase!48"


def _user(email: str, role: str, *, staff: bool = True, name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )
    if staff:
        StaffProfile.objects.create(user=user, country="Uganda", title=role)
    return user


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class ResetPasswordDrawerSavesInPlaceTests(TestCase):
    def setUp(self):
        self.admin = _user("pp-admin@edify.test", EdifyRole.ADMIN.value)
        self.cceo = _user("pp-cceo@edify.test", EdifyRole.CCEO.value)
        self.login = _user(
            "pp-amos@partner.test",
            EdifyRole.PARTNER_ADMIN.value,
            staff=False,
            name="Amos Ojok",
        )
        self.org = Partner.objects.create(name="Reading Partners", user=self.login)
        self.client.force_login(self.admin)

    def _drawer(self, account) -> str:
        return self.client.get(
            f"/admin-panel/users/{account.id}?drawer=password",
            HTTP_HX_REQUEST="true",
        ).content.decode()

    def _reset(self, account, password: str):
        return self.client.post(
            f"/admin-panel/users/{account.id}",
            {"action": "reset_password", "new_password": password, "next": "users"},
            HTTP_HX_REQUEST="true",
        )

    def test_the_drawer_saves_in_place_and_cannot_be_sent_twice(self):
        drawer = self._drawer(self.login)
        self.assertIn(f'hx-post="/admin-panel/users/{self.login.id}"', drawer)
        self.assertIn('hx-target="#rp-errors"', drawer)
        self.assertIn('hx-disabled-elt="find button[type=submit]"', drawer)
        # The button itself says the save is under way.
        self.assertIn("Saving", drawer)
        self.assertIn('id="rp-errors"', drawer)

    def test_a_partners_password_is_reset_without_reloading_the_users_page(self):
        response = self._reset(self.login, NEW_PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Location", response)
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        body = response.content.decode()
        self.assertIn('hx-swap-oob="beforeend:#toast-container"', body)
        self.assertIn("Password reset for Amos Ojok", body)
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password(NEW_PASSWORD))
        self.assertTrue(self.login.must_change_password)

    def test_a_staff_password_is_reset_the_same_way(self):
        response = self._reset(self.cceo, NEW_PASSWORD)

        self.assertEqual(response["HX-Trigger"], "close-drawer")
        self.cceo.refresh_from_db()
        self.assertTrue(self.cceo.check_password(NEW_PASSWORD))

    def test_a_refused_password_is_said_in_the_drawer_and_nothing_changes(self):
        response = self._reset(self.login, "weakpass")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Trigger", response)
        body = response.content.decode()
        self.assertIn('role="alert"', body)
        self.assertIn("uppercase letter", body)
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password(PASSWORD))
        self.assertFalse(self.login.must_change_password)

    def test_an_empty_password_is_said_in_the_drawer(self):
        response = self._reset(self.login, "   ")

        self.assertIn('role="alert"', response.content.decode())
        self.assertNotIn("HX-Trigger", response)

    def test_without_javascript_the_form_still_posts_and_returns_to_the_list(self):
        response = self.client.post(
            f"/admin-panel/users/{self.login.id}",
            {"action": "reset_password", "new_password": NEW_PASSWORD, "next": "users"},
        )
        self.assertRedirects(
            response, "/admin-panel/users", fetch_redirect_response=False
        )
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password(NEW_PASSWORD))


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerLoginButtonsShowTheyAreWorkingTests(TestCase):
    def setUp(self):
        self.admin = _user("pb-admin@edify.test", EdifyRole.ADMIN.value)
        self.login = _user(
            "pb-login@partner.test",
            EdifyRole.PARTNER_ADMIN.value,
            staff=False,
            name="Grace Achieng",
        )
        self.org = Partner.objects.create(name="Bright Schools", user=self.login)
        self.bare = Partner.objects.create(name="No Login Yet")

    def test_the_configure_login_drawer_says_it_is_saving(self):
        self.client.force_login(self.admin)
        drawer = self.client.get(
            f"/partners/{self.bare.id}/user-setup", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn('hx-disabled-elt="find button[type=submit]"', drawer)
        self.assertIn("Saving", drawer)

    def test_the_account_pages_password_form_says_it_is_saving(self):
        self.client.force_login(self.admin)
        page = self.client.get(f"/admin-panel/users/{self.login.id}").content.decode()
        form = page.split('value="reset_password"', 1)[1].split("</form>", 1)[0]
        self.assertIn("Saving", form)
        self.assertIn(':disabled="busy"', form)

    def test_the_change_password_button_shows_it_is_working(self):
        page = Path("templates/pages/auth/change_password.html").read_text()
        self.assertIn("data-change-password-submit", page)
        self.assertIn("login-submit__spinner", page)
        script = Path("static/js/login.js").read_text()
        self.assertIn("[data-change-password-form]", script)
        self.assertIn("[data-change-password-submit]", script)

    def test_the_partner_sets_their_own_password_at_first_sign_in(self):
        self.login.set_password(NEW_PASSWORD)
        self.login.must_change_password = True
        self.login.save()
        self.client.force_login(self.login)

        page = self.client.get("/change-password").content.decode()
        self.assertIn("data-change-password-submit", page)
        response = self.client.post(
            "/change-password",
            {"new_password": "Own-Choice!2026", "confirm_password": "Own-Choice!2026"},
        )

        self.assertEqual(response.status_code, 302)
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password("Own-Choice!2026"))
        self.assertFalse(self.login.must_change_password)
