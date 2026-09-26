"""Links and controls are drawn only for readers their target page admits.

A role-by-role crawl (2026-09-14) found pages that linked readers to pages
that refuse them, so a click landed on "Access Denied":

- /budget offered "Weekly Advance Request" to the RVP, who cannot open
  /fund-requests/weekly;
- the Analytics "Recommended Strategy" card offered "View Action Plan"
  (/planning) to the RVP, the Regional Lead and HR;
- /ssa renders the Analytics shell for partner, BT and MFI readers, and its
  header offered Download CSV, Send to Inbox and Customize, all Analytics
  routes those roles cannot open;
- the Admin dashboard's cluster table linked every cluster to
  href="/clusters/" because its rows carried no id;
- the Work Plan's row action and "View details" sent the RVP and HR to
  /my-plan/<id>, which they cannot open.

Every gate goes through the shared `can_open` filter
(apps.core.permissions.can_open_url), so these tests read the real page
permissions rather than a copy of them.
"""

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.frontend.work_plan_tables import grouped_tables

ANALYTICS_CONTROLS = (
    'href="/analytics/export',
    'hx-get="/analytics/schedule-report',
    'hx-get="/analytics/customize-dashboard"',
)


def _viewer(role):
    """A request user carrying only what the page gate reads."""
    return SimpleNamespace(is_authenticated=True, active_role=role, roles=[role])


def _render(template, role, context=None):
    request = RequestFactory().get("/")
    request.user = _viewer(role)
    return render_to_string(template, {**(context or {}), "request": request})


