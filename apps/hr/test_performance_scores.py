"""The canonical performance formulas (§13–§15).

What these exist to stop: a PL team score that counts a strong CCEO twice, a
country score built by averaging averages, and an employee with no agreement
being averaged in at 0% as though they had failed rather than never been set up.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.hr.models import (
    MilestoneAllocation,
    MilestoneMetricDefinition,
    MilestonePeriodTarget,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.hr.performance_scores import (
    CONFIGURATION_REQUIRED,
    country_performance,
    pl_performance,
    staff_overall,
)

FY = "2027"


def _staff(role, email, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        user=user, title=role, country=country, onboarding_state="active"
    )


class PerformanceScoreFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        # The FY2027 cycle and its metric vocabulary are reference data seeded
        # on post_migrate, so this reuses them rather than colliding with the
        # unique financial_year.
        cls.cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year=FY, defaults={"status": "published"}
        )
        cls.priority, _ = StrategicPriority.objects.get_or_create(
            fy=FY,
            level="country",
            country_id="Uganda",
            code="PS_TEST",
            defaults={
                "cycle": cls.cycle,
                "title": "Programme Quality",
                "sequence": 90,
            },
        )
        cls.metric, _ = MilestoneMetricDefinition.objects.get_or_create(
            metric_key="ps_test_metric",
            defaults={"canonical_label": "Verified activities"},
        )
        cls.cd, cls.cd_sp = _staff("CountryDirector", "cd@ps.test")
        cls.pl, cls.pl_sp = _staff("Program Lead", "pl@ps.test")
        cls.a, cls.a_sp = _staff("CCEO", "alpha@ps.test")
        cls.b, cls.b_sp = _staff("CCEO", "beta@ps.test")
        for sp in (cls.a_sp, cls.b_sp):
            StaffSupervisorAssignment.objects.create(
                supervisee=sp, supervisor=cls.pl_sp
            )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.pl_sp, supervisor=cls.cd_sp
        )

    def _milestone(self, code, *, measurement="count", cap=False, weight=100):
        return PriorityMilestone.objects.create(
            priority=self.priority,
            code=code,
            title=f"Milestone {code}",
            source_text="test",
            milestone_type="output",
            measurement_type=measurement,
            progress_source="test",
            metric_definition=self.metric,
            target_value=Decimal("1000"),
            target_unit="schools",
            allocation_method="field_cascade",
            cap_at_100=cap,
            weight=weight,
            requires_definition=False,
            definition_status="approved",
            active=True,
        )

    def _allocate(self, milestone, staff, target, achieved, *, weight=None):
        allocation = MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="employee",
            employee=staff,
            allocated_target=Decimal(str(target)),
            status="approved",
            weight=weight if weight is not None else milestone.weight,
            effective_date="2026-10-01",
        )
        MilestonePeriodTarget.objects.create(
            allocation=allocation,
            milestone=milestone,
            period_type="month",
            period_start="2026-10-01",
            period_end="2026-10-31",
            planned_value=Decimal(str(target)),
            actual_value=Decimal(str(achieved)),
        )
        return allocation


class StaffScoreTests(PerformanceScoreFixture):
    def test_a_single_milestone_scores_its_own_percentage(self):
        milestone = self._milestone("M1")
        self._allocate(milestone, self.a_sp, 100, 90)
        score = staff_overall(self.a_sp, FY)
        self.assertTrue(score.eligible)
        self.assertEqual(score.pct, 90.0)
        self.assertEqual(score.classification["label"], "Met Some of the Target")

    def test_milestones_combine_by_their_weights_not_equally(self):
        heavy = self._milestone("HEAVY", weight=75)
        light = self._milestone("LIGHT", weight=25)
        self._allocate(heavy, self.a_sp, 100, 100)  # 100%
        self._allocate(light, self.a_sp, 100, 20)  # 20%
        score = staff_overall(self.a_sp, FY)
        # (100*75 + 20*25) / 100 = 80, not the 60 an equal split would give.
        self.assertEqual(score.pct, 80.0)

    def test_variance_is_achieved_minus_target(self):
        milestone = self._milestone("VAR")
        self._allocate(milestone, self.a_sp, 100, 130)
        row = staff_overall(self.a_sp, FY).rows[0]
        self.assertEqual(row.variance, Decimal("30"))
        self.assertEqual(row.classification["label"], "Exceeded")

    def test_a_coverage_target_cannot_exceed_met(self):
        milestone = self._milestone("COVER", measurement="percentage", cap=True)
        self._allocate(milestone, self.a_sp, 90, 120)
        score = staff_overall(self.a_sp, FY)
        self.assertEqual(score.rows[0].classification["label"], "Met the Target")
        self.assertTrue(score.rows[0].classification["capped"])

    def test_a_zero_target_is_not_applicable_and_never_scored(self):
        milestone = self._milestone("ZERO")
        self._allocate(milestone, self.a_sp, 0, 0)
        score = staff_overall(self.a_sp, FY)
        self.assertFalse(score.rows[0].is_scoring)
        self.assertFalse(score.eligible)

    def test_no_allocation_means_configuration_required_not_zero(self):
        score = staff_overall(self.b_sp, FY)
        self.assertFalse(score.eligible)
        self.assertIsNone(score.pct)
        self.assertEqual(score.reason, CONFIGURATION_REQUIRED)

    def test_a_scoreable_milestone_with_no_weight_withholds_the_score(self):
        """Rather than silently reweighting the remaining rows — that would
        change someone's rating without anyone deciding to."""
        milestone = self._milestone("NOWEIGHT", weight=0)
        self._allocate(milestone, self.a_sp, 100, 100, weight=0)
        score = staff_overall(self.a_sp, FY)
        self.assertFalse(score.eligible)
        self.assertIn("no weight", score.reason)


