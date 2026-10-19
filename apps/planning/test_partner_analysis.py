"""Partner Monitoring's Analysis: each Partner read by the profile engine.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... oversights (Partner monitoring, ...) and apply the
detailed analytics you built yesterday to all that apply". A Partner's row is
`profile_intelligence.build` over its assigned portfolio — the read its
profile makes — narrowed to the hand-overs the reader's own monitoring page
shows, so the country reads the profile's figures and a team its own part.
"""

from __future__ import annotations

from apps.analytics import profile_intelligence as engine
from apps.core.rbac import EdifyRole
from apps.planning import partner_analysis as analysis
from apps.planning.test_partner_oversight import PartnerOversightFixture


class AnalysisFixture(PartnerOversightFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.director = cls._staff(
            "director@p.test", "Direktor", EdifyRole.COUNTRY_DIRECTOR
        )[0]

    def row(self, rows, partner):
        return next(r for r in rows if r["id"] == partner.id)


class RowsTest(AnalysisFixture):
    def test_the_country_reads_each_partner_as_its_profile_does(self):
        self.schedule(self.assign())
        self.assign(cceo=self.rival_cceo, school=self.rival_school)
        self.assign(partner=self.other_partner)

        rows = analysis.partner_rows(self.director, fy=str(self.fy))

        x = self.row(rows, self.partner)
        profile = engine.build(engine.partner_scope(self.partner), str(self.fy))
        self.assertEqual(x["schools"], profile["portfolio"]["schools"])
        self.assertEqual(x["handovers"], profile["portfolio"]["handovers"])
        self.assertEqual(
            x["handovers"],
            {"assigned": 2, "awaiting": 1, "scheduled": 1, "completed": 0},
        )
        self.assertEqual(x["visits"]["planned"], 1)
        self.assertEqual(x["href"], f"/partners/{self.partner.id}?tab=overview")
        self.assertEqual({r["name"] for r in rows}, {"Partner X", "Partner Y"})

    def test_a_team_reads_only_the_hand_overs_its_page_shows(self):
        self.assign()
        self.assign(cceo=self.rival_cceo, school=self.rival_school)

        x = self.row(analysis.partner_rows(self.pl_user, fy=str(self.fy)), self.partner)

        self.assertEqual(x["schools"], 1)
        self.assertEqual(x["handovers"]["assigned"], 1)

    def test_a_partner_with_nothing_in_the_reader_s_lens_is_not_listed(self):
        self.assign()
        self.assign(
            cceo=self.rival_cceo, school=self.rival_school, partner=self.other_partner
        )

        rows = analysis.partner_rows(self.pl_user, fy=str(self.fy))

        self.assertEqual([r["name"] for r in rows], ["Partner X"])

    def test_a_hand_over_taken_back_leaves_the_partner_s_portfolio(self):
        self.assign(status="returned_to_staff")

        self.assertEqual(analysis.partner_rows(self.director, fy=str(self.fy)), [])

    def test_the_summary_is_its_rows_added_up(self):
        self.schedule(self.assign())
        self.assign(partner=self.other_partner, school=self.rival_school)

        rows = analysis.partner_rows(self.director, fy=str(self.fy))
        summary = analysis.summarise(rows)

        self.assertEqual(summary["subjects"], 2)
        self.assertEqual(summary["schools"], 2)
        self.assertEqual(summary["handovers"]["assigned"], 2)
        self.assertEqual(summary["handovers"]["scheduled"], 1)
        self.assertEqual(summary["handovers"]["awaiting"], 1)


class PageTest(AnalysisFixture):
    def test_the_analysis_lists_each_partner_with_its_profile_link(self):
        self.assign()
        self.client.force_login(self.pl_user)

        response = self.client.get("/partner-oversight/analysis")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("data-partner-analysis", body)
        self.assertIn("Partner X", body)
        self.assertIn(f"/partners/{self.partner.id}?tab=overview", body)
        for heading in ("Assigned", "Awaiting Date", "Scheduled", "Completed"):
            self.assertIn(heading, body)

    def test_monitoring_and_analysis_are_one_switch_apart(self):
        self.assign()
        self.client.force_login(self.pl_user)

        monitoring = self.client.get("/partner-oversight/").content.decode()
        analysed = self.client.get("/partner-oversight/analysis").content.decode()

        self.assertIn('href="/partner-oversight/analysis"', monitoring)
        self.assertIn('href="/partner-oversight/"', analysed)

    def test_a_reader_without_partner_monitoring_is_refused(self):
        hr = self._staff("hr@p.test", "Hana", EdifyRole.HUMAN_RESOURCES)[0]
        self.client.force_login(hr)

        response = self.client.get("/partner-oversight/analysis")

        # The page guard turns a role without the page away, as it does on
        # Monitoring; nothing of the analysis is drawn.
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"data-partner-analysis", response.content)
