"""The Team Performance page: the FY27 Weekly Report, its sheets as tabs.

Owner, 2026-10-20: "Team performance page, replace everything there with" the
workbook; Executive Summary is the first tab and the default; the HR
workspace keeps its own "Performance Reviews" entry; leads read every region,
a CCEO their own row; the period filter (week, month, Q1–Q4) shows only where
a tab reads a period.
"""

from __future__ import annotations

from datetime import date

from apps.accounts.models import StaffSupervisorAssignment
from apps.core.navigation import build_sidebar_for_user
from apps.team_performance.test_ledger import FY, LedgerFixture, make_officer

URL = "/team-performance/"
TABS = ("summary", "weekly", "milestones", "dashboard", "month", "core")


class TeamPerformancePageTest(LedgerFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lead = make_officer("lead@tp-page.test", "Program Lead")
        cls.director = make_officer("cd@tp-page.test", "CountryDirector")
        cls.hr = make_officer("hr@tp-page.test", "HumanResources")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james.staff_profile, supervisor=cls.lead.staff_profile
        )

    def page(self, user, **query):
        self.client.force_login(user)
        response = self.client.get(URL, {"fy": FY, **query})
        self.assertEqual(response.status_code, 200, query)
        return response.content.decode()

    def test_the_executive_summary_is_the_first_tab_and_the_default(self):
        body = self.page(self.lead)

        self.assertIn('data-team-performance="summary"', body)
        tabs = [body.index(f'data-tp-tab="{key}"') for key in TABS]
        self.assertEqual(tabs, sorted(tabs))

    def test_every_tab_opens_for_each_period(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        for tab in TABS:
            for period in ("week", "month", "quarter", "year"):
                body = self.page(self.director, tab=tab, period=period, month=2)
                self.assertIn(f'data-team-performance="{tab}"', body)

    def test_the_summary_tab_is_titled_by_its_month(self):
        body = self.page(self.lead, month=2)

        self.assertIn("November 2026 Summary", body)

    def test_the_period_filter_shows_only_where_a_tab_reads_a_period(self):
        self.assertIn('name="period"', self.page(self.lead, tab="summary"))
        month = self.page(self.lead, tab="month")
        self.assertNotIn('name="period"', month)
        self.assertIn('name="month"', month)
        core = self.page(self.lead, tab="core")
        self.assertNotIn('name="period"', core)
        self.assertNotIn('name="month"', core)

    def test_the_detailed_country_report_has_the_workbooks_columns(self):
        body = self.page(self.lead, tab="weekly", month=2)

        self.assertIn("Detailed Country Report", body)
        self.assertNotIn("Weekly Report – Country", body)
        self.assertNotIn(">Deadline<", body)
        self.assertIn("Monthly Performance · November 2026", body)
        for q in (1, 2, 3, 4):
            self.assertIn(f"Q{q} Cumulative Performance", body)
        self.assertIn("Annual Performance against Annual Target", body)
        # Planned beside Target and Achieved in every band, each band its own
        # column colour (owner, 2026-10-20).
        self.assertEqual(body.count(">Planned</th>"), 6)
        for band in ("m", "q1", "q2", "q3", "q4", "y"):
            self.assertIn(f'data-tp-band="{band}"', body)
        # The month is the tab's one period: no Weekly/Quarterly picker.
        self.assertNotIn('name="period"', body)
        self.assertIn('name="month"', body)

    def test_a_lead_reads_every_region(self):
        body = self.page(self.lead)

        self.assertIn('data-tp-team="Northern"', body)
        self.assertIn('data-tp-team="No Programme Lead"', body)

    def test_a_cceo_reads_only_their_own_row(self):
        body = self.page(self.mary, tab="month")

        self.assertIn(f'data-tp-officer="{self.mary.staff_profile.id}"', body)
        self.assertNotIn(f'data-tp-officer="{self.james.staff_profile.id}"', body)
        self.assertNotIn("National Total", body)

    def test_a_cceo_opens_their_own_deep_dive(self):
        body = self.page(
            self.mary, tab="dashboard", view="deep", officer=self.james.staff_profile.id
        )

        self.assertIn(f'data-tp-deep="{self.mary.staff_profile.id}"', body)
        self.assertNotIn(self.james.staff_profile.id, body)

    def test_the_dashboard_has_the_live_sheets_five_views(self):
        for view in ("cceos", "deep", "milestones", "regions", "grid"):
            body = self.page(self.lead, tab="dashboard", view=view)
            self.assertIn(f'data-tp-dashboard="{view}"', body)
        cards = self.page(self.lead, tab="dashboard")
        self.assertIn(f'data-tp-officer-card="{self.james.staff_profile.id}"', cards)
        northern = self.page(self.lead, tab="dashboard", view="grid", region="Northern")
        self.assertIn(f'data-tp-grid="{self.james.staff_profile.id}"', northern)
        self.assertNotIn(f'data-tp-grid="{self.mary.staff_profile.id}"', northern)

    def test_a_figure_the_records_cannot_give_reads_not_tracked(self):
        body = self.page(self.lead, tab="weekly")
        church = body[body.index('data-tp-row="church_engagement"') :]

        self.assertIn("Not tracked", church[: church.index("</tr>")])

    def test_the_summary_charts_recruitment_by_region_and_by_lead_apart(self):
        self.client.force_login(self.lead)

        body = self.client.get(URL).content.decode()

        # One row per target area, its region chart and its Programme Lead
        # chart side by side.
        rows = body.count("data-tp-area-row=")
        self.assertGreater(rows, 40)
        self.assertEqual(body.count('data-tp-chart="region"'), rows)
        self.assertEqual(body.count('data-tp-chart="lead"'), rows)
        self.assertIn("Client Schools Trained by Programme Lead", body)
        self.assertIn("Core Visit 1 by Programme Lead", body)
        # Each chart has its figures as a table beneath it (owner,
        # 2026-10-21: "all the graphs in the executive summary is accompanied
        # by the tables below or above each graph").
        self.assertEqual(body.count("data-tp-chart-table"), 2 * rows)

    def test_core_visits_and_trainings_are_one_table_visits_first(self):
        """Owner, 2026-10-21: "merge core visits and training tables into 1
        with visits on the left and training on the right"."""
        self.client.force_login(self.lead)

        body = self.client.get(URL, {"tab": "core"}).content.decode()

        self.assertEqual(body.count("<table"), 1)
        visits = body.index('data-tp-core-kind="visit"')
        self.assertLess(visits, body.index('data-tp-core-kind="training"'))

    def test_a_malformed_link_still_opens_the_report(self):
        self.client.force_login(self.lead)
        for query in ({"fy": "abc"}, {"fy": "99999"}, {"month": "99", "week": "x"}):
            self.assertEqual(self.client.get(URL, query).status_code, 200, query)

    def test_roles_outside_the_report_are_refused(self):
        self.client.force_login(self.hr)

        response = self.client.get(URL)

        self.assertNotContains(
            response, "data-team-performance", status_code=response.status_code
        )

    def test_the_lead_has_team_performance_and_performance_reviews(self):
        items = {
            item["label"]: item["url"]
            for section in build_sidebar_for_user(self.lead, "/dashboard")
            for item in section["items"]
        }

        self.assertEqual(items["Team Performance"], "/team-performance/")
        self.assertEqual(items["Performance Reviews"], "/performance-reviews")

    def test_the_country_director_and_a_cceo_have_the_entry(self):
        for user in (self.director, self.mary):
            labels = [
                item["label"]
                for section in build_sidebar_for_user(user, "/dashboard")
                for item in section["items"]
            ]
            self.assertEqual(labels.count("Team Performance"), 1, user.email)