def _user(email, role):
    return get_user_model().objects.create_user(
        email=email,
        name=f"{role} reader",
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class RecommendedStrategyLinkTest(SimpleTestCase):
    TEMPLATE = "partials/analytics/recommended_insights.html"

    def test_readers_planning_refuses_see_the_strategy_without_the_link(self):
        for role in ("RegionalVicePresident", "RegionalProgramLead", "HumanResources"):
            with self.subTest(role=role):
                html = _render(self.TEMPLATE, role, {"insights": []})
                self.assertIn("Recommended Strategy", html)
                self.assertNotIn("View Action Plan", html)
                self.assertNotIn('href="/planning"', html)

    def test_readers_who_plan_keep_the_link(self):
        for role in ("CountryDirector", "Program Lead", "Admin"):
            with self.subTest(role=role):
                html = _render(self.TEMPLATE, role, {"insights": []})
                self.assertIn('href="/planning"', html)
                self.assertIn("View Action Plan", html)


class AdminClusterTableLinksTest(SimpleTestCase):
    TEMPLATE = "partials/dashboards/admin/operations.html"

    def _row(self, **extra):
        return {
            "name": "Kasese North",
            "avg_ssa": 6.1,
            "status": "Good",
            "status_class": "s-green",
            **extra,
        }

    def test_each_cluster_links_to_its_own_profile(self):
        html = _render(
            self.TEMPLATE, "Admin", {"cluster_performance": [self._row(id="cl-1")]}
        )
        self.assertIn('href="/clusters/cl-1"', html)
        self.assertNotIn('href="/clusters/"', html)

    def test_a_row_without_an_id_is_plain_text_not_a_bare_link(self):
        html = _render(self.TEMPLATE, "Admin", {"cluster_performance": [self._row()]})
        self.assertIn("Kasese North", html)
        self.assertNotIn('href="/clusters/"', html)

    def test_a_reader_the_cluster_profile_refuses_gets_the_name_only(self):
        html = _render(
            self.TEMPLATE,
            "Accountant",
            {"cluster_performance": [self._row(id="cl-1")]},
        )
        self.assertIn("Kasese North", html)
        self.assertNotIn('href="/clusters/cl-1"', html)


class WorkPlanRowLinksTest(SimpleTestCase):
    TEMPLATE = "partials/work_plan/detail_tables.html"

    def _tables(self, action_url="/my-plan/act-1", action_text="View"):
        row = {
            "id": "act-1",
            "detail_group": "non_school",
            "name": "Quarterly programme review",
            "date_label": "12 Sep",
            "detail_venue": "Country office",
            "cost": 0,
            "delivery_status": "Planned",
            "delivery_status_tone": "neutral",
            "status_label": "Planned",
            "table_action": {
                "text": action_text,
                "url": action_url,
                "description": "",
            },
        }
        return {"detail_tables": grouped_tables([row]), "period_label": "Q4"}

    def test_readers_activity_records_refuse_get_no_record_links(self):
        for role in ("RegionalVicePresident", "HumanResources"):
            with self.subTest(role=role):
                html = _render(self.TEMPLATE, role, self._tables())
                self.assertNotIn('href="/my-plan/', html)
                self.assertNotIn("View details", html)
                self.assertIn("No action available", html)

    def test_each_control_is_gated_on_its_own_route(self):
        """A message the reader may compose stays when the record link goes."""
        html = _render(
            self.TEMPLATE,
            "HumanResources",
            self._tables(
                action_url="/messages/new?context_type=activity&context_id=act-1",
                action_text="Send to Jane",
            ),
        )
        self.assertIn("Send to Jane", html)
        self.assertNotIn("View details", html)
        self.assertNotIn("No action available", html)
        # One control left is its own button, not a one-item Actions menu.
        self.assertNotIn("data-row-actions", html)

    def test_readers_who_open_records_get_the_record_once(self):
        """A row whose action is View already opens the record; it is not
        offered a second time as View details (2026-09-26)."""
        for role in ("CountryDirector", "Program Lead", "Admin"):
            with self.subTest(role=role):
                html = _render(self.TEMPLATE, role, self._tables())
                self.assertEqual(html.count('href="/my-plan/act-1"'), 1)
                self.assertNotIn("View details", html)
                self.assertNotIn("No action available", html)
                self.assertNotIn("data-row-actions", html)

    def test_a_different_action_and_the_record_are_one_actions_menu(self):
        for role in ("CountryDirector", "Program Lead", "Admin"):
            with self.subTest(role=role):
                html = _render(
                    self.TEMPLATE,
                    role,
                    self._tables(
                        action_url="/messages/new?context_type=activity&context_id=act-1",
                        action_text="Send to Jane",
                    ),
                )
                # Both sit in the row's one Actions menu (owner, 2026-09-26).
                self.assertEqual(html.count("data-row-actions"), 1)
                self.assertIn(
                    'aria-label="Actions for Quarterly programme review"', html
                )
                self.assertEqual(html.count('role="menuitem"'), 2)
                self.assertIn("Send to Jane", html)
                self.assertIn(
                    'role="menuitem" href="/my-plan/act-1">View details', html
                )


class LinkGatePagesTest(TestCase):
    """The same gates through the real views, where the context is the view's."""

    def test_rvp_budget_has_no_weekly_advance_request_link(self):
        self.client.force_login(_user("rvp-gate@edify.test", "RegionalVicePresident"))
        response = self.client.get("/budget?fy=2026&period=month")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/fund-requests/weekly"')

    def test_country_director_budget_keeps_the_weekly_advance_request_link(self):
        self.client.force_login(_user("cd-gate@edify.test", "CountryDirector"))
        response = self.client.get("/budget?fy=2026&period=month")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/fund-requests/weekly"')

    def test_ssa_page_draws_no_analytics_controls_for_readers_analytics_refuses(self):
        for index, role in enumerate(
            (
                "PartnerFieldOfficer",
                "BusinessTransformationOfficer",
                "MfiLoanOfficer",
                "MfiPartnerAdmin",
            )
        ):
            with self.subTest(role=role):
                self.client.force_login(_user(f"ssa-gate-{index}@edify.test", role))
                response = self.client.get("/ssa")
                self.assertEqual(response.status_code, 200)
                for control in ANALYTICS_CONTROLS:
                    self.assertNotContains(response, control)

    def test_ssa_page_keeps_analytics_controls_for_analytics_readers(self):
        self.client.force_login(_user("ssa-gate-cd@edify.test", "CountryDirector"))
        response = self.client.get("/ssa")
        self.assertEqual(response.status_code, 200)
        for control in ANALYTICS_CONTROLS:
            self.assertContains(response, control)

    def test_admin_dashboard_links_each_cluster_by_its_id(self):
        from apps.clusters.models import Cluster
        from apps.geography.models import District, Region

        region = Region.objects.create(name="Gate Region")
        district = District.objects.create(name="Gate District", region=region)
        cluster = Cluster.objects.create(
            name="Gate Cluster", region=region, district=district
        )
        self.client.force_login(_user("admin-gate@edify.test", "Admin"))
        response = self.client.get("/dashboard?view=operations")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="/clusters/{cluster.id}"')
        self.assertNotContains(response, 'href="/clusters/"')
