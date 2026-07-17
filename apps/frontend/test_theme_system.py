"""Theme preference contract for the shared shell and Settings surface."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


class ThemeSystemContractTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(
            id="theme-system-user",
            email="theme-system@edify.org",
            name="Theme System User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_settings_exposes_system_light_blue_and_dark_preferences(self):
        response = self.client.get("/settings")
        self.assertEqual(response.status_code, 200)
        for mode in ("system", "light", "blue", "dark"):
            self.assertContains(response, f"setTheme('{mode}')")
        self.assertContains(response, "Light by day, dark after 19:00")
        self.assertContains(response, "Night black")
        self.assertContains(response, "OLED-friendly")

    def test_bootstrap_and_runtime_keep_system_as_a_real_preference(self):
        response = self.client.get("/settings")
        self.assertContains(response, "var pref = 'system'")
        self.assertContains(response, "hour >= 6 && hour < 19")
        self.assertContains(response, "html.dataset.themePref = pref")

        javascript = (
            Path(settings.BASE_DIR) / "static/js/alpine-components.js"
        ).read_text(encoding="utf-8")
        self.assertIn("['system', 'light', 'blue', 'dark']", javascript)
        self.assertIn("millisecondsUntilSystemBoundary", javascript)
        self.assertIn("preference: mode", javascript)
        self.assertIn("toggleNight()", javascript)

        design_system = (
            Path(settings.BASE_DIR) / "static/css/design-system.css"
        ).read_text(encoding="utf-8")
        self.assertIn("--edify-bg: #000000", design_system)
        self.assertIn("--edify-canvas-treatment: none", design_system)
