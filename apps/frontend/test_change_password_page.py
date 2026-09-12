"""The forced change-password screen (owner, 2026-09-12): one centred card
over the blurred classroom photo, eye toggles on both fields, guiding words
instead of dots."""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase


class ChangePasswordPageTest(SimpleTestCase):
    def setUp(self):
        self.page = Path("templates/pages/auth/change_password.html").read_text()
        self.css = Path("static/css/login.css").read_text()

    def test_it_is_the_login_card_in_its_focus_variant(self):
        self.assertIn('{% extends "layouts/login.html" %}', self.page)
        self.assertIn("{% block shell_variant %}focus{% endblock %}", self.page)
        layout = Path("templates/layouts/login.html").read_text()
        self.assertIn(
            '<main class="login-shell" data-variant="{% block shell_variant %}split{% endblock %}">',
            layout,
        )
        self.assertFalse(Path("templates/layouts/auth.html").exists())

    def test_the_background_is_blurred_and_the_card_is_centred(self):
        self.assertIn(
            '.login-shell[data-variant="focus"] .login-access::before', self.css
        )
        self.assertIn("filter: blur(14px)", self.css)
        self.assertIn(
            '.login-shell[data-variant="focus"] {\n  grid-template-columns: 1fr;\n}',
            self.css,
        )
        self.assertIn(
            '.login-shell[data-variant="focus"] .login-brand {\n  display: none;\n}',
            self.css,
        )

    def test_both_fields_have_an_eye_toggle_and_a_guiding_word(self):
        self.assertEqual(self.page.count("data-password-toggle"), 2)
        self.assertIn('placeholder="Create a new password"', self.page)
        self.assertIn('placeholder="Repeat the new password"', self.page)
        self.assertNotIn("\u2022\u2022\u2022", self.page)
        self.assertIn('aria-controls="new_password"', self.page)
        self.assertIn('aria-controls="confirm_password"', self.page)
