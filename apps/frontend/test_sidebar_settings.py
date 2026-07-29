"""Settings live behind the gear in the sidebar's bottom-left corner.

That corner used to hold a decorative avatar — it showed who you were and did
nothing — while the only route into settings was a menu behind the topbar
avatar. These tests hold the gear in place and, more importantly, hold the
settings actually wired to it: a menu of links that go nowhere would look
identical to a working one in a screenshot.
"""

from __future__ import annotations

from pathlib import Path

from django.test import Client, TestCase
from django.urls import resolve

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole

ROOT = Path(__file__).resolve().parents[2]
SIDEBAR = ROOT / "templates" / "components" / "sidebar.html"
SHELL = ROOT / "templates" / "layouts" / "shell.html"
BASE_DRAWER = ROOT / "templates" / "components" / "drawers" / "base_drawer.html"

# Everything the Settings page offers, reachable from the gear.
SETTINGS_DESTINATIONS = ["/settings", "/profile", "/change-password", "/notifications"]
THEMES = ["system", "light", "blue", "dark"]


class SidebarSettingsMarkupTest(TestCase):
    def setUp(self):
        self.src = SIDEBAR.read_text()

    def test_the_corner_is_a_settings_control_not_a_decorative_avatar(self):
        self.assertIn("app-sidebar__settings-trigger", self.src)
        self.assertIn('aria-label="Settings and account"', self.src)
        self.assertIn('aria-haspopup="true"', self.src)
        # The initials block that used to sit here is gone.
        self.assertNotIn("avatar_initials", self.src)

    def test_the_signed_in_identity_is_still_shown(self):
        """Knowing which account you are in is the other job of this corner."""
        self.assertIn("app-sidebar__user-name", self.src)
        self.assertIn("app-sidebar__user-role", self.src)

    def test_every_theme_is_wired_to_the_real_theme_store(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.assertIn(f"$store.theme.setTheme('{theme}')", self.src)
                self.assertIn(f"$store.theme.preference === '{theme}'", self.src)

    def test_sign_out_posts_with_a_csrf_token(self):
        """A GET logout link would be triggerable cross-site."""
        self.assertIn('action="/logout"', self.src)
        form = self.src.split('action="/logout"', 1)[1]
        self.assertIn("csrf_token", form.split("</form>", 1)[0])

    def test_mobile_navigation_restores_focus_and_hides_background(self):
        shell = SHELL.read_text()
        self.assertIn('x-ref="mobileSidebarOpen"', shell)
        self.assertIn("$refs.mobileSidebarOpen?.focus()", shell)
        self.assertIn(':inert="sidebarOpen"', shell)
        self.assertIn(":aria-hidden=\"sidebarOpen ? 'true' : null\"", shell)

    def test_shared_drawer_traps_focus_hides_background_and_restores_opener(self):
        drawer = BASE_DRAWER.read_text()
        self.assertIn('role="dialog"', drawer)
        self.assertIn('aria-modal="true"', drawer)
        self.assertIn('@keydown.tab="trapFocus($event)"', drawer)
        self.assertIn("backgroundNodes.forEach", drawer)
        self.assertIn("node.inert = true", drawer)
        self.assertIn("target?.isConnected", drawer)


class SidebarSettingsWiringTest(TestCase):
    """The menu's destinations have to be real routes that actually open."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="gear@sidebar.test",
            password="password123",
            name="Gear Tester",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=self.user, title="CD", country="Uganda")
        self.client = Client()
        self.client.force_login(self.user)

    def test_every_destination_resolves(self):
        for url in SETTINGS_DESTINATIONS:
            with self.subTest(url=url):
                self.assertIsNotNone(resolve(url))

    def test_every_destination_opens(self):
        for url in SETTINGS_DESTINATIONS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(
                    response.status_code,
                    (200, 301, 302),
                    f"{url} returned {response.status_code}",
                )

    def test_the_control_renders_on_a_real_page(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("app-sidebar__settings-trigger", body)
        for url in SETTINGS_DESTINATIONS:
            self.assertIn(f'href="{url}"', body)
        # And the identity it labels itself with is this user's.
        self.assertIn("Gear Tester", body)
