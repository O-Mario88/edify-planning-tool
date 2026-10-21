"""The six tabs, built from one read for one reader.

Owner, 2026-10-20: leads read all four regions, a CCEO their own row; the
{Month} {Year} Summary is titled by the chosen month; the Executive Summary
sets the week's figures against the end of the week before.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_tz

from apps.accounts.models import StaffSupervisorAssignment
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.ssa.models import SsaRecord
from apps.team_performance.periods import ReportPeriod
from apps.team_performance.report import Report, status
from apps.team_performance.targets import Scope
from apps.team_performance.test_ledger import FY, LedgerFixture, make_officer

#: A Wednesday in the year's second month: last week ended on Sunday 15th.
TODAY = date(2026, 11, 18)


class ReportFixture(LedgerFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.lead = make_officer("lead@tp-report.test", "Program Lead")
        cls.director = make_officer("cd@tp-report.test", "CountryDirector")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james.staff_profile, supervisor=cls.lead.staff_profile
        )

    def report(self, user=None, month=2, kind="month") -> Report:
        period = ReportPeriod.resolve(FY, month, kind=kind, today=TODAY)
        return Report.build(user or self.director, period)


class RosterTest(ReportFixture):
    def test_ia_cd_and_admin_read_everyone_grouped_by_programme_lead(self):
        """Owner, 2026-10-21: "IA, CD and Admin See Everyone grouped by PL"."""
        for role in ("CountryDirector", "ImpactAssessment", "Admin"):
            reader = make_officer(f"{role.lower()}@tp-all.test", role)
            report = self.report(reader)

            labels = [r.label for r in report.roster.regions]
            self.assertEqual(labels, ["Northern", "No Programme Lead"], role)
            self.assertEqual(
                [o.name for o in report.roster.regions[0].officers], [self.james.name]
            )
            self.assertEqual(report.ledger.portfolio(None), 3, role)

    def test_a_lead_reads_only_their_own_team(self):
        """Owner, 2026-10-21: a PL "Sees own and team portfolio and
        performance only"."""
        report = self.report(self.lead)
        lead = str(self.lead.staff_profile.id)

        self.assertEqual([r.label for r in report.roster.regions], ["Northern"])
        self.assertEqual([o.name for o in report.roster.officers], [self.james.name])
        # Only the team's schools are read: James's two, not Mary's.
        self.assertEqual(report.ledger.portfolio(None), 2)
        self.assertEqual(report.home(), report.scope(f"region:{lead}")[2])
        self.assertEqual(
            [key for key, *_ in report.scopes()],
            [f"region:{lead}", str(self.james.staff_profile.id)],
        )
        self.assertIsNone(report.roster.officer(self.mary.staff_profile.id))

    def test_an_oversight_supervisor_does_not_move_a_cceo_out_of_their_region(self):
        """IA and RVP supervisor rows are oversight beside the direct line
        (`StaffSupervisorAssignment`): the CCEO stays under their PL."""
        ia = make_officer("ia@tp-report.test", "ImpactAssessment")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.james.staff_profile, supervisor=ia.staff_profile
        )

        report = self.report(self.lead)

        region = report.roster.region_of(self.james.staff_profile.id)
        self.assertEqual(region.key, str(self.lead.staff_profile.id))

    def test_a_cceos_team_row_is_their_own_not_their_teams(self):
        from apps.team_performance.targets import Target

        report = self.report(self.james)
        targets = {"region": 350, "officer": 25}
        report.book.target = lambda m, scope, eligible=None: Target(
            annual=targets.get(scope.kind), source="Allocation"
        )

        summary = report.executive_summary()

        self.assertEqual(
            summary["regions"][0]["figures"]["core_recruitment_target"], 25
        )
        recruit = summary["sections"][0][1][0]
        self.assertEqual([b["target"] for b in recruit["leads"]], [25])

    def test_a_cceo_reads_only_their_own_row(self):
        report = self.report(self.mary)

        self.assertTrue(report.roster.own)
        self.assertEqual([o.name for o in report.roster.officers], [self.mary.name])
        self.assertEqual(report.ledger.portfolio(None), 1)
        self.assertEqual(
            [key for key, *_ in report.scopes()], [self.mary.staff_profile.id]
        )


