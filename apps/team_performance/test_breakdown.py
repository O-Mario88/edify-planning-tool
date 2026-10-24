"""The Executive Summary's breakdown, per reader (owner, 2026-10-24).

"The Executive summary tab should have PL and his team members instead of
other PLs and Region. Instead of saying By Region, use By CCEO for PL and
for CCEO it should be by District ... for IA, CD, RPL, RVP, HR should by
region, By PL and By CCEO ... so that those can start by viewing the higher
level summary which can then be expanded into more details."
"""

from __future__ import annotations

from datetime import date

from apps.geography.models import District
from apps.schools.models import School
from apps.team_performance import breakdown
from apps.team_performance.test_report import ReportFixture


class BreakdownTest(ReportFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.kitgum = District.objects.create(name="Kitgum", region=cls.region)
        cls.far = cls.school("TP-KIT", cls.james, "client")
        School.objects.filter(pk=cls.far.pk).update(district=cls.kitgum)

    def labels(self, bd):
        return [column.label for column in bd.columns]

    def test_each_reader_breaks_down_by_their_own_levels(self):
        self.assertEqual(
            breakdown.levels(self.report().roster),
            (breakdown.REGION, breakdown.LEAD, breakdown.CCEO),
        )
        self.assertEqual(
            breakdown.levels(self.report(self.lead).roster), (breakdown.CCEO,)
        )
        self.assertEqual(
            breakdown.levels(self.report(self.james).roster), (breakdown.DISTRICT,)
        )

    def test_a_cceo_reads_their_portfolio_by_district(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        self.work("school_visit", self.far, day=date(2026, 11, 4))
        report = self.report(self.james)

        bd = breakdown.resolve(report)

        self.assertEqual(bd.level, breakdown.DISTRICT)
        self.assertEqual(self.labels(bd), ["Gulu", "Kitgum"])
        cells = [column.cell("client_visits_staff_n") for column in bd.columns]
        self.assertEqual([c["achieved"] for c in cells], [1, 1])
        # The districts add up to the CCEO's own total.
        own = report.summary_figures(report.home(), report.period.to_date)
        self.assertEqual(
            sum(c["achieved"] for c in cells), own["client_visits_staff_n"]
        )

    def test_a_lead_reads_their_team_member_by_member(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        report = self.report(self.lead)

        bd = breakdown.resolve(report, by=breakdown.REGION)

        # A Lead has no region view: their team, one column a member.
        self.assertEqual(bd.level, breakdown.CCEO)
        self.assertEqual(self.labels(bd), [self.james.name])
        self.assertEqual(bd.columns[0].cell("client_visits_staff_n")["achieved"], 1)
        self.assertIsNone(bd.columns[0].drill)

    def test_a_lead_who_holds_schools_is_a_column_of_their_own_team(self):
        self.school("TP-LEAD", self.lead, "client")

        bd = breakdown.resolve(self.report(self.lead))

        self.assertEqual(self.labels(bd), [self.lead.name, self.james.name])

    def test_leadership_starts_by_region_and_opens_into_leads_then_cceos(self):
        report = self.report()

        regions = breakdown.resolve(report)
        self.assertEqual(regions.level, breakdown.REGION)
        self.assertIn("Northern", self.labels(regions))
        north = next(c for c in regions.columns if c.label == "Northern")
        self.assertEqual(north.drill, {"by": "lead", "in_region": "Northern"})

        leads = breakdown.resolve(report, **north.drill)
        self.assertEqual(self.labels(leads), [self.lead.name, "No Programme Lead"])
        team = leads.columns[0]
        self.assertEqual(
            team.drill, {"by": "cceo", "in_lead": str(self.lead.staff_profile.id)}
        )

        cceos = breakdown.resolve(report, **team.drill)
        self.assertEqual(self.labels(cceos), [self.james.name])
        self.assertEqual(cceos.in_lead_label, self.lead.name)

        everyone = breakdown.resolve(report, by="cceo")
        self.assertEqual(self.labels(everyone), [self.james.name, self.mary.name])

    def test_a_region_nobody_reads_is_not_a_filter(self):
        bd = breakdown.resolve(self.report(), by="lead", in_region="Atlantis")

        self.assertEqual(bd.in_region, "")
        self.assertEqual(self.labels(bd), [self.lead.name, "No Programme Lead"])

    def test_the_summary_table_follows_the_breakdown(self):
        summary = self.report(self.lead).executive_summary()

        self.assertEqual(summary["breakdown"].level, breakdown.CCEO)
        area = summary["sections"][0][1][0]
        self.assertEqual([t["label"] for t in area["teams"]], [self.james.name])
        self.assertEqual(summary["width"], 5 + 3)

    def test_each_area_charts_its_level_beside_the_one_under_it(self):
        def levels(report, **picked):
            area = report.section_charts("Program Growth", **picked)[0]
            return [chart["level"] for chart in area["charts"]]

        report = self.report()
        self.assertEqual(levels(report), ["region", "lead"])
        self.assertEqual(levels(report, by="lead"), ["lead", "cceo"])
        self.assertEqual(levels(report, by="cceo"), ["cceo"])
        self.assertEqual(levels(self.report(self.lead)), ["cceo"])
        self.assertEqual(levels(self.report(self.james)), ["district"])

    def test_the_page_offers_the_levels_and_opens_a_region(self):
        self.client.force_login(self.director)
        html = self.client.get("/team-performance/?tab=summary").content.decode()
        self.assertIn('data-tp-by="region"', html)
        self.assertIn("by=lead&amp;in_region=Northern", html)

        html = self.client.get(
            "/team-performance/?tab=summary&by=lead&in_region=Northern"
        ).content.decode()
        self.assertIn(f'data-tp-team="{self.lead.name}"', html)
        self.assertIn("by=cceo&amp;in_lead=", html)
