"""Account identity and workspace settings have separate shell controls.

The upper-right avatar owns name, title and Log out. The sidebar footer is one
gear icon whose panel owns appearance, settings links and sidebar layout.
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
SETTINGS_PAGE = ROOT / "templates" / "pages" / "settings" / "index.html"

# Everything the Settings page offers, reachable from the gear.
SETTINGS_DESTINATIONS = ["/settings", "/profile", "/change-password", "/notifications"]
THEMES = ["system", "light", "blue", "dark"]


class SidebarSettingsMarkupTest(TestCase):
    def setUp(self):
        self.src = SIDEBAR.read_text()

    def test_the_corner_is_a_settings_control_not_a_decorative_avatar(self):
        self.assertIn("app-sidebar__settings-trigger", self.src)
        self.assertIn('aria-label="Settings"', self.src)
        self.assertNotIn("avatar_initials", self.src)
        self.assertNotIn("app-sidebar__user-name", self.src)
        self.assertNotIn("app-sidebar__user-role", self.src)
        self.assertNotIn("request.user.name", self.src)
        self.assertNotIn("request.user.active_role", self.src)

    def test_every_theme_is_wired_to_the_real_theme_store(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                self.assertIn(f"$store.theme.setTheme('{theme}')", self.src)
                self.assertIn(f"$store.theme.preference === '{theme}'", self.src)

    def test_account_identity_and_logout_live_in_the_top_avatar(self):
        shell = SHELL.read_text()
        self.assertIn("request.user.name", shell)
        self.assertIn("request.user.active_role", shell)
        self.assertIn('action="/logout"', shell)
        form = shell.split('action="/logout"', 1)[1]
        self.assertIn("csrf_token", form.split("</form>", 1)[0])
        self.assertIn("Log out", form.split("</form>", 1)[0])
        self.assertNotIn('action="/logout"', self.src)

    def test_collapse_is_an_item_inside_settings_not_a_footer_row(self):
        self.assertIn("collapsed = !collapsed; settingsOpen = false", self.src)
        self.assertIn("Collapse sidebar", self.src)
        self.assertIn("Expand sidebar", self.src)
        self.assertNotIn("app-sidebar__collapse-btn", self.src)

    def test_settings_page_does_not_repeat_identity_or_logout(self):
        settings = SETTINGS_PAGE.read_text()
        self.assertNotIn("{{ user.name }}", settings)
        self.assertNotIn("{{ user.active_role }}", settings)
        self.assertNotIn('action="/logout"', settings)
        self.assertIn("avatar in the upper-right corner", settings)

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
        # Identity and title are rendered once in the upper-right account menu.
        self.assertIn("Gear Tester", body)
        self.assertIn("CountryDirector", body)
        self.assertIn("Log out", body)
        self.assertEqual(body.count('action="/logout"'), 1)
