"""Priorities is one page with tabs, not three sidebar links.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"I dont see it in the priority page… IA can have priorities and priorities
setting pages but I was also thinking they should be one page separated by
tabs just like the way you did the map and operation. The idea is to reduce to
many menu links. Do it for PLs as well."

Three surfaces answered the same question from three sidebar entries — Priority
Setting (/strategic-priorities), Priorities (/target-distribution or
/priorities) and, for a Program Lead, Team Target Distribution. A Country
Director carried two of them, filed in two different sidebar groups; an Impact
Assessment officer carried only Priorities, so on a country whose master has
not been seeded it opened empty and showed none of the 68 milestones that did
exist. The priorities were in the product the whole time, one menu entry away
from the menu entry named after them.

WHAT THESE TESTS HOLD

That the three routes still exist and still enforce their own permissions —
this joins pages, it does not merge them — and that each one renders the shared
rail whose tabs are exactly the views that reader has. A press asks for the
rail and the panel together, which is what makes it a tab and not a link.
"""

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import StaffProfile, User
from apps.frontend.views.priority_workspace import (
    PANEL_ID,
    SHELL_ID,
    priority_workspace_tabs,
)
from apps.hr.uganda_master_seeding import seed_uganda_master

from .test_design_system_quality import _read


def _user(role, email):
    user = User.objects.create_user(
        email=email,
        name=role,
        roles=[role],
        active_role=role,
        password="test-password",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user


class PriorityWorkspaceTabTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_uganda_master(actor_id="test")

    def _tabs(self, html):
        import re

        rail = re.findall(r'role="tab"[^>]*>([^<]+)<', html)
        return [label.strip() for label in rail]

    def test_each_role_gets_the_views_it_has_and_no_others(self):
        cases = {
            # Runs the distribution, so Priorities opens the workspace.
            "ImpactAssessment": (
                "/target-distribution",
                ["Priority Setting", "Target Distribution"],
            ),
            "CountryDirector": (
                "/target-distribution",
                ["Priority Setting", "Target Distribution"],
            ),
            # §13's own workspace is this reader's third view.
            "Program Lead": (
                "/priorities",
                ["Priority Setting", "Target Distribution", "My Team"],
            ),
            "RegionalVicePresident": (
                "/priorities",
                ["Priority Setting", "Target Distribution"],
            ),
            "HumanResources": (
                "/priorities",
                ["Priority Setting", "Target Distribution"],
            ),
            # A CCEO reads the master and nothing else. One tab is not a tab
            # bar, so this page carries no rail at all.
            "CCEO": ("/priorities", []),
        }
        for role, (url, expected) in cases.items():
            with self.subTest(role=role):
                self.client.force_login(_user(role, f"{role.replace(' ', '')}@tab.test"))
                response = self.client.get(f"{url}?fy=2027")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self._tabs(response.content.decode()), expected)

    def test_the_setting_view_opens_for_the_roles_the_owner_added(self):
        for role in ("ImpactAssessment", "Program Lead"):
            with self.subTest(role=role):
                self.client.force_login(_user(role, f"{role.replace(' ', '')}@set.test"))
                response = self.client.get("/strategic-priorities?fy=2027")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Priority Setting Dashboard", response.content.decode())

    def test_a_role_with_no_priority_surface_is_still_turned_away(self):
        """Joining pages did not widen who may read them."""

        self.client.force_login(_user("Accountant", "acct@tab.test"))
        for url in ("/strategic-priorities", "/target-distribution", "/priorities"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotEqual(response.status_code, 200)

    def test_a_tab_press_returns_the_rail_and_the_panel_only(self):
        """What makes it a tab: htmx asks for the shell's CONTENT, and gets a
        fragment rather than a page to nest inside the one already open."""

        self.client.force_login(_user("CountryDirector", "cd@press.test"))
        response = self.client.get(
            "/strategic-priorities?fy=2027",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET=SHELL_ID,
        )
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<html", html)
        self.assertIn("data-dashboard-views", html)
        self.assertIn(f'id="{PANEL_ID}"', html)
        # The shell wrapper is the element being swapped INTO; sending a second
        # one would nest a shell inside itself on every press.
        self.assertNotIn("data-dashboard-view-shell", html)
        self.assertIn("Priority Setting Dashboard", html)

    def test_the_year_travels_with_the_press(self):
        self.client.force_login(_user("CountryDirector", "cd@fy.test"))
        html = self.client.get("/target-distribution?fy=2026").content.decode()
        self.assertIn("/strategic-priorities?fy=2026", html)

    def test_one_view_means_no_rail(self):
        class _Request:
            GET = {}

            def __init__(self, user):
                self.user = user

        cceo = _user("CCEO", "cceo@rail.test")
        self.assertIsNone(
            priority_workspace_tabs(
                _Request(cceo),
                active="distribution",
                view_template="partials/priorities/master_view.html",
            )
        )


class PriorityWorkspaceMarkupTest(SimpleTestCase):
    def test_every_host_page_renders_the_shared_rail_and_its_own_view(self):
        pages = {
            "templates/pages/hr/priority_configuration.html": "setting_view.html",
            "templates/pages/hr/target_distribution.html": "distribution_view.html",
            "templates/pages/hr/priorities_master.html": "master_view.html",
            "templates/pages/hr/team_target_distribution.html": "team_view.html",
        }
        for page, view in pages.items():
            with self.subTest(page=page):
                source = _read(page)
                self.assertIn('{% if dashboard_tabs %}{% include "partials/dashboards/_view_tabs.html" %}', source)
                self.assertIn(f'{{% include "partials/priorities/{view}" %}}', source)
                # Both assets travel with every host page: a tab press swaps the
                # panel, not the document head, so a view entered from another
                # tab would otherwise arrive unstyled and unbound.
                self.assertIn('partials/priorities/_workspace_css.html', source)
                self.assertIn('partials/priorities/_workspace_scripts.html', source)

    def test_each_view_carries_its_own_wrapper_inside_the_panel(self):
        """The stylesheet hooks are scoped to these classes, and the panel is
        what travels — a class left on the host page styles only the view you
        happened to enter from."""

        self.assertIn(
            '<div class="ia-master space-y-5"',
            _read("templates/partials/priorities/distribution_view.html"),
        )
        self.assertIn(
            '<div class="ia-master team-distribution-workspace space-y-5"',
            _read("templates/partials/priorities/team_view.html"),
        )
        self.assertIn(
            '<div class="priority-setting-workspace space-y-5"',
            _read("templates/partials/priorities/setting_view.html"),
        )
        for page in (
            "templates/pages/hr/target_distribution.html",
            "templates/pages/hr/team_target_distribution.html",
        ):
            self.assertNotIn('class="edify-page-canvas ia-master', _read(page))

    def test_the_workspace_scripts_survive_a_swap(self):
        """They sit outside the panel, so they load once — and they look their
        elements up when used, because a press replaces every one of them."""

        source = _read("templates/partials/priorities/_workspace_scripts.html")
        self.assertIn("document.addEventListener('htmx:afterSettle', bind);", source)
        self.assertIn("document.addEventListener('htmx:afterSettle', bindTeam);", source)
        self.assertIn("const dialogEl = () => document.getElementById('team-allocation-dialog');", source)
        self.assertIn("const distributionDialogEl = () => el('ia-distribution-dialog');", source)
        # Bound once per element, so a second settle does not double a click.
        self.assertIn("if (!node || node.dataset.iaBound === type) return;", source)
        self.assertIn("if (!node || node.dataset.teamBound === type) return;", source)

    def test_the_sidebar_lost_the_duplicate_links(self):
        nav = _read("apps/core/navigation.py")
        # Exactly one navigation item still points at each folded route, and it
        # is not a sidebar entry — the rail builds those URLs itself.
        self.assertNotIn('"url": "/strategic-priorities",', nav)
        self.assertNotIn('"url": "/target-distribution/team",', nav)
        # The routes and their page keys are untouched: this removed links, not
        # pages.
        self.assertIn('"strategic_priorities": {RVP, CD, HR, ADMIN, IA, PL},', nav)
        self.assertIn('"team_target_distribution": {PL, ADMIN},', nav)

    def test_a_held_panel_is_keyed_by_route_when_there_is_no_view_parameter(self):
        """The dashboards' views are one path with `?view=`; these are three
        real routes, so the path is what names the view."""

        source = _read("static/js/view-panels.js")
        self.assertIn('return parsed.searchParams.get("view") || parsed.pathname;', source)
