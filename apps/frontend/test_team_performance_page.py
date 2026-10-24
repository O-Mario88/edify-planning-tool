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

    def test_a_lead_reads_their_team_and_the_director_everyone(self):
        """Owner, 2026-10-21: a PL sees their own team only; "IA, CD and Admin
        See Everyone grouped by PL"."""
        lead = self.page(self.lead)
        self.assertIn('data-tp-team="Lead"', lead)
        self.assertNotIn('data-tp-team="No Programme Lead"', lead)
        self.assertIn("Your team", lead)

        director = self.page(self.director)
        self.assertIn('data-tp-team="Lead"', director)
        self.assertIn('data-tp-team="No Programme Lead"', director)

    def test_a_lead_cannot_open_another_teams_officer(self):
        body = self.page(
            self.lead, tab="dashboard", view="deep", officer=self.mary.staff_profile.id
        )

        self.assertIn(f'data-tp-deep="{self.james.staff_profile.id}"', body)
        self.assertNotIn(self.mary.staff_profile.id, body)

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
        for view in ("cceos", "deep", "milestones", "leads", "grid"):
            body = self.page(self.lead, tab="dashboard", view=view)
            self.assertIn(f'data-tp-dashboard="{view}"', body)
        cards = self.page(self.lead, tab="dashboard")
        self.assertIn(f'data-tp-officer-card="{self.james.staff_profile.id}"', cards)
        northern = self.page(
            self.director, tab="dashboard", view="grid", lead=self.lead.staff_profile.id
        )
        self.assertIn(f'data-tp-grid="{self.james.staff_profile.id}"', northern)
        self.assertNotIn(f'data-tp-grid="{self.mary.staff_profile.id}"', northern)

    def test_a_figure_the_records_cannot_give_reads_not_tracked(self):
        body = self.page(self.lead, tab="weekly")
        church = body[body.index('data-tp-row="church_engagement"') :]

        self.assertIn("Not tracked", church[: church.index("</tr>")])

    def test_the_summary_charts_recruitment_by_region_and_by_lead_apart(self):
        self.client.force_login(self.lead)

        body = self.client.get(URL).content.decode()

        # Each section's charts load as the reader reaches them, so the page
        # stays within the platform's page-size budget (the route audit's
        # 10,000 elements) however many targets there are.
        placeholders = body.count("data-tp-charts-for=")
        self.assertGreater(placeholders, 5)
        self.assertEqual(body.count('hx-trigger="intersect once"'), placeholders)
        self.assertNotIn("data-tp-area-row=", body)

        visits = self.client.get(URL, {"tab": "summary", "charts": "Visits"})
        fragment = visits.content.decode()
        # One row per target area, its region chart and its Programme Lead
        # chart side by side.
        rows = fragment.count("data-tp-area-row=")
        self.assertGreater(rows, 5)
        self.assertEqual(fragment.count('data-tp-chart="region"'), rows)
        self.assertEqual(fragment.count('data-tp-chart="lead"'), rows)
        self.assertIn("Core Visit 1 by Programme Lead", fragment)
        self.assertNotIn("<html", fragment)
        # Each chart has its figures as a table beneath it (owner,
        # 2026-10-21: "all the graphs in the executive summary is accompanied
        # by the tables below or above each graph").
        self.assertEqual(fragment.count("data-tp-chart-table"), 2 * rows)
        trainings = self.client.get(
            URL, {"tab": "summary", "charts": "Client School Trainings"}
        ).content.decode()
        self.assertIn("Client Schools Trained by Programme Lead", trainings)

    def test_an_unknown_chart_section_is_refused(self):
        self.client.force_login(self.lead)

        response = self.client.get(URL, {"tab": "summary", "charts": "Nope"})

        self.assertEqual(response.status_code, 404)

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
        accountant = make_officer("acc@tp-page.test", "Accountant")
        self.client.force_login(accountant)

        response = self.client.get(URL)

        self.assertNotContains(
            response, "data-team-performance", status_code=response.status_code
        )

    def test_hr_reads_everyone(self):
        """Owner, 2026-10-23: HR is among the roles that read everyone's
        performance, on every tab."""
        for tab in TABS:
            body = self.page(self.hr, tab=tab)
            self.assertIn(f'data-team-performance="{tab}"', body)
        summary = self.page(self.hr)
        self.assertIn(f'data-tp-team="{self.lead.name}"', summary)
        self.assertIn('data-tp-team="No Programme Lead"', summary)
        self.assertIn("National Total", summary)
        grid = self.page(self.hr, tab="dashboard", view="grid")
        self.assertIn(f'data-tp-grid="{self.james.staff_profile.id}"', grid)
        self.assertIn(f'data-tp-grid="{self.mary.staff_profile.id}"', grid)

    def test_a_cceo_never_sees_another_officer_on_any_tab(self):
        """Owner, 2026-10-23: "CCEO can only see their performance only. The
        graphs and table … should be role specific"."""
        james = str(self.james.staff_profile.id)
        for tab in TABS:
            body = self.page(self.mary, tab=tab)
            self.assertNotIn(james, body, tab)
            self.assertNotIn(self.james.name, body, tab)
            self.assertNotIn("National Total", body, tab)
        for view in ("cceos", "deep", "milestones", "leads", "grid"):
            body = self.page(self.mary, tab="dashboard", view=view, officer=james)
            self.assertNotIn(james, body, view)
        fragment = self.page(self.mary, tab="summary", charts="Program Growth")
        self.assertNotIn(self.james.name, fragment)
        self.assertNotIn(f'data-tp-bar="{self.lead.name}"', fragment)

    def test_a_lead_never_sees_an_officer_outside_their_team_on_any_tab(self):
        """Owner, 2026-10-23: a Programme Lead sees "his performance and the
        performance of his cceo team members"."""
        mary = str(self.mary.staff_profile.id)
        for tab in TABS:
            body = self.page(self.lead, tab=tab)
            self.assertNotIn(mary, body, tab)
            self.assertNotIn(self.mary.name, body, tab)
            self.assertNotIn("No Programme Lead", body, tab)
        for scope in ("country", "region:none", mary):
            body = self.page(self.lead, tab="weekly", scope=scope)
            self.assertNotIn(mary, body, scope)
        fragment = self.page(self.lead, tab="summary", charts="Program Growth")
        self.assertNotIn(self.mary.name, fragment)
        self.assertNotIn("No Programme Lead", fragment)

    def test_the_master_ledger_reads_each_officers_region_not_their_lead(self):
        """Owner, 2026-10-23: "Officer Performance Master Ledger … Region
        Column should fetch the actual region not prgram lead"."""
        grid = self.page(self.director, tab="dashboard", view="grid")
        row = grid.split(f'data-tp-grid="{self.james.staff_profile.id}"')[1]
        row = row[: row.index("</tr>")]
        cells = [c.split("</td>")[0].strip() for c in row.split("<td>")[1:3]]
        # Region, then Programme Lead: the region is never the lead.
        self.assertEqual(cells, ["Northern", self.lead.name])

    def test_the_dashboard_filters_by_programme_lead_by_name(self):
        """Owner, 2026-10-23: "The region pills should be program lead pills.
        All, PL1, PL2 … And use the actual name of the PL"."""
        body = self.page(self.director, tab="dashboard")
        chips = body[body.index('aria-label="Programme Lead"') :]
        chips = chips[: chips.index("</nav>")]
        self.assertIn(">All <span>", chips)
        self.assertIn(f'data-tp-lead-chip="{self.lead.name}"', chips)
        self.assertIn('data-tp-lead-chip="No Programme Lead"', chips)
        self.assertNotIn('aria-label="Region"', body)
        self.assertNotIn("Northern", chips)

    def test_every_region_column_reads_the_officers_region(self):
        """Owner, 2026-10-23: "Fix all the places where region column has
        program leads"."""
        for view in ("cceos", "deep", "grid"):
            body = self.page(
                self.director,
                tab="dashboard",
                view=view,
                officer=self.james.staff_profile.id,
            )
            self.assertIn("Northern", body, view)
        core = self.page(self.director, tab="core")
        line = core.split(f'data-tp-core-line="{self.james.staff_profile.id}"')[1]
        self.assertIn("<td>Northern</td>", line[: line.index("</tr>")])

    def test_the_month_summary_groups_by_programme_lead_by_name(self):
        body = self.page(self.director, tab="month")
        self.assertIn(f'data-tp-region-total="{self.lead.name}"', body)
        self.assertIn(f"{self.lead.name} Total", body)

    def test_impact_assessment_is_every_milestones_responsible_lead(self):
        """Owner, 2026-10-23: "Strategic Milestones & Operational Trackers -
        Responsible Lead is the Impact Assessment"."""
        from apps.team_performance import strategic

        body = self.page(self.director, tab="milestones")
        self.assertEqual(body.count("<td>Impact Assessment</td>"), len(strategic.ROWS))
        for old in ("Quality Assurance", "M&amp;E Team", "Training Team"):
            self.assertNotIn(old, body)

    def test_hr_has_the_entry(self):
        labels = [
            item["label"]
            for section in build_sidebar_for_user(self.hr, "/dashboard")
            for item in section["items"]
        ]
        self.assertEqual(labels.count("Team Performance"), 1)

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
