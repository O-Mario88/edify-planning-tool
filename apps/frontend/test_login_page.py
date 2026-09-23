from django.core.cache import cache
from django.test import TestCase

from apps.core.throttling import reset_throttle_state


class LoginPageDesignTest(TestCase):
    def setUp(self):
        # The page caches its figures. The sign-in throttle counts outside the
        # cache when the cache is per-process, so clearing it is not a reset.
        cache.clear()
        reset_throttle_state(["auth.login:127.0.0.1"])

    def test_login_uses_the_supplied_design_language(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "layouts/login.html")
        self.assertContains(response, "Edify Planning &amp;")
        self.assertContains(response, "Access workspace")
        self.assertContains(response, "Built for impact. Designed for results.")
        self.assertContains(response, "Secure access")
        self.assertContains(response, "login-classroom-portrait.jpg")

    def test_login_form_has_accessible_password_and_autofill_controls(self):
        response = self.client.get("/login")

        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'id="current-password"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, "data-password-toggle")
        self.assertContains(response, "data-forgot-password")

    def test_invalid_login_preserves_email_and_remember_me(self):
        response = self.client.post(
            "/login",
            {
                "email": "domario@edify.org",
                "password": "incorrect-password",
                "remember_me": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")
        self.assertContains(response, 'value="domario@edify.org"')
        self.assertContains(
            response, 'id="remember-me" name="remember_me" type="checkbox" checked'
        )