class SummaryTest(ReportFixture):
    def test_the_week_is_set_against_the_end_of_last_week(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 10))
        self.work("school_visit", self.other, day=date(2026, 11, 17))

        summary = self.report(kind="week").executive_summary()

        self.assertEqual(summary["before"]["client_visit_total"], 1)
        self.assertEqual(summary["now"]["client_visit_total"], 2)
        self.assertEqual(summary["change"]["client_visit_total"], 1)

    def test_each_region_and_the_country_carry_the_portfolio(self):
        summary = self.report().executive_summary()

        by_region = {r["label"]: r["figures"]["portfolio"] for r in summary["regions"]}
        self.assertEqual(by_region, {"Northern": 2, "No Programme Lead": 1})
        self.assertEqual(summary["now"]["portfolio"], 3)

    def test_the_month_summary_is_titled_by_its_month(self):
        summary = self.report(month=2).month_summary()

        self.assertEqual(summary["label"], "November 2026")
        north = summary["groups"][0]
        self.assertEqual(north["total"]["portfolio"], 2)
        self.assertEqual(north["lines"][0]["cols"]["active"], 2)


class WeeklyRowTest(ReportFixture):
    def test_a_row_reads_the_month_each_quarter_cumulative_and_the_year(self):
        """The workbook's columns: Monthly Performance, Q1–Q4 Cumulative
        Performance and Annual Performance against Annual Target."""
        SsaRecord.objects.create(
            school=self.client_school,
            fy=FY,
            quarter="Q1",
            date_of_ssa=datetime(2026, 11, 5, tzinfo=dt_tz.utc),
            verification_status="confirmed",
            uploaded_by="t",
        )
        november = dict(self.report(month=2).weekly(Scope.country()))
        row = next(
            r for r in november["Data Gathering"] if r["measure"].key == "ssa_client"
        )

        self.assertEqual(row["month"].achieved, 1)
        q1, q2, q3, q4 = row["quarters"]
        self.assertEqual(q1["cell"].achieved, 1)
        # Today is in November: the later quarters have not started.
        self.assertTrue(q2["future"] and q3["future"] and q4["future"])
        self.assertEqual(row["year"].achieved, 1)

        october = dict(self.report(month=1).weekly(Scope.country()))
        row = next(
            r for r in october["Data Gathering"] if r["measure"].key == "ssa_client"
        )
        self.assertEqual(row["month"].achieved, 0)
        self.assertEqual(row["year"].achieved, 1)

    def test_a_row_sets_the_plan_beside_target_and_achieved(self):
        """Owner, 2026-10-20: "a Planned column" from the training and visit
        plans; the annual band reads the whole year's plan."""
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        self.work(
            "school_visit", self.other, day=date(2026, 11, 20), status="scheduled"
        )
        self.work("school_visit", self.other, day=date(2027, 2, 10), status="scheduled")

        sections = dict(self.report(month=2).weekly(Scope.country()))
        row = next(
            r for r in sections["Visits"] if r["measure"].key == "client_visit_total"
        )

        self.assertEqual((row["month"].planned, row["month"].achieved), (2, 1))
        q1, q2, _q3, _q4 = row["quarters"]
        self.assertEqual(q1["cell"].planned, 2)
        # Q2 has not started; the visit booked in it is already planned.
        self.assertTrue(q2["future"])
        self.assertEqual(q2["planned"], 2)
        self.assertEqual((row["year"].planned, row["year"].achieved), (2, 1))
        ssa = next(
            r for r in sections["Data Gathering"] if r["measure"].key == "ssa_client"
        )
        self.assertIsNone(ssa["year"].planned)

    def test_a_figure_the_records_cannot_give_is_not_a_zero(self):
        sections = dict(self.report().weekly(Scope.country()))
        church = next(
            r
            for r in sections["Program Growth"]
            if r["measure"].key == "church_engagement"
        )

        self.assertIsNone(church["year"].achieved)


