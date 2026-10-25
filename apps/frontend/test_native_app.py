"""What the iOS and Android app (mobile/, docs/mobile-app.md) is sent that a
browser is not.

The app names itself in its user agent ("EdifyApp", capacitor.config.js). Its
shell script (static/js/native-shell.js) keeps a tapped field from zooming
the page, among other things, so every page the app can show must carry it:
the sign-in page too, which is a layout of its own (layouts/login.html).
"""

from __future__ import annotations

import re

from django.test import TestCase

from apps.accounts.models import StaffProfile, User

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 EdifyApp"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 16; Pixel 9; wv) AppleWebKit/537.36 (KHTML, like "
    "Gecko) Version/4.0 Chrome/133.0.6943.137 Mobile Safari/537.36 EdifyApp"
)
SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/27.0 Mobile/15E148 Safari/604.1"
)


class AppSignInTest(TestCase):
    def test_sign_in_in_the_app_carries_the_app_s_shell(self):
        body = self.client.get("/login", HTTP_USER_AGENT=IPHONE).content.decode()
        self.assertIn("js/native-shell.js", body)

    def test_sign_in_in_a_browser_is_sent_none_of_it(self):
        body = self.client.get("/login", HTTP_USER_AGENT=SAFARI).content.decode()
        self.assertNotIn("js/native-shell.js", body)


def _viewport(body: str) -> str:
    return re.search(r'<meta name="viewport" content="([^"]*)"', body).group(1)


class AppKeepsItsScaleTest(TestCase):
    """A tapped field under 16px zoomed an iPhone's page into it and left it
    there, filling the screen (sign-in's fields are 13px). In the app the
    page's own viewport holds its scale from the first frame, on both phones,
    before any script has run; a browser keeps its pinch zoom."""

    def test_sign_in_in_the_app_holds_its_scale_on_both_phones(self):
        for agent in (IPHONE, ANDROID):
            body = self.client.get("/login", HTTP_USER_AGENT=agent).content.decode()
            self.assertIn("maximum-scale=1", _viewport(body), agent)

    def test_a_signed_in_page_in_the_app_holds_its_scale(self):
        user = User.objects.create_user(
            email="field@edify.test",
            password="password123",
            name="Field Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(user=user, title="CCEO", country="Uganda")
        self.client.force_login(user)
        body = self.client.get("/home", HTTP_USER_AGENT=ANDROID).content.decode()
        self.assertIn("maximum-scale=1", _viewport(body))

    def test_a_browser_keeps_its_pinch_zoom(self):
        body = self.client.get("/login", HTTP_USER_AGENT=SAFARI).content.decode()
        self.assertNotIn("maximum-scale", _viewport(body))


class AppSignInBarsTest(TestCase):
    """The phone's bars beside sign-in take its colours in the app, as on every
    other page (static/js/system-chrome.js); a browser is not sent the script."""

    def test_sign_in_in_the_app_colours_the_phone_s_bars(self):
        body = self.client.get("/login", HTTP_USER_AGENT=ANDROID).content.decode()
        self.assertIn("js/system-chrome.js", body)

    def test_sign_in_in_a_browser_does_not(self):
        body = self.client.get("/login", HTTP_USER_AGENT=SAFARI).content.decode()
        self.assertNotIn("js/system-chrome.js", body)


class SignInClearsThePhoneBarsTest(TestCase):
    """On an iPhone the app runs the page under the status bar (static/js/
    system-chrome.js), so sign-in must clear it itself: its card sat behind
    the clock (2026-10-25). The phone rules re-set the sign-in area's padding
    without the safe areas, so the clearance is the last word on its frame."""

    def test_the_sign_in_frame_clears_the_status_bar_and_home_indicator(self):
        from pathlib import Path

        from django.conf import settings

        css = Path(settings.BASE_DIR, "static/css/login.css").read_text()
        frame = [m for m in re.finditer(r"\.login-shell\s*\{([^}]*)\}", css)]
        padded = [m for m in frame if "padding" in m.group(1)]
        self.assertTrue(padded, "the sign-in frame pads itself")
        last = padded[-1]
        for edge in ("top", "bottom"):
            self.assertIn(f"env(safe-area-inset-{edge}", last.group(1))
        # Nothing after it takes the clearance back on the sign-in area.
        self.assertNotRegex(css[last.end() :], r"\.login-shell\s*\{[^}]*padding")
