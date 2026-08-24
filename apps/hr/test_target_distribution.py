"""Uganda Master Priority Plan — the §4/§6/§7/§11 laws under test.

Covers: the seed shape, CD confirmation + publish-and-lock, IA→PL
reconciliation (sums, Core/Client columns, over/under balances), one annual
distribution, PL→team-member scoping, quarterly law (Q1+Q2+Q3+Q4 = annual),
capacity-aware monthly phasing with locked past months and honest capacity
warnings, rates-never-sum, achievement classification bands, amendment and
reforecast control, credit reversal on IA return, and both workspace pages.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.services import apply_catalogue_snapshot
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal

from . import target_distribution as engine
from .milestone_allocations import approve_allocation, create_allocation
from .milestone_progress import (
    record_activity_progress,
    reverse_activity_progress,
)
from .models import (
    MilestoneActivityRule,
    MilestoneAllocation,
    MilestoneMetricDefinition,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from .uganda_master_seeding import seed_uganda_master

FY = "2027"


def _user(role, email, name):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="test-password",
        is_active=True,
    )
    staff = StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user, staff


class DistributionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_uganda_master(actor_id="test")
        cls.cd, cls.cd_sp = _user("CountryDirector", "cd@ug.test", "CD Uganda")
        cls.ia, cls.ia_sp = _user("ImpactAssessment", "ia@ug.test", "IA Uganda")
        # A second IA: amendments now require requester != approver
        # (2026-08-20 audit G2).
        cls.ia2, cls.ia2_sp = _user("ImpactAssessment", "ia2@ug.test", "IA Two")
        cls.pl, cls.pl_sp = _user("Program Lead", "pl1@ug.test", "PL One")
        cls.pl2, cls.pl2_sp = _user("Program Lead", "pl2@ug.test", "PL Two")
        cls.cceo_a, cls.cceo_a_sp = _user("CCEO", "cceo-a@ug.test", "CCEO Alpha")
        cls.cceo_b, cls.cceo_b_sp = _user("CCEO", "cceo-b@ug.test", "CCEO Beta")
        cls.cceo_c, cls.cceo_c_sp = _user("CCEO", "cceo-c@ug.test", "CCEO Gamma")
        for supervisee in (cls.cceo_a_sp, cls.cceo_b_sp):
            StaffSupervisorAssignment.objects.create(
                supervisee=supervisee, supervisor=cls.pl_sp
            )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_c_sp, supervisor=cls.pl2_sp
        )
        cls.region = Region.objects.create(name="UMP Region")
        cls.district = District.objects.create(name="UMP District", region=cls.region)
        # CCEO Alpha: 3 client + 1 core; Beta: 1 client; Gamma: 1 core.
        assignments = [
            (cls.cceo_a_sp, "client", 3),
            (cls.cceo_a_sp, "core", 1),
            (cls.cceo_b_sp, "client", 1),
            (cls.cceo_c_sp, "core", 1),
        ]
        counter = 0
        cls.schools_by_staff = {}
        for staff, school_type, how_many in assignments:
            for _ in range(how_many):
                counter += 1
                school = School.objects.create(
                    school_id=f"UMP-{counter}",
                    name=f"UMP School {counter}",
                    region=cls.region,
                    district=cls.district,
                    school_type=school_type,
                )
                # school_id here is the School pk — StaffSchoolAssignment
                # stores it as a plain CharField, not an FK.
                StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
                cls.schools_by_staff.setdefault(staff.id, []).append(school)

    # ── helpers ──────────────────────────────────────────────────────────
    @classmethod
    def _milestone(
        cls,
        code="TEST_COUNT",
        *,
        measurement="count",
        target="100",
        method="field_cascade",
        cap_at_100=False,
    ):
        priority = StrategicPriority.objects.get(
            fy=FY, level="country", code="PROGRAM_QUALITY", country_id="Uganda"
        )
        metric = MilestoneMetricDefinition.objects.get(
            metric_key="verified_activity_catalogue_progress"
        )
        return PriorityMilestone.objects.create(
            priority=priority,
            code=code,
            title=f"Test milestone {code}",
            source_text="test",
            milestone_type="output",
            measurement_type=measurement,
            progress_source="test",
            metric_definition=metric,
            target_value=Decimal(target),
            target_unit="units",
            allocation_method=method,
            cap_at_100=cap_at_100,
            requires_definition=False,
            definition_status="approved",
            active=True,
        )

    def _team_allocation(self, milestone, team_sp, target, **extra):
        return create_allocation(
            milestone=milestone,
            data={
                "allocatedToType": "team",
                "teamId": team_sp.id,
                "allocatedTarget": str(target),
                "effectiveDate": "2026-10-01",
                "allocationReason": "test distribution",
                **extra,
            },
            principal=self.ia,
        )

    def _employee_allocation(self, milestone, staff, target, parent=None, **extra):
        data = {
            "allocatedToType": "employee",
            "employeeId": staff.id,
            "allocatedTarget": str(target),
            "effectiveDate": "2026-10-01",
            "allocationReason": "test distribution",
            **extra,
        }
        if parent is not None:
            data["parentId"] = parent.id
        return create_allocation(milestone=milestone, data=data, principal=self.pl)


class UgandaMasterSeedTests(DistributionFixture):
    def test_seed_is_idempotent_and_preserves_the_five_groups(self):
        first = PriorityMilestone.objects.filter(
            priority__level="country", priority__country_id="Uganda"
        ).count()
        seed_uganda_master(actor_id="test")
        second = PriorityMilestone.objects.filter(
            priority__level="country", priority__country_id="Uganda"
        ).count()
        self.assertEqual(first, second)
        # 75 = the 74 transcribed source rows + TRAINED_90_PERCENT, the
        # percentage milestone the source states as prose.
        self.assertEqual(first, 75)
        country = StrategicPriority.objects.filter(
            fy=FY, level="country", country_id="Uganda"
        ).order_by("sequence")
        self.assertEqual(country.count(), 5)
        for priority in country:
            self.assertIsNotNone(priority.parent_id)
            self.assertEqual(priority.parent.level, "regional")
            self.assertEqual(priority.parent.code, priority.code)

    def test_uganda_figures_sit_beside_the_regional_plan_not_instead_of_it(self):
        regional = PriorityMilestone.objects.get(
            code="NEW_CORE_SCHOOLS", priority__level="regional"
        )
        uganda = PriorityMilestone.objects.get(
            code="NEW_CORE_SCHOOLS", priority__level="country"
        )
        self.assertEqual(regional.target_value, 730)
        self.assertEqual(uganda.target_value, 500)

    def test_training_milestones_carry_core_client_and_participant_dimensions(self):
        dc = PriorityMilestone.objects.get(
            code="DC_TRAINING", priority__level="country"
        )
        self.assertEqual(dc.target_value, 4157)
        self.assertEqual(dc.core_target, 520)
        self.assertEqual(dc.client_target, 3637)
        self.assertEqual(dc.participants_per_school, 1)
        self.assertEqual(dc.allocation_method, "field_cascade")

    def test_ambiguous_source_values_are_flagged_never_silently_normalized(self):
        flagged = PriorityMilestone.objects.filter(
            priority__level="country",
            priority__country_id="Uganda",
            needs_confirmation=True,
        )
        # 29 = the original 27 ambiguous source values + the 50%-vs-100-loans
        # composite + TRAINED_90_PERCENT, whose denominator the source never
        # states.
        self.assertEqual(flagged.count(), 29)
        ecd = PriorityMilestone.objects.get(
            code="ECD_TEACHERS", priority__level="country"
        )
        self.assertIn("2000, 200", ecd.confirmation_note)

    def test_blank_source_targets_are_preserved_but_never_scoreable(self):
        tot = PriorityMilestone.objects.get(
            code="TOT_TRAININGS", priority__level="country"
        )
        self.assertEqual(tot.allocation_method, "non_scoreable")
        self.assertIsNone(tot.target_value)
        self.assertFalse(tot.active)


class ClassificationTests(SimpleTestCase):
    """The five approved bands, tested at their exact boundaries.

    A boundary that "roughly" works is a boundary that disagrees with itself
    at 89.99 vs 90.00, which is precisely where someone's rating changes.
    """

    def test_the_five_bands_at_their_exact_boundaries(self):
        cases = [
            (0, "not_met"),
            (89.99, "not_met"),
            (90, "met_some"),
            (90.00, "met_some"),
            (99.99, "met_some"),
            (100, "met"),
            (100.00, "met"),
            (100.01, "exceeded"),
            (149.99, "exceeded"),
            (150, "far_exceeded"),
            (150.00, "far_exceeded"),
            (210, "far_exceeded"),
        ]
        for pct, expected in cases:
            self.assertEqual(engine.classify_achievement(pct)["key"], expected, msg=pct)

    def test_the_labels_are_the_approved_wording(self):
        self.assertEqual(engine.classify_achievement(50)["label"], "Not Met the Target")
        self.assertEqual(
            engine.classify_achievement(95)["label"], "Met Some of the Target"
        )
        self.assertEqual(engine.classify_achievement(100)["label"], "Met the Target")
        self.assertEqual(engine.classify_achievement(120)["label"], "Exceeded")
        self.assertEqual(engine.classify_achievement(150)["label"], "Far Exceeded")

    def test_a_coverage_target_can_reach_met_and_no_further(self):
        capped = engine.classify_achievement(150, cap_at_100=True)
        self.assertEqual(capped["key"], "met")
        self.assertEqual(capped["pct"], 100.0)
        self.assertTrue(capped["capped"])

    def test_no_data_is_not_started_never_zero_percent(self):
        result = engine.classify_achievement(None)
        self.assertEqual(result["key"], "not_started")
        self.assertFalse(result["is_scoring"])

    def test_a_zero_target_is_not_applicable_never_a_division(self):
        result = engine.classify_achievement(0, target=0)
        self.assertEqual(result["key"], "not_applicable")
        self.assertFalse(result["is_scoring"])

    def test_a_non_scoreable_milestone_is_never_averaged_in(self):
        result = engine.classify_achievement(120, scoreable=False)
        self.assertEqual(result["key"], "non_scoreable")
        self.assertFalse(result["is_scoring"])

    def test_only_real_percentages_are_scoring(self):
        self.assertTrue(engine.classify_achievement(42)["is_scoring"])


class WeightedSplitTests(SimpleTestCase):
    def test_split_preserves_the_exact_total(self):
        shares = engine.weighted_split(Decimal("100.01"), [3, 2, 1])
        self.assertEqual(sum(shares), Decimal("100.01"))

    def test_zero_weights_fall_back_to_an_equal_split(self):
        shares = engine.weighted_split(Decimal("9"), [0, 0, 0])
        self.assertEqual(sum(shares), Decimal("9"))
        self.assertTrue(all(share == Decimal("3") for share in shares))


class ReconciliationTests(DistributionFixture):
    def test_missing_balance_blocks_distribution_approval(self):
        milestone = self._milestone("REC_1")
        self._team_allocation(milestone, self.pl_sp, 60)
        state = engine.reconcile_team_level(milestone)
        self.assertFalse(state["balanced"])
        self.assertEqual(state["unallocated"], Decimal("40"))
        with self.assertRaises(BadRequest):
            engine.approve_team_distribution(milestone, principal=self.ia)

    def test_overallocation_is_an_error_not_a_stretch_goal(self):
        milestone = self._milestone("REC_2")
        self._team_allocation(milestone, self.pl_sp, 80)
        self._team_allocation(milestone, self.pl2_sp, 40)
        state = engine.reconcile_team_level(milestone)
        self.assertFalse(state["balanced"])
        self.assertIn("Over-allocated", state["errors"][0])

    def test_balanced_distribution_approves_and_locks_every_row(self):
        milestone = self._milestone("REC_3")
        self._team_allocation(milestone, self.pl_sp, 60)
        self._team_allocation(milestone, self.pl2_sp, 40)
        approved = engine.approve_team_distribution(milestone, principal=self.ia)
        self.assertEqual(approved, 2)
        rows = MilestoneAllocation.objects.filter(milestone=milestone)
        for row in rows:
            self.assertEqual(row.status, "approved")
            self.assertIsNotNone(row.locked_at)

    def test_core_and_client_columns_reconcile_like_the_main_column(self):
        milestone = self._milestone("REC_4")
        milestone.core_target = Decimal("30")
        milestone.client_target = Decimal("70")
        milestone.save(update_fields=["core_target", "client_target"])
        self._team_allocation(
            milestone, self.pl_sp, 60, coreTarget="10", clientTarget="50"
        )
        self._team_allocation(
            milestone, self.pl2_sp, 40, coreTarget="10", clientTarget="30"
        )
        state = engine.reconcile_team_level(milestone)
        self.assertFalse(state["balanced"])
        self.assertTrue(any("Core" in error for error in state["errors"]))

    def test_targets_are_distributed_once_a_second_row_is_refused(self):
        milestone = self._milestone("REC_5")
        self._team_allocation(milestone, self.pl_sp, 60)
        with self.assertRaises(BadRequest) as ctx:
            self._team_allocation(milestone, self.pl_sp, 40)
        self.assertIn("amendment", str(ctx.exception))

    def test_unconfirmed_source_figures_cannot_distribute(self):
        milestone = self._milestone("REC_6")
        milestone.needs_confirmation = True
        milestone.save(update_fields=["needs_confirmation"])
        self._team_allocation(milestone, self.pl_sp, 100)
        with self.assertRaises(BadRequest):
            engine.approve_team_distribution(milestone, principal=self.ia)

    def test_program_leads_cannot_run_the_country_distribution(self):
        milestone = self._milestone("REC_7")
        self._team_allocation(milestone, self.pl_sp, 100)
        with self.assertRaises(BadRequest):
            engine.approve_team_distribution(milestone, principal=self.pl)


class EmployeeDistributionTests(DistributionFixture):
    def _approved_team(self, code="EMP_1", target=40):
        # approve_allocation now enforces reconcile-to-zero (2026-08-20
        # audit G1) — a lone team allocation approves only when it IS the
        # whole country distribution, so the milestone target matches it.
        milestone = self._milestone(code, target=str(target))
        allocation = self._team_allocation(milestone, self.pl_sp, target)
        # approve_allocation re-fetches under lock — use the fresh instance.
        allocation = approve_allocation(allocation, principal=self.ia)
        return milestone, allocation

    def test_cceo_allocations_must_sum_to_the_team_target(self):
        milestone, team = self._approved_team()
        self._employee_allocation(milestone, self.cceo_a_sp, 25, parent=team)
        with self.assertRaises(BadRequest):
            engine.approve_employee_distribution(team, principal=self.pl)
        self._employee_allocation(milestone, self.cceo_b_sp, 15, parent=team)
        approved = engine.approve_employee_distribution(team, principal=self.pl)
        self.assertEqual(approved, 2)

    def test_a_pl_cannot_allocate_outside_their_supervised_team(self):
        milestone, team = self._approved_team("EMP_2")
        with self.assertRaises(BadRequest):
            self._employee_allocation(milestone, self.cceo_c_sp, 40, parent=team)

    def test_a_pl_cannot_complete_another_teams_distribution(self):
        milestone, team = self._approved_team("EMP_3")
        self._employee_allocation(milestone, self.cceo_a_sp, 40, parent=team)
        with self.assertRaises(BadRequest):
            engine.approve_employee_distribution(team, principal=self.pl2)

    def test_a_pl_is_an_eligible_holder_inside_their_approved_team_target(self):
        milestone, team = self._approved_team("EMP_SELF", target=40)
        milestone.role_applicability = ["CCEO"]
        milestone.save(update_fields=["role_applicability"])

        recommendations = engine.recommend_employee_allocations(team)
        lead = next(row for row in recommendations if row["staff"] == self.pl_sp)
        self.assertTrue(lead["isLead"])

        self._employee_allocation(milestone, self.pl_sp, 10, parent=team)
        self._employee_allocation(milestone, self.cceo_a_sp, 20, parent=team)
        self._employee_allocation(milestone, self.cceo_b_sp, 10, parent=team)
        approved = engine.approve_employee_distribution(team, principal=self.pl)
        self.assertEqual(approved, 3)

    def test_a_pl_cannot_self_allocate_without_their_approved_ia_parent(self):
        milestone = self._milestone("EMP_SELF_GUARD", target="10")
        with self.assertRaises(BadRequest) as ctx:
            self._employee_allocation(milestone, self.pl_sp, 10)
        self.assertIn("approved team target", str(ctx.exception))

    def test_recommendations_balance_portfolio_availability_and_workload(self):
        milestone, team = self._approved_team("EMP_4", target=50)
        rows = engine.recommend_employee_allocations(team)
        by_name = {row["staff"].user.name: row for row in rows}
        # The PL is a delivery holder too. Alpha holds 4 of the team's 5
        # schools, so portfolio demand remains dominant, while capacity keeps
        # a non-zero recommendation for Beta and the PL.
        self.assertIn("PL One", by_name)
        self.assertTrue(by_name["PL One"]["isLead"])
        self.assertGreater(
            by_name["CCEO Alpha"]["recommended"],
            by_name["CCEO Beta"]["recommended"],
        )
        self.assertGreater(
            by_name["CCEO Beta"]["recommended"], by_name["PL One"]["recommended"]
        )
        self.assertEqual(by_name["CCEO Alpha"]["eligibleSchools"], 4)
        self.assertEqual(by_name["CCEO Beta"]["eligibleSchools"], 1)
        self.assertGreater(by_name["CCEO Alpha"]["balanceScore"], 50)
        self.assertIn("availableDays", by_name["CCEO Alpha"]["activeFactors"])
        by_name = {name: row["recommended"] for name, row in by_name.items()}
        self.assertEqual(sum(by_name.values()), Decimal("50"))

    def test_existing_priority_load_reduces_a_cceo_recommendation(self):
        milestone, team = self._approved_team("EMP_LOAD", target=50)
        before = {
            row["staff"].id: row for row in engine.recommend_employee_allocations(team)
        }
        other = self._milestone("EMP_OTHER", target="10")
        other_team = self._team_allocation(other, self.pl_sp, 10)
        approve_allocation(other_team, principal=self.ia)
        self._employee_allocation(other, self.cceo_a_sp, 10, parent=other_team)
        after = {
            row["staff"].id: row for row in engine.recommend_employee_allocations(team)
        }
        self.assertEqual(after[self.cceo_a_sp.id]["activePriorities"], 1)
        self.assertLess(
            after[self.cceo_a_sp.id]["recommended"],
            before[self.cceo_a_sp.id]["recommended"],
        )
        self.assertEqual(
            sum(row["recommended"] for row in after.values()), Decimal("50")
        )


class TeamRecommendationTests(DistributionFixture):
    def test_ia_model_uses_team_schools_cceo_count_and_capacity(self):
        milestone = self._milestone("TEAM_SMART", target="100")
        rows = engine.recommend_team_allocations(milestone)
        by_name = {row["staff"].user.name: row for row in rows}
        larger = by_name["PL One"]
        smaller = by_name["PL Two"]
        self.assertEqual(larger["portfolio"]["total"], 5)
        self.assertEqual(larger["memberCount"], 3)
        self.assertEqual(larger["cceoCount"], 2)
        self.assertEqual(smaller["portfolio"]["total"], 1)
        self.assertEqual(smaller["memberCount"], 2)
        self.assertEqual(smaller["cceoCount"], 1)
        self.assertGreater(larger["availableDays"], smaller["availableDays"])
        self.assertGreater(larger["recommended"], smaller["recommended"])
        self.assertEqual(sum(row["recommended"] for row in rows), Decimal("100"))


class QuarterlySpreadTests(DistributionFixture):
    def _approved(self, code="QSP_1", target="12", measurement="count"):
        milestone = self._milestone(code, target=target, measurement=measurement)
        allocation = self._team_allocation(milestone, self.pl_sp, target)
        approve_allocation(allocation, principal=self.ia)
        return allocation

    def test_annual_approval_writes_quarters_and_capacity_phased_months(self):
        allocation = self._approved()
        months = allocation.period_targets.filter(period_type="month")
        quarters = allocation.period_targets.filter(period_type="quarter")
        self.assertEqual(months.count(), 12)
        self.assertEqual(quarters.count(), 4)
        self.assertEqual(sum(row.planned_value for row in months), Decimal("12"))
        self.assertEqual(sum(row.planned_value for row in quarters), Decimal("12"))

    def test_quarters_must_sum_to_the_annual_target(self):
        allocation = self._approved("QSP_2")
        with self.assertRaises(BadRequest):
            engine.approve_quarters(
                allocation,
                quarters={"Q1": "6", "Q2": "3", "Q3": "2", "Q4": "2"},
                principal=self.ia,
            )

    def test_approved_spread_rewrites_quarters_and_reaches_month_rows(self):
        allocation = self._approved("QSP_3")
        engine.approve_quarters(
            allocation,
            quarters={"Q1": "6", "Q2": "3", "Q3": "2", "Q4": "1"},
            principal=self.ia,
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.quarter_status, "approved")
        q1_start, _ = Cal.quarter_range(FY, "Q1")
        q1 = allocation.period_targets.get(period_type="quarter", period_start=q1_start)
        self.assertEqual(q1.planned_value, Decimal("6"))
        q1_months = [
            row
            for row in allocation.period_targets.filter(period_type="month")
            if Cal.quarter_of_month(Cal.month_of_fy_for(row.period_start, FY)) == "Q1"
        ]
        self.assertEqual(sum(row.planned_value for row in q1_months), Decimal("6"))

    def test_the_team_spread_is_approved_by_ia_not_by_the_pl(self):
        allocation = self._approved("QSP_4")
        with self.assertRaises(BadRequest):
            engine.approve_quarters(
                allocation,
                quarters={"Q1": "3", "Q2": "3", "Q3": "3", "Q4": "3"},
                principal=self.pl,
            )

    def test_the_cceo_spread_is_approved_by_their_supervising_pl(self):
        milestone = self._milestone("QSP_5", target="12")
        team = self._team_allocation(milestone, self.pl_sp, 12)
        approve_allocation(team, principal=self.ia)
        child = self._employee_allocation(milestone, self.cceo_a_sp, 12, parent=team)
        approve_allocation(child, principal=self.pl)
        with self.assertRaises(BadRequest):
            engine.approve_quarters(
                child,
                quarters={"Q1": "3", "Q2": "3", "Q3": "3", "Q4": "3"},
                principal=self.pl2,
            )
        engine.approve_quarters(
            child,
            quarters={"Q1": "3", "Q2": "3", "Q3": "3", "Q4": "3"},
            principal=self.pl,
        )
        child.refresh_from_db()
        self.assertEqual(child.quarter_status, "approved")

    def test_rates_carry_the_level_in_every_quarter_never_a_sum(self):
        milestone = self._milestone(
            "QSP_RATE", target="90", measurement="percentage", cap_at_100=True
        )
        allocation = self._team_allocation(milestone, self.pl_sp, 90)
        approve_allocation(allocation, principal=self.ia)
        for row in allocation.period_targets.all():
            self.assertEqual(row.planned_value, Decimal("90"))


class MonthlyPhasingTests(DistributionFixture):
    def test_a_fully_blocked_month_carries_zero_and_its_quarter_absorbs_it(self):
        milestone = self._milestone("PHA_1", target="21")
        team = self._team_allocation(milestone, self.pl_sp, 21)
        approve_allocation(team, principal=self.ia)
        child = self._employee_allocation(milestone, self.cceo_a_sp, 21, parent=team)
        # CCEO Alpha is on approved leave for all of November 2026.
        Leave.objects.create(
            staff=self.cceo_a_sp,
            type="personal_time_off",
            start_date="2026-11-01",
            end_date="2026-11-30",
            days=21,
            status="approved",
        )
        approve_allocation(child, principal=self.pl)
        november = child.period_targets.get(
            period_type="month", period_start=date(2026, 11, 1)
        )
        self.assertEqual(november.planned_value, Decimal("0"))
        q1_months = child.period_targets.filter(
            period_type="month",
            period_start__in=[date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)],
        )
        q1 = child.period_targets.get(
            period_type="quarter", period_start=date(2026, 10, 1)
        )
        self.assertEqual(sum(row.planned_value for row in q1_months), q1.planned_value)

    def test_elapsed_months_never_move_when_the_future_is_rephased(self):
        milestone = self._milestone("PHA_2", target="12")
        allocation = self._team_allocation(milestone, self.pl_sp, 12)
        approve_allocation(allocation, principal=self.ia)
        october = allocation.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )
        committed_october = october.planned_value
        # Re-phase mid-November: October has elapsed and must keep its value.
        warnings = engine.phase_allocation_periods(allocation, today=date(2026, 11, 15))
        october.refresh_from_db()
        self.assertEqual(october.planned_value, committed_october)
        self.assertEqual(warnings, [])
        months = allocation.period_targets.filter(period_type="month")
        self.assertEqual(sum(row.planned_value for row in months), Decimal("12"))

    def test_zero_remaining_capacity_warns_and_never_reduces_the_commitment(self):
        milestone = self._milestone("PHA_3", target="12")
        team = self._team_allocation(milestone, self.pl_sp, 12)
        approve_allocation(team, principal=self.ia)
        child = self._employee_allocation(milestone, self.cceo_b_sp, 12, parent=team)
        Leave.objects.create(
            staff=self.cceo_b_sp,
            type="personal_time_off",
            start_date="2026-10-01",
            end_date="2026-12-31",
            days=64,
            status="approved",
        )
        approve_allocation(child, principal=self.pl)
        warnings = engine.phase_allocation_periods(
            child,
            {
                "Q1": Decimal("12"),
                "Q2": Decimal("0"),
                "Q3": Decimal("0"),
                "Q4": Decimal("0"),
            },
        )
        self.assertTrue(any("cannot fit" in warning for warning in warnings))
        months = child.period_targets.filter(period_type="month")
        self.assertEqual(sum(row.planned_value for row in months), Decimal("12"))


class AutoRephaseTests(DistributionFixture):
    def test_approved_leave_rephases_future_months_automatically(self):
        from apps.hr.leave_services import LeaveApprovalService

        milestone = self._milestone("ARP_1", target="21")
        team = self._team_allocation(milestone, self.pl_sp, 21)
        approve_allocation(team, principal=self.ia)
        child = self._employee_allocation(milestone, self.cceo_a_sp, 21, parent=team)
        child = approve_allocation(child, principal=self.pl)
        november = child.period_targets.get(
            period_type="month", period_start=date(2026, 11, 1)
        )
        self.assertGreater(november.planned_value, 0)

        leave = Leave.objects.create(
            staff=self.cceo_a_sp,
            type="personal_time_off",
            start_date="2026-11-01",
            end_date="2026-11-30",
            days=21,
            status="pending",
        )
        with self.captureOnCommitCallbacks(execute=True):
            LeaveApprovalService.approve_request(leave.id, self.pl)

        november.refresh_from_db()
        self.assertEqual(november.planned_value, Decimal("0"))
        months = child.period_targets.filter(period_type="month")
        self.assertEqual(sum(row.planned_value for row in months), Decimal("21"))


class AmendmentTests(DistributionFixture):
    def _approved(self, code="AMD_1"):
        milestone = self._milestone(code, target="100")
        allocation = self._team_allocation(milestone, self.pl_sp, 100)
        return approve_allocation(allocation, principal=self.ia)

    def test_approved_figures_change_only_through_an_amendment(self):
        allocation = self._approved()
        amendment = engine.request_amendment(
            allocation,
            kind="amendment",
            reason="Portfolio shrank after school closures.",
            new_target="80",
            principal=self.ia,
        )
        engine.approve_amendment(amendment, principal=self.ia2)
        allocation.refresh_from_db()
        self.assertEqual(allocation.allocated_target, Decimal("80"))
        self.assertEqual(allocation.version, 2)
        # The old spread reconciled against the old figure; it re-approves.
        self.assertEqual(allocation.quarter_status, "draft")

    def test_an_amendment_without_a_reason_is_refused(self):
        allocation = self._approved("AMD_2")
        with self.assertRaises(BadRequest):
            engine.request_amendment(
                allocation,
                kind="amendment",
                reason="  ",
                new_target="80",
                principal=self.ia,
            )

    def test_amendments_keep_previous_and_new_values_for_audit(self):
        allocation = self._approved("AMD_3")
        amendment = engine.request_amendment(
            allocation,
            kind="amendment",
            reason="Recovery plan.",
            new_target="120",
            principal=self.ia,
        )
        self.assertEqual(amendment.previous_target, Decimal("100"))
        self.assertEqual(amendment.new_target, Decimal("120"))
        self.assertEqual(amendment.status, "requested")

    def test_a_reforecast_moves_future_quarters_and_keeps_the_annual_total(self):
        allocation = self._approved("AMD_4")
        engine.approve_quarters(
            allocation,
            quarters={"Q1": "25", "Q2": "25", "Q3": "25", "Q4": "25"},
            principal=self.ia,
        )
        allocation.refresh_from_db()
        with patch.object(
            Cal,
            "current",
            return_value={
                "today": date(2027, 1, 15),
                "fy": FY,
                "month_of_fy": 4,
                "quarter": "Q2",
                "month_label": "January 2027",
            },
        ):
            with self.assertRaises(BadRequest):
                # Q1 has closed — moving it is refused.
                engine.request_amendment(
                    allocation,
                    kind="reforecast",
                    reason="Shift work later.",
                    new_quarters={"Q1": "20", "Q2": "30", "Q3": "25", "Q4": "25"},
                    principal=self.ia,
                )
            amendment = engine.request_amendment(
                allocation,
                kind="reforecast",
                reason="Term dates moved delivery to Q4.",
                new_quarters={"Q1": "25", "Q2": "25", "Q3": "15", "Q4": "35"},
                principal=self.ia,
            )
            engine.approve_amendment(amendment, principal=self.ia2)
        allocation.refresh_from_db()
        self.assertEqual(allocation.allocated_target, Decimal("100"))
        self.assertEqual(allocation.quarter_distribution["Q4"], "35.00")

    def test_a_reforecast_that_changes_the_annual_total_is_refused(self):
        allocation = self._approved("AMD_5")
        with self.assertRaises(BadRequest):
            engine.request_amendment(
                allocation,
                kind="reforecast",
                reason="More everywhere.",
                new_quarters={"Q1": "30", "Q2": "30", "Q3": "30", "Q4": "30"},
                principal=self.ia,
            )


class RateAchievementTests(DistributionFixture):
    def test_rate_achievement_uses_the_portfolio_denominator_not_unit_division(self):
        milestone = self._milestone(
            "RATE_1", target="90", measurement="percentage", cap_at_100=True
        )
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        rule = MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="PERCENT_OF_ELIGIBLE_SCHOOLS",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        allocation = self._team_allocation(milestone, self.pl_sp, 90)
        allocation.denominator = Decimal("4")
        allocation.save(update_fields=["denominator"])
        approve_allocation(allocation, principal=self.ia)
        schools = self.schools_by_staff[self.cceo_a_sp.id][:2]
        for school in schools:
            activity = Activity.objects.create(
                activity_type=item.workflow_kind,
                status="ia_verified",
                salesforce_activity_id=f"VS-CREDIT-{school.school_id}",
                planned_date=date(2026, 10, 15),
                fy=FY,
                school=school,
                responsible_staff_id=self.cceo_a_sp.id,
                focus_intervention="christlike_behaviour",
            )
            apply_catalogue_snapshot(
                activity,
                item=item,
                requested_intervention="christlike_behaviour",
            )
            record_activity_progress(activity)
        october = allocation.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )
        # 2 of 4 schools = 50% coverage against a 90% commitment → 55.56%.
        self.assertEqual(october.actual_value, Decimal("2"))
        self.assertAlmostEqual(float(october.achievement_percentage), 55.56, places=1)

    def _credit_schools(self, milestone_code, *, rate, denominator, cover):
        """One rate milestone, an approved allocation with the given
        denominator, and `cover` verified school visits credited against it.
        Returns the October period row the progress engine wrote."""
        milestone = self._milestone(
            milestone_code, target=str(rate), measurement="percentage", cap_at_100=True
        )
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="PERCENT_OF_ELIGIBLE_SCHOOLS",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        allocation = self._team_allocation(milestone, self.pl_sp, rate)
        allocation.denominator = Decimal(str(denominator)) if denominator else None
        allocation.save(update_fields=["denominator"])
        approve_allocation(allocation, principal=self.ia)
        for school in self.schools_by_staff[self.cceo_a_sp.id][:cover]:
            activity = Activity.objects.create(
                activity_type=item.workflow_kind,
                status="ia_verified",
                salesforce_activity_id=f"VS-{milestone_code}-{school.school_id}",
                planned_date=date(2026, 10, 15),
                fy=FY,
                school=school,
                responsible_staff_id=self.cceo_a_sp.id,
                focus_intervention="christlike_behaviour",
            )
            apply_catalogue_snapshot(
                activity, item=item, requested_intervention="christlike_behaviour"
            )
            record_activity_progress(activity)
        return allocation.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )

    def test_meeting_the_rate_scores_one_hundred_percent(self):
        """Owner's rule (2026-08-24): cover the committed share of your own
        portfolio and the target is MET — 2 of 4 schools against a 50%
        commitment is 100% achievement, not 50%."""
        october = self._credit_schools("RATE_MET", rate=50, denominator=4, cover=2)

        self.assertEqual(october.achievement_percentage, Decimal("100"))

    def test_full_coverage_of_a_lower_rate_is_extra(self):
        """All 4 of 4 schools against a 90% commitment: coverage caps at 100,
        achievement is 111.11 — the surplus survives the cap because the cap
        is on coverage, never on the achievement ratio."""
        october = self._credit_schools("RATE_XTRA", rate=90, denominator=4, cover=4)

        self.assertAlmostEqual(float(october.achievement_percentage), 111.11, places=1)

    def test_coverage_past_the_portfolio_is_capped_before_the_ratio(self):
        """4 credits against a recorded denominator of 3 is a data problem —
        coverage caps at 100 first, so achievement lands at 111.11 against a
        90% rate rather than parading 148%."""
        october = self._credit_schools("RATE_GLITCH", rate=90, denominator=3, cover=4)

        self.assertAlmostEqual(float(october.achievement_percentage), 111.11, places=1)

    def test_a_missing_denominator_scores_an_honest_zero(self):
        """Without a denominator, coverage cannot be computed. The old
        fallback divided raw units by the rate — 4 units against 90 read as
        4.4% — which is dimensional nonsense wearing a number. Now it is an
        honest zero and a loud log line."""
        october = self._credit_schools("RATE_NODEN", rate=90, denominator=None, cover=4)

        self.assertEqual(october.achievement_percentage, Decimal("0"))
        self.assertEqual(october.actual_value, Decimal("4"))


class CreditReversalTests(DistributionFixture):
    def test_a_returned_activity_reverses_its_milestone_credit(self):
        milestone = self._milestone("REV_1", target="10")
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="VERIFIED_ACTIVITIES",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        allocation = self._team_allocation(milestone, self.pl_sp, 10)
        approve_allocation(allocation, principal=self.ia)
        activity = Activity.objects.create(
            activity_type=item.workflow_kind,
            status="ia_verified",
            salesforce_activity_id="VS-CREDIT-TEAM-1",
            planned_date=date(2026, 10, 20),
            fy=FY,
            responsible_staff_id=self.cceo_a_sp.id,
            focus_intervention="christlike_behaviour",
        )
        apply_catalogue_snapshot(
            activity, item=item, requested_intervention="christlike_behaviour"
        )
        self.assertEqual(record_activity_progress(activity), 1)
        october = allocation.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )
        self.assertEqual(october.actual_value, Decimal("1"))

        activity.status = "returned"
        activity.save(update_fields=["status"])
        self.assertEqual(reverse_activity_progress(activity), 1)
        # Credits are append-only: the row survives as history, stamped
        # reversed, and stops counting. Deleting it would erase the fact that
        # the work was once credited.
        credit = MilestoneProgressCredit.objects.get(activity=activity)
        self.assertIsNotNone(credit.reversed_at)
        october.refresh_from_db()
        self.assertEqual(october.actual_value, Decimal("0"))


class IaWorkspaceCreditTests(DistributionFixture):
    def test_the_live_ia_workspace_path_credits_milestones_too(self):
        # The audit's severest finding: only the DRF ia_confirm path wrote
        # milestone credits; the certification service behind the actual IA
        # workspace wrote none, so every Uganda allocation's actuals stayed
        # at zero in production. This pins the fix.
        from apps.activities.ia_services import ActivityCertificationService

        milestone = self._milestone("IAUI_1", target="10")
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="VERIFIED_ACTIVITIES",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        allocation = self._team_allocation(milestone, self.pl_sp, 10)
        approve_allocation(allocation, principal=self.ia)
        activity = Activity.objects.create(
            activity_type=item.workflow_kind,
            status="awaiting_ia_verification",
            # Present before verification, as the workflow requires: the
            # reference is locked once IA confirms, so it can never be added
            # afterwards.
            salesforce_activity_id="VS-CREDIT-WORKSPACE-1",
            planned_date=date(2026, 10, 22),
            fy=FY,
            responsible_staff_id=self.cceo_a_sp.id,
            focus_intervention="christlike_behaviour",
        )
        apply_catalogue_snapshot(
            activity, item=item, requested_intervention="christlike_behaviour"
        )
        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(
            MilestoneProgressCredit.objects.filter(activity=activity).count(),
            1,
        )
        october = allocation.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )
        self.assertEqual(october.actual_value, Decimal("1"))

    def test_verified_work_appears_on_the_country_tracker(self):
        """The CD/IA master tracker is the same workspace page: the verified
        credit written above must surface as a per-milestone delivery figure
        and in the country-delivery headline, with no snapshot in between —
        that immediacy is the whole point of the tracker."""
        self.test_the_live_ia_workspace_path_credits_milestones_too()

        self.client.force_login(self.ia)
        response = self.client.get(f"/target-distribution?fy={FY}")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Verified delivery", body)
        self.assertIn("Country delivery", body)
        # The one credited activity against the 10-unit milestone.
        self.assertIn("1 of 10", body)


class PlannedOutputTests(DistributionFixture):
    def test_scheduling_raises_planned_output_and_cancelling_returns_it(self):
        milestone = self._milestone("PLN_1", target="10")
        item = ActivityCatalogueItem.objects.get(
            stable_code="CLA_CHARACTER_DEVELOPMENT"
        )
        MilestoneActivityRule.objects.create(
            milestone=milestone,
            catalogue_item=item,
            counting_basis="VERIFIED_ACTIVITIES",
            minimum_completion_state="ia_verified",
            weight=1,
        )
        team = self._team_allocation(milestone, self.pl_sp, 10)
        approve_allocation(team, principal=self.ia)
        child = self._employee_allocation(milestone, self.cceo_a_sp, 10, parent=team)
        approve_allocation(child, principal=self.pl)
        activity = Activity.objects.create(
            activity_type=item.workflow_kind,
            status="scheduled",
            planned_date=date(2026, 10, 20),
            fy=FY,
            responsible_staff_id=self.cceo_a_sp.id,
            focus_intervention="christlike_behaviour",
        )
        apply_catalogue_snapshot(
            activity, item=item, requested_intervention="christlike_behaviour"
        )
        self.assertEqual(engine.planned_output(child), Decimal("1"))
        # Verified actual stays untouched — the four figures never blur.
        october = child.period_targets.get(
            period_type="month", period_start=date(2026, 10, 1)
        )
        self.assertEqual(october.actual_value, Decimal("0"))

        activity.status = "cancelled"
        activity.save(update_fields=["status"])
        self.assertEqual(engine.planned_output(child), Decimal("0"))


class MasterGovernanceTests(DistributionFixture):
    def _confirm_all(self):
        flagged = PriorityMilestone.objects.filter(
            priority__level="country",
            priority__country_id="Uganda",
            needs_confirmation=True,
        ).exclude(allocation_method="non_scoreable")
        for milestone in flagged:
            engine.confirm_milestone(milestone, data={}, principal=self.cd)

    def test_publish_refuses_while_source_figures_are_unconfirmed(self):
        with self.assertRaises(BadRequest) as ctx:
            engine.publish_uganda_master(FY, principal=self.cd)
        self.assertIn("Confirm these source figures", str(ctx.exception))

    def test_only_the_cd_confirms_and_publishes(self):
        milestone = PriorityMilestone.objects.get(
            code="ECD_TEACHERS", priority__level="country"
        )
        with self.assertRaises(BadRequest):
            engine.confirm_milestone(milestone, data={}, principal=self.ia)
        self._confirm_all()
        with self.assertRaises(BadRequest):
            engine.publish_uganda_master(FY, principal=self.ia)

    def test_publication_locks_the_master_and_activates_scoreable_milestones(self):
        self._confirm_all()
        activated = engine.publish_uganda_master(FY, principal=self.cd)
        self.assertGreater(activated, 40)
        dc = PriorityMilestone.objects.get(
            code="DC_TRAINING", priority__level="country"
        )
        self.assertTrue(dc.active)
        self.assertEqual(dc.priority.status, "published")
        tot = PriorityMilestone.objects.get(
            code="TOT_TRAININGS", priority__level="country"
        )
        self.assertFalse(tot.active)
        # Locked: confirmation now refuses.
        with self.assertRaises(BadRequest):
            engine.confirm_milestone(dc, data={}, principal=self.cd)

    def test_reseeding_cannot_reset_or_replace_a_published_master(self):
        confirmed = PriorityMilestone.objects.get(
            code="ECD_TEACHERS", priority__level="country"
        )
        engine.confirm_milestone(
            confirmed,
            data={"targetValue": "321"},
            principal=self.cd,
        )
        self._confirm_all()
        engine.publish_uganda_master(FY, principal=self.cd)

        report = seed_uganda_master(actor_id="deployment-rerun")

        confirmed.refresh_from_db()
        self.assertEqual(confirmed.target_value, Decimal("321"))
        self.assertEqual(confirmed.definition_status, "approved")
        self.assertTrue(confirmed.active)
        self.assertEqual(confirmed.priority.status, "published")
        self.assertGreater(report["skippedPublished"], 0)

    def test_participant_guidance_flows_from_the_published_master_only(self):
        item = ActivityCatalogueItem.objects.get(stable_code="DISCIPLESHIP_DYNAMICS")
        self.assertIsNone(engine.participant_guidance_for(item.id))
        self._confirm_all()
        engine.publish_uganda_master(FY, principal=self.cd)
        # DC Training carries 1 participant per school in the source document.
        self.assertEqual(engine.participant_guidance_for(item.id), 1)


class WorkspacePageTests(DistributionFixture):
    def _publish_master(self):
        flagged = PriorityMilestone.objects.filter(
            priority__level="country",
            priority__country_id="Uganda",
            needs_confirmation=True,
        ).exclude(allocation_method="non_scoreable")
        for milestone in flagged:
            engine.confirm_milestone(milestone, data={}, principal=self.cd)
        engine.publish_uganda_master(FY, principal=self.cd)

    def test_the_ia_workspace_renders_with_reconciliation_state(self):
        self.client.force_login(self.ia)
        response = self.client.get("/target-distribution")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Uganda Target Distribution")
        self.assertContains(response, "DC Training")
        self.assertContains(response, "Remaining to distribute")
        self.assertContains(response, "Every row below is fetched")

    def test_the_country_workspace_builds_staff_capacity_once(self):
        with patch.object(
            engine,
            "_staff_recommendation_context",
            wraps=engine._staff_recommendation_context,
        ) as capacity_context:
            workspace = engine.country_distribution_workspace(FY)

        self.assertTrue(workspace["groups"])
        self.assertEqual(capacity_context.call_count, 1)

    def test_the_cd_sees_the_confirmation_controls(self):
        self.client.force_login(self.cd)
        response = self.client.get("/target-distribution")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm source figure")

    def test_field_roles_cannot_open_the_country_workspace(self):
        self.client.force_login(self.cceo_a)
        response = self.client.get("/target-distribution")
        self.assertNotEqual(response.status_code, 200)

    def test_the_distribution_form_is_loaded_from_the_published_database_master(self):
        self._publish_master()
        milestone = PriorityMilestone.objects.get(
            code="DC_TRAINING", priority__level="country"
        )
        self.client.force_login(self.ia)
        workspace = self.client.get("/target-distribution", {"fy": FY})
        self.assertContains(workspace, "To Program Leads")
        self.assertContains(workspace, "data-open-distribution")
        response = self.client.get(
            "/target-distribution/form", {"milestone": milestone.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Priority Group")
        self.assertContains(response, "Distribute to Program Leads")
        self.assertContains(response, "PL One")
        self.assertContains(response, "4,157")

    def test_only_ia_can_load_the_program_lead_distribution_form(self):
        self._publish_master()
        milestone = PriorityMilestone.objects.get(
            code="DC_TRAINING", priority__level="country"
        )
        self.client.force_login(self.cd)
        response = self.client.get(
            "/target-distribution/form", {"milestone": milestone.id}
        )
        self.assertEqual(response.status_code, 403)

    def test_ia_can_save_and_approve_a_zero_balance_in_one_form_submission(self):
        milestone = self._milestone("PAGE_FORM", target="100")
        self.client.force_login(self.ia)
        response = self.client.post(
            "/target-distribution/action",
            {
                "action": "save_and_approve_team_distribution",
                "fy": FY,
                "milestone": milestone.id,
                f"target__{self.pl_sp.id}": "60",
                f"target__{self.pl2_sp.id}": "40",
                "reason": "Reference-form zero-balance distribution.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            MilestoneAllocation.objects.filter(milestone=milestone)
            .exclude(status="approved")
            .exists()
        )

    def test_the_pl_workspace_is_scoped_to_their_own_team(self):
        milestone = self._milestone("PAGE_1", target="40")
        team = self._team_allocation(milestone, self.pl_sp, 40)
        approve_allocation(team, principal=self.ia)
        self.client.force_login(self.pl)
        response = self.client.get("/target-distribution/team")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test milestone PAGE_1")
        self.assertContains(response, "CCEO Alpha")
        self.assertContains(response, "PL One")
        self.assertContains(response, "Program Lead · You")
        self.assertContains(response, "Team distribution command")
        self.assertContains(response, "Distribute within team")
        self.assertContains(response, "Team priority distribution")
        self.assertContains(response, "Unassigned from your IA allocation")
        self.assertEqual(response.context["kpis"]["openActions"], 1)
        self.assertIsNotNone(response.context["next_team_distribution"])
        self.client.force_login(self.pl2)
        response = self.client.get("/target-distribution/team")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Test milestone PAGE_1")

    def test_remaining_is_scoped_to_only_the_pls_approved_ia_allocation(self):
        milestone = self._milestone("PAGE_SCOPED", target="100")
        pl_one = self._team_allocation(milestone, self.pl_sp, 40)
        pl_two = self._team_allocation(milestone, self.pl2_sp, 60)
        approve_allocation(pl_one, principal=self.ia)
        approve_allocation(pl_two, principal=self.ia)

        self.client.force_login(self.pl)
        response = self.client.get("/target-distribution/team")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["kpis"]["totalTeamTarget"], Decimal("40"))
        self.assertEqual(response.context["kpis"]["remainingTarget"], Decimal("40"))
        self.assertNotContains(response, "60.00")

    def test_the_full_cascade_reaches_the_cceo_as_an_official_priority(self):
        from .milestone_allocations import personal_milestone_targets

        milestone = self._milestone("PAGE_2", target="40")
        self.client.force_login(self.ia)
        self.client.post(
            "/target-distribution/action",
            {
                "action": "save_team_allocations",
                "fy": FY,
                "milestone": milestone.id,
                f"target__{self.pl_sp.id}": "40",
                "reason": "Annual distribution.",
            },
        )
        self.client.post(
            "/target-distribution/action",
            {
                "action": "approve_team_distribution",
                "fy": FY,
                "milestone": milestone.id,
            },
        )
        team = MilestoneAllocation.objects.get(
            milestone=milestone, allocated_to_type="team"
        )
        self.assertEqual(team.status, "approved")
        self.client.force_login(self.pl)
        self.client.post(
            "/target-distribution/team/action",
            {
                "action": "save_member_allocations",
                "fy": FY,
                "allocation": team.id,
                f"target__{self.cceo_a_sp.id}": "25",
                f"target__{self.cceo_b_sp.id}": "15",
                "reason": "Team distribution.",
            },
        )
        self.client.post(
            "/target-distribution/team/action",
            {"action": "approve_member_distribution", "fy": FY, "allocation": team.id},
        )
        personal = personal_milestone_targets(
            staff=self.cceo_a_sp, fy=FY, month_of_fy=1
        )
        mine = [row for row in personal if row["milestone"].endswith("PAGE_2")]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["fyPlan"], Decimal("25"))
        self.assertIn("classification", mine[0])
        child = MilestoneAllocation.objects.get(
            milestone=milestone, employee=self.cceo_a_sp
        )
        self.assertEqual(str(child.parent_id), str(team.id))

    def test_another_pl_cannot_write_into_a_foreign_team(self):
        milestone = self._milestone("PAGE_3", target="40")
        team = self._team_allocation(milestone, self.pl_sp, 40)
        approve_allocation(team, principal=self.ia)
        self.client.force_login(self.pl2)
        self.client.post(
            "/target-distribution/team/action",
            {
                "action": "save_member_allocations",
                "fy": FY,
                "allocation": team.id,
                f"target__{self.cceo_c_sp.id}": "40",
                "reason": "Should not land.",
            },
        )
        self.assertFalse(
            MilestoneAllocation.objects.filter(
                milestone=milestone, employee=self.cceo_c_sp
            ).exists()
        )

    def test_pl_can_save_and_approve_a_zero_balance_in_one_submission(self):
        milestone = self._milestone("PAGE_ONE_STEP", target="40")
        team = self._team_allocation(milestone, self.pl_sp, 40)
        approve_allocation(team, principal=self.ia)
        self.client.force_login(self.pl)

        response = self.client.post(
            "/target-distribution/team/action",
            {
                "action": "save_and_approve_member_distribution",
                "fy": FY,
                "allocation": team.id,
                f"target__{self.cceo_a_sp.id}": "25",
                f"target__{self.cceo_b_sp.id}": "15",
                "reason": "One-step governed CCEO distribution.",
            },
        )

        self.assertEqual(response.status_code, 302)
        children = MilestoneAllocation.objects.filter(parent=team)
        self.assertEqual(children.count(), 2)
        self.assertFalse(children.exclude(status="approved").exists())


class SeedCycleGuardTests(TestCase):
    def test_seeding_without_a_regional_cycle_is_refused(self):
        self.assertFalse(
            StrategicPriorityCycle.objects.filter(financial_year="2031").exists()
        )
        with self.assertRaises(BadRequest):
            seed_uganda_master(fy="2031")