class CorePackageTabTest(ReportFixture):
    def test_each_school_counts_at_its_number_of_visits(self):
        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        for n, day in ((1, date(2026, 10, 10)), (2, date(2026, 11, 2))):
            visit = self.work("school_visit", self.core, day=day)
            CoreActivitySlot.objects.create(
                id=f"cslot-TP-CORE-v{n}-{FY}",
                core_plan=plan,
                school_id="TP-CORE",
                intervention="leadership",
                activity_type="visit",
                sequence_number=n,
                status="ia_verified",
                activity_id=visit.id,
            )

        package = self.report().core_package()
        james = next(
            r for r in package["lines"] if r["officer"].name == self.james.name
        )

        self.assertEqual(james["core"], 1)
        self.assertEqual(james["visit"]["two"], 1)
        self.assertEqual(james["visit"]["done"], 2)
        self.assertEqual(james["visit"]["expected"], 4)
        self.assertEqual(james["visit"]["pct"], 50.0)


class PeriodTest(ReportFixture):
    def test_the_annual_period_is_the_whole_financial_year(self):
        period = ReportPeriod.resolve(FY, kind="year", today=TODAY)

        self.assertEqual(period.span, (date(2026, 10, 1), date(2027, 10, 1)))
        self.assertEqual(period.months, tuple(range(1, 13)))
        self.assertEqual(period.last_month, 12)
        self.assertEqual(period.label, "FY2027 (Oct 2026–Sep 2027)")
        # The year to date stops at today; before the year there is nothing.
        self.assertEqual(period.to_date, (date(2026, 10, 1), date(2026, 11, 19)))
        self.assertEqual(period.before, (date(2026, 10, 1), date(2026, 10, 1)))


class StatusTest(ReportFixture):
    def test_the_workbooks_status_rule(self):
        self.assertEqual(status(100), "Achieved")
        self.assertEqual(status(100, running=True), "On Track")
        self.assertEqual(status(80), "Progressing")
        self.assertEqual(status(10), "Needs Attention")
        self.assertEqual(status(None), "")

    def test_the_dashboard_adds_the_summarys_columns(self):
        """The live dashboard's figures: visits are the Core schools at each
        package step plus the non-core schools visited; SSA reviews are the
        Core (Yr 1–3) and client SSAs."""
        self.work("school_visit", self.client_school, day=date(2026, 11, 10))
        SsaRecord.objects.create(
            school=self.client_school,
            fy=FY,
            quarter="Q1",
            date_of_ssa=datetime(2026, 11, 5, tzinfo=dt_tz.utc),
            verification_status="confirmed",
            uploaded_by="t",
        )
        report = self.report()
        f = report.officer_figures(Scope.officer(self.james.staff_profile.id))

        self.assertEqual((f["portfolio"], f["visits_noncore"], f["visits"]), (2, 1, 1))
        self.assertEqual((f["ssa_client"], f["ssa"]), (1, 1))

        board = report.cceo_board(region="Northern")
        self.assertEqual([c["officer"].name for c in board["cards"]], [self.james.name])
        self.assertEqual(board["total"]["visits"], 1)


class TrackerTest(ReportFixture):
    def test_every_tracker_opens_a_page(self):
        from django.urls import Resolver404, resolve

        from apps.team_performance import measures
        from apps.team_performance.report import TRACKERS, _tracker

        urls = {url for url, _ in TRACKERS.values()} | {_tracker([])[0]}
        for url in urls:
            try:
                resolve(url)
            except Resolver404:
                self.fail(f"{url} opens no page")
        # Each record kind opens where it is kept.
        self.assertEqual(
            _tracker([measures.get("development_loans")])[1], "Loan Register"
        )
        self.assertEqual(_tracker([measures.get("enrolment")])[1], "School Registry")
        self.assertEqual(
            _tracker([measures.get("dc_clubs_core")])[1], "School Evidence"
        )


