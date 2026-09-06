"""The two-view home dashboards: Map | Operations.

Owner, 2026-09-05: the country map moved from Analytics to the home
dashboards. Every leadership dashboard (Country Director, Program Lead,
Regional Vice President, Internal Auditor) opens on the map with the
operations one tab away; the Accountant, HR, Special Projects and Admin
open on their work with the map one tab away; the CCEO opens on the week
with the map second. The header, KPI strip
and attention band stay fixed above the rail, a tab swaps only the view
container, and the platform remembers the last view a person chose.
"""

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.frontend.views.dashboard_view_state import VIEW_COOKIE_PREFIX

ROOT = Path(__file__).resolve().parents[2]
MAP_INCLUDE = 'include "partials/analytics/regional_performance.html"'
RAIL_INCLUDE = 'include "partials/dashboards/_view_tabs.html"'


def _read(relative: str) -> str:
    return ROOT.joinpath(relative).read_text(encoding="utf-8")


def _user(email: str, role: str):
    return get_user_model().objects.create_user(
        email=email,
        name=email.split("@")[0].replace(".", " ").title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class DashboardViewSourceTest(TestCase):
    """What the templates say, independent of data."""

    def test_the_map_left_the_analytics_workspace_for_the_dashboards(self):
        for panel in (
            "templates/partials/analytics/kpi_cards.html",
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
        ):
            with self.subTest(panel=panel):
                self.assertNotIn(MAP_INCLUDE, _read(panel))
        for view in (
            "templates/partials/dashboards/cd/map_view.html",
            "templates/partials/dashboards/pl/map_view.html",
            "templates/partials/dashboards/rvp/map_view.html",
            "templates/partials/ia/view.html",
            "templates/partials/finance/accountant_view.html",
        ):
            with self.subTest(view=view):
                self.assertIn(MAP_INCLUDE, _read(view))

    def test_the_fixed_part_stays_above_the_rail(self):
        cd = _read("templates/partials/dashboards/cd/body.html")
        self.assertLess(cd.index("Country pulse"), cd.index("Leadership Attention"))
        self.assertLess(cd.index("Leadership Attention"), cd.index(RAIL_INCLUDE))
        pl = _read("templates/partials/dashboards/pl/body.html")
        self.assertLess(pl.index("Team pulse"), pl.index("Leadership Attention"))
        self.assertLess(pl.index("Leadership Attention"), pl.index(RAIL_INCLUDE))
        rvp = _read("templates/pages/dashboards/rvp.html")
        self.assertLess(rvp.index("Regional pulse"), rvp.index("Leadership Attention"))
        self.assertLess(rvp.index("Leadership Attention"), rvp.index(RAIL_INCLUDE))
        ia_page = _read("templates/pages/ia/analytics_dashboard.html")
        ia_body = _read("templates/partials/ia/dashboard_body.html")
        self.assertLess(
            ia_page.index("Verification workload"), ia_page.index("partials/ia/dashboard_body.html")
        )
        self.assertIn(RAIL_INCLUDE, ia_body)

    def test_each_map_view_keeps_its_table_under_the_map(self):
        cd = _read("templates/partials/dashboards/cd/map_view.html")
        self.assertLess(cd.index(MAP_INCLUDE), cd.index("data-cd-geography"))
        pl = _read("templates/partials/dashboards/pl/map_view.html")
        self.assertLess(pl.index(MAP_INCLUDE), pl.index("data-pl-map-districts"))
        rvp = _read("templates/partials/dashboards/rvp/map_view.html")
        self.assertLess(rvp.index(MAP_INCLUDE), rvp.index("_region_ranking.html"))
        ia = _read("templates/partials/ia/view.html")
        self.assertLess(ia.index(MAP_INCLUDE), ia.index("_geography_cards.html"))

    def test_every_role_dashboard_carries_the_rail_and_a_map_view(self):
        """Owner, 2026-09-05: "are you sure all roles got the map". The CCEO's
        first tab is the week; HR, Special Projects and Admin open on their
        operations; every one of them has the map one tab away."""
        for page in (
            "templates/pages/dashboards/cceo.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/pages/dashboards/special_projects.html",
            "templates/pages/dashboards/main.html",
        ):
            with self.subTest(page=page):
                self.assertIn(RAIL_INCLUDE, _read(page))
        for view in (
            "templates/partials/dashboards/cceo/map_view.html",
            "templates/partials/dashboards/hr/map_view.html",
            "templates/partials/dashboards/special_projects/map_view.html",
            "templates/partials/dashboards/admin/map_view.html",
        ):
            with self.subTest(view=view):
                self.assertIn(MAP_INCLUDE, _read(view))
        cceo = _read("templates/pages/dashboards/cceo.html")
        self.assertLess(cceo.index("Week at a glance"), cceo.index(RAIL_INCLUDE))

    def test_the_verification_quality_tab_keeps_district_monitoring_without_a_rail(self):
        body = _read("templates/partials/ia/dashboard_body.html")
        self.assertIn("{% if ia_dashboard_tabs %}", body)
        self.assertIn('include "partials/ia/operations.html" with show_geography=True', body)
        operations = _read("templates/partials/ia/operations.html")
        self.assertIn(
            '{% if show_geography %}{% include "partials/ia/_geography_cards.html" %}{% endif %}',
            operations,
        )
        cards = _read("templates/partials/ia/_geography_cards.html")
        self.assertIn("Regional performance", cards)
        self.assertIn("District monitoring", cards)

    def test_the_rail_is_a_tablist_of_real_urls(self):
        rail = _read("templates/partials/dashboards/_view_tabs.html")
        self.assertIn('role="tablist"', rail)
        self.assertIn('role="tab"', rail)
        self.assertIn('href="{{ tab.url }}"', rail)
        self.assertIn('hx-target="#{{ dashboard_tabs.panel_id }}-shell"', rail)
        self.assertIn('id="{{ dashboard_tabs.panel_id }}-shell"', rail)
        self.assertIn('hx-push-url="true"', rail)

    def test_the_dashboards_load_the_map_stylesheet(self):
        for page in (
            "templates/pages/dashboards/cd.html",
            "templates/pages/dashboards/pl.html",
            "templates/pages/dashboards/rvp.html",
            "templates/pages/accounts/dashboard.html",
        ):
            with self.subTest(page=page):
                self.assertIn('include "partials/vendor/dashboard_map.html"', _read(page))
        self.assertIn("css/pages/analytics-dashboard.css", _read("templates/partials/vendor/dashboard_map.html"))
        # The IA page already loads it as an Analytics-family page.
        self.assertIn("css/pages/analytics-dashboard.css", _read("templates/pages/ia/analytics_dashboard.html"))


class DashboardViewRenderTest(TestCase):
    """What each role gets on their home dashboard."""

    def setUp(self):
        self.cd = _user("cd.view@edify.test", "CountryDirector")
        self.pl = _user("pl.view@edify.test", "Program Lead")
        self.rvp = _user("rvp.view@edify.test", "RegionalVicePresident")
        self.ia = _user("ia.view@edify.test", "ImpactAssessment")
        self.accountant = _user("accountant.view@edify.test", "Accountant")
        self.cceo = _user("cceo.view@edify.test", "CCEO")
        self.hr = _user("hr.view@edify.test", "HumanResources")
        self.coordinator = _user("coordinator.view@edify.test", "ProjectCoordinator")
        self.admin = _user("admin.view@edify.test", "Admin")

    def _get(self, user, url, **headers):
        self.client.force_login(user)
        return self.client.get(url, **headers)

    def test_leadership_dashboards_open_on_the_map(self):
        for user, url in (
            (self.cd, "/dashboard"),
            (self.pl, "/dashboard"),
            (self.rvp, "/dashboard"),
            (self.ia, "/ia/dashboard/"),
        ):
            with self.subTest(role=user.active_role):
                response = self._get(user, url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn("data-dashboard-views", html)
                self.assertIn("subregionMap()", html)
                self.assertIn('id="subregion-distribution-rows"', html)
                self.assertIn('aria-selected="true"', html)
                self.assertLess(html.index("Map"), html.index("Operations"))

    def test_the_accountant_opens_on_the_queue_with_the_map_one_tab_away(self):
        response = self._get(self.accountant, "/accounts")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-dashboard-views", html)
        self.assertNotIn("subregionMap()", html)
        self.assertIn('id="fund-filters-card"', html)
        html = self._get(self.accountant, "/accounts?view=map").content.decode()
        self.assertIn("subregionMap()", html)
        self.assertNotIn('id="fund-filters-card"', html)

    def test_the_remaining_roles_open_on_their_work_with_the_map_one_tab_away(self):
        for user, first in (
            (self.cceo, "Week"),
            (self.hr, "Operations"),
            (self.coordinator, "Operations"),
            (self.admin, "Operations"),
        ):
            with self.subTest(role=user.active_role):
                response = self._get(user, "/dashboard")
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn("data-dashboard-views", html)
                self.assertNotIn("subregionMap()", html)
                selected = re.findall(r'id="dashboard-tab-(\w+)"\s+role="tab"\s+aria-selected="true"', html)
                self.assertEqual(selected, ["operations"])
                self.assertLess(html.index(f">{first}</a>"), html.index(">Map</a>"))
                html = self._get(user, "/dashboard?view=map").content.decode()
                self.assertIn("subregionMap()", html)
                self.assertIn('id="subregion-distribution-rows"', html)

    def test_the_operations_view_carries_the_work(self):
        html = self._get(self.cd, "/dashboard?view=operations").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("Country Program Leads Performance", html)
        self.assertIn("data-cd-verification", html)
        html = self._get(self.pl, "/dashboard?view=operations").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("CCEO Performance", html)
        html = self._get(self.rvp, "/dashboard?view=operations").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("Country Directors Performance", html)
        self.assertIn("Strategy Notes", html)
        html = self._get(self.ia, "/ia/dashboard/?view=operations").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("CCEO and Program Lead performance", html)
        self.assertNotIn("District monitoring</h3>", html)

    def test_the_map_view_keeps_the_role_table_under_the_map(self):
        html = self._get(self.cd, "/dashboard?view=map").content.decode()
        self.assertLess(html.index("subregionMap()"), html.index("data-cd-geography"))
        html = self._get(self.rvp, "/dashboard?view=map").content.decode()
        self.assertLess(html.index("subregionMap()"), html.index("Region Performance Ranking"))
        html = self._get(self.ia, "/ia/dashboard/?view=map").content.decode()
        self.assertLess(html.index("subregionMap()"), html.index("District monitoring</h3>"))

    def test_a_chosen_view_is_remembered_per_role(self):
        response = self._get(self.cd, "/dashboard?view=operations")
        cookie = response.cookies.get(f"{VIEW_COOKIE_PREFIX}cd")
        self.assertIsNotNone(cookie)
        self.assertEqual(cookie.value, "operations")
        html = self.client.get("/dashboard").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("Country Program Leads Performance", html)
        # A view nobody asked for sets no cookie.
        response = self.client.get("/dashboard?view=map")
        self.assertEqual(response.cookies[f"{VIEW_COOKIE_PREFIX}cd"].value, "map")
        response = self._get(self.pl, "/dashboard")
        self.assertNotIn(f"{VIEW_COOKIE_PREFIX}pl", response.cookies)

    def test_a_tab_click_swaps_the_rail_and_the_view_together(self):
        """The rail travels with the panel, so the highlight can never lag:
        swapping the panel alone left both tabs painted selected.

        The response is the shell's CONTENT — rail and panel, no shell
        wrapper — swapped into the shell already on the page. A response
        that carried the wrapper nested a new shell inside the old one on
        every click (2026-09-06)."""
        for user, url, target, active in (
            (self.cd, "/dashboard?view=operations", "cd-dashboard-view", "operations"),
            (self.pl, "/dashboard?view=map", "pl-dashboard-view", "map"),
            (self.rvp, "/dashboard?view=operations", "rvp-dashboard-view", "operations"),
            (self.ia, "/ia/dashboard/?view=map", "ia-dashboard-view", "map"),
            (self.accountant, "/accounts?view=map", "accountant-dashboard-view", "map"),
        ):
            with self.subTest(target=target):
                response = self._get(
                    user, url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET=f"{target}-shell"
                )
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertNotIn("<html", html)
                self.assertNotIn(f'id="{target}-shell"', html)
                self.assertIn("data-dashboard-views", html)
                selected = re.findall(r'id="dashboard-tab-(\w+)"\s+role="tab"\s+aria-selected="true"', html)
                self.assertEqual(selected, [active])
                self.assertIn(f'id="{target}" role="tabpanel"', html)

    def test_the_filter_forms_carry_the_view(self):
        html = self._get(self.cd, "/dashboard?view=operations").content.decode()
        self.assertIn('name="view" value="operations"', html)
        html = self._get(self.pl, "/dashboard?view=operations").content.decode()
        self.assertIn('name="view" value="operations"', html)
        html = self._get(self.rvp, "/dashboard?view=operations").content.decode()
        self.assertIn('name="view" value="operations"', html)

    def test_the_analytics_overview_no_longer_draws_the_map(self):
        html = self._get(self.cd, "/analytics").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertIn("Geographic priorities", html)
        html = self._get(self.ia, "/analytics/verification-quality").content.decode()
        self.assertNotIn("subregionMap()", html)
        self.assertNotIn("data-dashboard-views", html)
        self.assertIn("District monitoring</h3>", html)
