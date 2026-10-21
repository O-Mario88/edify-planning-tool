"""Targets: the Uganda Master Priority Plan figures leads already set.

Owner, 2026-10-20: "Targets are already set by PL and Project coordinator".
The country reads the milestone, a region its lead's team allocation, a CCEO
their own allocation, each month its approved phasing; a coverage rate is a
share of the scope's eligible schools.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.hr.models import (
    MilestoneAllocation,
    MilestonePeriodTarget,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.team_performance import measures
from apps.team_performance.targets import Scope, TargetBook
from apps.team_performance.test_ledger import make_officer

FY = "2031"


class TargetBookTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cycle = StrategicPriorityCycle.objects.create(
            financial_year=FY, title="FY2031", scope_type="country", country_id="Uganda"
        )
        cls.priority = StrategicPriority.objects.create(
            cycle=cycle,
            fy=FY,
            level="country",
            country_id="Uganda",
            title="Program Quality",
            sequence=2,
        )
        cls.lead = make_officer("lead@tp-targets.test", "Program Lead")
        cls.james = make_officer("james@tp-targets.test")
        cls.recruit = cls.milestone("NEW_CORE_SCHOOLS", 500)
        cls.literacy = cls.milestone(
            "LITERACY_TRAINING", 7000, core_target=1600, client_target=5400
        )
        cls.coverage = cls.milestone(
            "CLIENT_VISIT_COVERAGE", 90, measurement="percentage"
        )

        team = cls.allocate(cls.recruit, team_id=cls.lead.staff_profile.id, value=120)
        mine = cls.allocate(
            cls.recruit, employee=cls.james.staff_profile, value=25, parent=team
        )
        for month_start, value in ((date(2030, 10, 1), 5), (date(2030, 11, 1), 7)):
            MilestonePeriodTarget.objects.create(
                milestone=cls.recruit,
                allocation=mine,
                scope="employee",
                employee=cls.james.staff_profile,
                period_type="month",
                period_start=month_start,
                period_end=month_start.replace(day=28),
                planned_value=Decimal(value),
            )
        cls.allocate(
            cls.literacy,
            employee=cls.james.staff_profile,
            value=300,
            core=100,
            client=200,
        )

    @classmethod
    def milestone(cls, code, target, *, measurement="count", **slices):
        return PriorityMilestone.objects.create(
            priority=cls.priority,
            code=code,
            title=code.title(),
            source_text=code,
            milestone_type="output",
            measurement_type=measurement,
            progress_source="activities",
            target_value=Decimal(target),
            responsible_role="CCEO",
            **{k: Decimal(v) for k, v in slices.items()},
        )

    @classmethod
    def allocate(cls, milestone, *, value, core=None, client=None, **holder):
        kind = "employee" if "employee" in holder else "team"
        return MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type=kind,
            allocated_target=Decimal(value),
            core_target=None if core is None else Decimal(core),
            client_target=None if client is None else Decimal(client),
            allocation_reason="test",
            allocated_by="test",
            effective_date=date(2030, 10, 1),
            status="approved",
            **holder,
        )

    def setUp(self):
        self.book = TargetBook.load(FY)
        self.country = Scope.country()
        self.region = Scope.region(
            self.lead.staff_profile.id, {self.james.staff_profile.id}
        )
        self.officer = Scope.officer(self.james.staff_profile.id)

    def target(self, key, scope, eligible=None):
        return self.book.target(measures.get(key), scope, eligible=eligible)

    def test_each_scope_reads_its_own_figure(self):
        self.assertEqual(self.target("core_recruitment", self.country).annual, 500)
        self.assertEqual(self.target("core_recruitment", self.region).annual, 120)
        self.assertEqual(self.target("core_recruitment", self.officer).annual, 25)

    def test_the_country_months_are_the_teams_approved_phasing(self):
        team = MilestoneAllocation.objects.get(
            milestone=self.recruit, allocated_to_type="team"
        )
        MilestonePeriodTarget.objects.create(
            milestone=self.recruit,
            allocation=team,
            scope="team",
            period_type="month",
            period_start=date(2030, 10, 1),
            period_end=date(2030, 10, 28),
            planned_value=Decimal(30),
        )

        target = TargetBook.load(FY).target(
            measures.get("core_recruitment"), self.country
        )

        self.assertEqual(target.annual, 500)
        self.assertEqual(target.months, {1: 30})

    def test_any_plan_milestone_is_read_by_its_code(self):
        target = self.book.for_code("LITERACY_TRAINING", self.officer, slice="core")

        self.assertEqual(target.annual, 100)

    def test_a_core_or_client_row_reads_its_slice(self):
        self.assertEqual(self.target("literacy_numeracy", self.country).annual, 5400)
        self.assertEqual(self.target("literacy_numeracy", self.officer).annual, 200)

    def test_the_months_are_the_approved_phasing(self):
        target = self.target("core_recruitment", self.officer)

        self.assertEqual(target.months, {1: 5, 2: 7})
        self.assertEqual(target.through(2), 12)
        self.assertIsNone(self.target("core_recruitment", self.country).months)

    def test_a_coverage_rate_is_a_share_of_the_eligible_schools(self):
        target = self.target("client_visit_total", self.country, eligible=400)

        self.assertEqual(target.annual, 360)
        self.assertEqual(target.rate, 90)

    def test_a_coverage_row_without_a_milestone_takes_the_eligible_schools(self):
        target = self.target("core_visit_1", self.officer, eligible=40)

        self.assertEqual(target.annual, 40)
        self.assertEqual(target.source, "Eligible schools")

    def test_a_milestone_row_without_its_milestone_is_not_set_not_the_portfolio(self):
        # Discipleship Clubs is 60% of the portfolio: with no milestone for the
        # year it must not read as 100% of it.
        target = self.target("dc_clubs", self.officer, eligible=40)

        self.assertIsNone(target.annual)
        self.assertEqual(target.source, "Not set")

    def test_a_target_of_nought_is_nought_not_unset(self):
        self.milestone("MSC_STORIES", 0)
        self.allocate(
            PriorityMilestone.objects.get(code="MSC_STORIES"),
            employee=self.james.staff_profile,
            value=0,
        )
        book = TargetBook.load(FY)

        for scope in (self.country, self.officer):
            target = book.target(measures.get("msc"), scope)
            self.assertEqual((target.annual, target.source == "Not set"), (0, False))

    def test_the_holders_of_a_milestone_are_its_cceo_allocations(self):
        self.assertEqual(
            self.book.holders("NEW_CORE_SCHOOLS"), [str(self.james.staff_profile.id)]
        )
        self.assertEqual(self.book.holders("NO_SUCH_MILESTONE"), [])

    def test_no_figure_is_not_set_never_zero(self):
        target = self.target("government_core", self.officer)

        self.assertIsNone(target.annual)
        self.assertEqual(target.source, "Not set")

    def test_the_milestones_are_listed_in_plan_order(self):
        codes = [m.code for m in self.book.milestones]

        self.assertEqual(
            codes, ["NEW_CORE_SCHOOLS", "LITERACY_TRAINING", "CLIENT_VISIT_COVERAGE"]
        )