class StrategicTargetTest(ReportFixture):
    def test_a_strategic_row_reads_the_same_target_as_its_report_row(self):
        report = self.report()
        rows = {
            row["spec"].title: row
            for _domain, group in report.milestones()["domains"]
            for row in group
        }
        weekly = {
            r["measure"].key: r
            for _s, group in report.weekly(Scope.country())
            for r in group
        }

        exam = rows["Exam Scores target (core schools)"]
        self.assertEqual(exam["year"].target, weekly["core_exam_scores"]["year"].target)
        self.assertEqual(exam["year"].target, 1)  # the one Core school


class PeriodInputTest(ReportFixture):
    def test_a_year_that_is_not_one_reads_the_current_year(self):
        for junk in ("abc", "99999", "-1", ""):
            period = ReportPeriod.resolve(junk, today=TODAY)
            self.assertEqual(period.fy, "2027", junk)


class AreaChartTest(ReportFixture):
    """Owner, 2026-10-21: recruitment charted by every region ("use region in
    stead") and by Programme Lead apart, then "do the graphs for all other
    performance areas. and the summary for all other target performance areas
    as well. graphs of the same target should be on the same row in 2
    columns". A region's target is each CCEO's target shared across the
    regions their eligible schools are in ("Split each CCEO's target")."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.geography.models import Region
        from apps.schools.models import School

        cls.eastern = Region.objects.create(name="Eastern Region")
        Region.objects.create(name="Western Region")
        cls.east = []
        for n in range(3):
            school = cls.school(f"TP-E{n}", cls.james, "client")
            School.objects.filter(pk=school.pk).update(region=cls.eastern)
            cls.east.append(school)

    def bars(self, key, targets=None, country=None):
        report = self.report()
        if targets is not None:
            report.book = _Book(targets, country)
        return {bar["label"]: bar for bar in report.region_bars(key)}

    def test_the_summary_has_every_tracked_target_area(self):
        """Owner, 2026-10-21: "Add training target, core school visits,
        School visits, ....all targets that are tracked"."""
        summary = self.report().executive_summary()
        keys = [a["key"] for _section, areas in summary["sections"] for a in areas]

        for key in (
            "core_recruitment",
            "ssa_client",
            "client_visit_total",
            "client_visit_partner",
            "msc",
            "dc_clubs",
            "core_visit_1",
            "core_training_4",
            "client_trained",
            "literacy_numeracy",
            "client_visits_staff_n",
            "sip_leaders",
        ):
            self.assertIn(key, keys)
        # Untracked rows, rows with no target, and data collected (whose only
        # target would be the portfolio) are not target areas.
        for key in (
            "church_engagement",
            "government_core",
            "online_sessions",
            "dc_data",
        ):
            self.assertNotIn(key, keys)
        self.assertEqual(
            [section for section, _areas in summary["sections"]][:3],
            ["Program Growth", "Data Gathering", "Visits"],
        )
        area = summary["sections"][0][1][0]
        self.assertEqual(area["label"], "Core School Recruitment")
        self.assertEqual(
            [t["label"] for t in area["teams"]], ["Eastern", "No Programme Lead"]
        )
        self.assertIn("regions", area)
        self.assertIn("leads", area)
        # A row label shared by a Core and a client row says which it is.
        labels = [a["label"] for _s, areas in summary["sections"] for a in areas]
        self.assertIn("CC-SEL – Core", labels)
        self.assertIn("CC-SEL – Client", labels)

    def test_a_visit_session_counts_in_its_schools_region(self):
        self.work("school_visit", self.east[0], day=date(2026, 11, 3))
        self.work("school_visit", self.client_school, day=date(2026, 11, 4))

        bars = self.bars("client_visits_staff_n")

        self.assertEqual(
            (bars["Eastern"]["achieved"], bars["Northern"]["achieved"]), (1, 1)
        )

    def test_participants_are_summed_where_their_session_was(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem

        self.work(
            "in_school_training",
            self.east[0],
            day=date(2026, 11, 12),
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="SCHOOL_LEADERSHIP"
            ),
            teachers_attended=7,
            leaders_attended=3,
        )

        bars = self.bars("sip_leaders")

        self.assertEqual(bars["Eastern"]["achieved"], 3)

    def test_every_region_is_listed_even_with_nothing_in_it(self):
        bars = self.bars("core_recruitment", {})

        self.assertEqual(list(bars)[:3], ["Eastern", "Northern", "Western"])
        self.assertEqual(
            (bars["Western"]["target"], bars["Western"]["achieved"]), (0, 0)
        )

    def test_each_cceos_target_follows_their_client_schools(self):
        lead = self.lead.staff_profile.id
        bars = self.bars(
            "core_recruitment",
            {self.james.staff_profile.id: 8, self.mary.staff_profile.id: 3, lead: 2},
        )

        # James: 1 client school in the North, 3 in the East -> 2 and 6 of 8.
        # Mary: her one client school is in the North -> all 3.
        self.assertEqual(bars["Northern"]["target"], 5)
        self.assertEqual(bars["Eastern"]["target"], 6)
        # The lead holds no school: their 2 cannot be placed, and the bars
        # still add up to every target.
        self.assertEqual(bars["Not placed"]["target"], 2)
        self.assertEqual(sum(b["target"] for b in bars.values()), 13)

    def test_a_recruit_counts_where_its_school_is(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem

        self.work(
            "in_school_training",
            self.core,
            day=date(2026, 11, 2),
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="CORE_SCHOOL_ORIENTATION"
            ),
        )

        bars = self.bars("core_recruitment", {})

        self.assertEqual(bars["Northern"]["achieved"], 1)
        self.assertEqual(bars["Eastern"]["achieved"], 0)

    def test_an_eligible_school_target_lands_on_the_regions_eligible_schools(self):
        # Partner visits have no plan milestone: each officer's target is
        # their client schools, so each region's is the client schools there.
        self.work(
            "school_visit", self.east[0], day=date(2026, 11, 3), delivery_type="partner"
        )

        bars = self.bars("client_visit_partner")

        self.assertEqual(bars["Eastern"]["target"], 3)
        self.assertEqual(bars["Northern"]["target"], 2)
        self.assertEqual(bars["Eastern"]["achieved"], 1)
        self.assertNotIn("Not placed", bars)

    def test_a_portfolio_figure_is_read_by_where_its_schools_are(self):
        bars = self.bars("active_schools")

        self.assertEqual(bars["Eastern"]["achieved"], 3)
        self.assertEqual(bars["Northern"]["achieved"], 3)
        self.assertEqual(sum(b["target"] for b in bars.values()), 6)

    def test_each_bar_carries_its_variance_and_share(self):
        bars = self.bars("client_visit_partner")

        self.assertEqual(
            (bars["Eastern"]["variance"], bars["Eastern"]["pct"]), (-3, 0.0)
        )

    def test_a_country_target_nobody_holds_is_not_placed(self):
        bars = self.bars("msc", {}, country=100)

        self.assertEqual(bars["Not placed"]["target"], 100)
        self.assertEqual(sum(b["target"] for b in bars.values()), 100)

    def test_the_programme_lead_charts_are_their_own(self):
        summary = self.report().executive_summary()

        for area in (a for _s, areas in summary["sections"] for a in areas):
            self.assertEqual(
                [bar["label"] for bar in area["leads"]], ["Lead", "No Programme Lead"]
            )


class _Book:
    """A target book: CCEO targets for every milestone, and a country one."""

    def __init__(self, targets, country=None):
        self.targets = {str(k): v for k, v in targets.items()}
        self.country_target = country
        self.country = {}

    def holders(self, code):
        return sorted(self.targets)

    def target(self, measure, scope, *, eligible=None):
        from apps.team_performance.targets import Target

        if scope.kind == "country":
            return Target(annual=self.country_target, source="Country milestone")
        value = self.targets.get(scope.lead) if scope.kind == "officer" else None
        return Target(annual=value, source="Allocation")