class TeamAndCountryTests(PerformanceScoreFixture):
    def test_the_pl_headline_is_the_average_of_direct_reports(self):
        milestone = self._milestone("TEAM")
        self._allocate(milestone, self.a_sp, 100, 100)  # 100%
        self._allocate(milestone, self.b_sp, 100, 60)  # 60%
        result = pl_performance(self.pl_sp, FY)
        self.assertEqual(result["team"]["pct"], 80.0)
        self.assertEqual(result["team"]["counted"], 2)

    def test_the_pl_personal_score_stays_visible_beside_the_team_score(self):
        milestone = self._milestone("BOTH")
        self._allocate(milestone, self.pl_sp, 100, 40)  # PL's own delivery
        self._allocate(milestone, self.a_sp, 100, 100)
        self._allocate(milestone, self.b_sp, 100, 100)
        result = pl_performance(self.pl_sp, FY)
        self.assertEqual(result["team"]["pct"], 100.0)
        self.assertEqual(result["personal"]["pct"], 40.0)

    def test_the_pl_is_not_counted_inside_their_own_team_average(self):
        milestone = self._milestone("SELFEX")
        self._allocate(milestone, self.pl_sp, 100, 0)
        self._allocate(milestone, self.a_sp, 100, 100)
        self._allocate(milestone, self.b_sp, 100, 100)
        result = pl_performance(self.pl_sp, FY)
        self.assertEqual(result["team"]["pct"], 100.0)

    def test_a_report_with_no_agreement_is_excluded_and_named(self):
        milestone = self._milestone("PARTIAL")
        self._allocate(milestone, self.a_sp, 100, 100)
        result = pl_performance(self.pl_sp, FY)
        self.assertEqual(result["team"]["pct"], 100.0)
        self.assertEqual(result["team"]["counted"], 1)
        excluded = {e["name"] for e in result["team"]["excluded"]}
        self.assertIn("beta", excluded)

    def test_country_counts_each_person_once_not_via_team_averages(self):
        """Averaging PL team averages would count both CCEOs a second time and
        weight them by team size."""
        milestone = self._milestone("COUNTRY")
        self._allocate(milestone, self.pl_sp, 100, 40)
        self._allocate(milestone, self.a_sp, 100, 100)
        self._allocate(milestone, self.b_sp, 100, 100)
        self._allocate(milestone, self.cd_sp, 100, 20)
        result = country_performance("Uganda", FY)
        # Four individuals, each once: (40 + 100 + 100 + 20) / 4 = 65.
        self.assertEqual(result["counted"], 4)
        self.assertEqual(result["pct"], 65.0)
        # An average of averages would have produced 100 (team) vs 40/20,
        # i.e. a different and wrong answer.
        self.assertNotEqual(result["pct"], 53.33)

    def test_another_country_never_enters_the_average(self):
        milestone = self._milestone("XCOUNTRY")
        _, kenyan = _staff("CCEO", "kenya@ps.test", country="Kenya")
        self._allocate(milestone, self.a_sp, 100, 100)
        self._allocate(milestone, kenyan, 100, 0)
        result = country_performance("Uganda", FY)
        self.assertEqual(result["counted"], 1)
        self.assertEqual(result["pct"], 100.0)
