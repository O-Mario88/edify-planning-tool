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
        self.assertContains(response, "Matches your device appearance")
        self.assertContains(response, "Night black")
        # "OLED-friendly" was here, and the dark ground stopped being pure
        # black — the one condition under which that claim is true. The
        # accuracy of this description is now held by
        # test_bootstrap_and_runtime_keep_system_as_a_real_preference, which
        # ties it to the token instead of to a literal typed twice.
        self.assertContains(response, "low-glare")

    def test_bootstrap_and_runtime_keep_system_as_a_real_preference(self):
        response = self.client.get("/settings")
        self.assertContains(response, "var pref = 'system'")
        self.assertContains(response, "prefers-color-scheme: dark")
        self.assertContains(response, "html.dataset.themePref = pref")

        javascript = (
            Path(settings.BASE_DIR) / "static/js/alpine-components.js"
        ).read_text(encoding="utf-8")
        self.assertIn("['system', 'light', 'blue', 'dark']", javascript)
        self.assertIn("matchMedia('(prefers-color-scheme: dark)')", javascript)
        self.assertIn("addEventListener('change'", javascript)
        self.assertNotIn("millisecondsUntilSystemBoundary", javascript)
        self.assertIn("preference: mode", javascript)
        self.assertIn("toggleNight()", javascript)

        design_system = (
            Path(settings.BASE_DIR) / "static/css/design-system.css"
        ).read_text(encoding="utf-8")
        self.assertIn("--edify-canvas-treatment: none", design_system)

        # The dark ground, and the Settings copy that describes it, must agree.
        #
        # This asserted `--edify-bg: #000000` while Settings advertised
        # "True-black, low-glare and OLED-friendly". The dark theme was later
        # rebuilt around a deep navy (#0e151c) so stacked cards and table rows
        # have something to sit on — a good change — but the copy went on
        # promising true black, and "OLED-friendly" is a claim only pure black
        # can keep, since that is when OLED pixels are actually off. A screen
        # describing a feature the code no longer implements is the same defect
        # class as a button with no handler; it is just cheaper to fix.
        #
        # So pin them to each other rather than to a literal. Change the
        # ground and this fails until the words change with it.
        dark_block = design_system.split(":root.theme-dark {", 1)[1].split("\n}", 1)[0]
        self.assertIn("--edify-bg:", dark_block)
        is_true_black = "--edify-bg: #000000" in dark_block
        self.assertEqual(
            is_true_black,
            "True-black" in response.content.decode(),
            "the dark theme's background and the words Settings uses to "
            "describe it no longer agree",
        )
