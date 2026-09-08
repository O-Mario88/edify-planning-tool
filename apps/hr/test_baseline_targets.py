"""Baseline targets for the plan-linked milestones (owner, 2026-09-07: "Set
targets for the linked milestones so the percentages show").

Set through the governed define path — DEFINED, never approved — from one of
two defensible sources: last year's own delivery, or the size of the school
family a coverage milestone is a fraction of. A milestone with neither is
reported, not guessed.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.services import apply_catalogue_snapshot
from apps.hr.management.commands.set_milestone_baseline_targets import (
    derive_baseline,
    set_baseline_targets,
)
from apps.hr.models import PriorityMilestone
from apps.hr.priority_seeding import seed_fy2027_priorities
from apps.schools.models import School


class BaselineTargetsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_fy2027_priorities(actor_id="test")
        cls.core_school = School.objects.create(
            name="Core One",
            school_id="BASE-C1",
            school_type="core",
            operational_status="active",
        )
        cls.client_school = School.objects.create(
            name="Client One",
            school_id="BASE-K1",
            school_type="client",
            operational_status="active",
        )

    def _visit(self, school, status, fy):
        item = ActivityCatalogueItem.objects.get(stable_code="STANDARD_SCHOOL_VISIT")
        activity = Activity.objects.create(
            activity_type="school_visit",
            status=status,
            school=school,
            fy=fy,
            planned_date=date(int(fy), 3, 1),
        )
        apply_catalogue_snapshot(activity, item=item, requested_intervention=None)
        activity.save()
        return activity

    def test_last_years_delivery_becomes_the_floor(self):
        self._visit(self.core_school, "completed", "2026")
        self._visit(self.client_school, "completed", "2026")
        self._visit(self.client_school, "scheduled", "2026")
        report = set_baseline_targets(fy="2027", baseline_fy="2026")
        visits = PriorityMilestone.objects.get(code="SCHOOL_VISITS")
        self.assertEqual(visits.target_value, Decimal("3"))
        self.assertEqual(visits.target_unit, "activities")
        self.assertEqual(visits.definition_status, "defined")
        self.assertFalse(visits.active)  # approval stays the RVP's
        self.assertIsNotNone(visits.metric_definition)
        self.assertIn("at least match it", visits.metric_definition.description)
        row = next(r for r in report["set"] if r["code"] == "SCHOOL_VISITS")
        self.assertEqual(row["target"], "3")

    def test_a_coverage_milestone_with_no_history_takes_its_family_size(self):
        set_baseline_targets(fy="2027", baseline_fy="2026")
        core_ssa = PriorityMilestone.objects.get(code="CORE_SSA_COVERAGE")
        self.assertEqual(
            core_ssa.target_value, Decimal("1")
        )  # one core school in this test
        self.assertEqual(core_ssa.target_unit, "schools")
        everyone = PriorityMilestone.objects.get(code="SCHOOLS_TRAINED")
        self.assertEqual(everyone.target_value, Decimal("2"))

    def test_source_targets_and_conservative_fallback_cover_every_linked_row(self):
        report = set_baseline_targets(fy="2027", baseline_fy="2026")
        self.assertEqual(report["counts"]["skipped"], 0)
        self.assertFalse(
            PriorityMilestone.objects.filter(
                priority__fy="2027",
                activity_rules__active=True,
                target_value__isnull=True,
            ).exists()
        )
        self.assertEqual(
            PriorityMilestone.objects.get(code="CLA").target_value, Decimal("4119")
        )
        self.assertEqual(
            PriorityMilestone.objects.get(code="PARTNER_REVIEW_MEETINGS").target_value,
            Decimal("4"),
        )
        # No numeric source exists for this activity-shaped row. It still gets
        # a visible, explicitly provisional percentage rather than a blank.
        safeguarding = PriorityMilestone.objects.get(code="SAFEGUARDING_TRAINING")
        self.assertEqual(safeguarding.target_value, Decimal("1"))
        self.assertIn(
            "RVP confirmation required", safeguarding.metric_definition.description
        )

    def test_an_existing_target_is_kept_unless_overwritten(self):
        self._visit(self.core_school, "completed", "2026")
        set_baseline_targets(fy="2027", baseline_fy="2026")
        visits = PriorityMilestone.objects.get(code="SCHOOL_VISITS")
        visits.target_value = Decimal("99")
        visits.save(update_fields=["target_value"])
        report = set_baseline_targets(fy="2027", baseline_fy="2026")
        self.assertIn("SCHOOL_VISITS", {r["code"] for r in report["kept"]})
        self.assertEqual(
            PriorityMilestone.objects.get(code="SCHOOL_VISITS").target_value,
            Decimal("99"),
        )
        set_baseline_targets(fy="2027", baseline_fy="2026", overwrite=True)
        self.assertEqual(
            PriorityMilestone.objects.get(code="SCHOOL_VISITS").target_value,
            Decimal("1"),
        )

    def test_a_dry_run_writes_nothing(self):
        self._visit(self.core_school, "completed", "2026")
        report = set_baseline_targets(fy="2027", baseline_fy="2026", dry_run=True)
        self.assertGreater(report["counts"]["set"], 0)
        self.assertIsNone(
            PriorityMilestone.objects.get(code="SCHOOL_VISITS").target_value
        )

    def test_the_meter_shows_a_percentage_once_a_target_exists(self):
        from apps.hr.target_distribution import milestone_plan_progress

        self._visit(self.core_school, "completed", "2026")
        self._visit(self.client_school, "completed", "2026")
        set_baseline_targets(fy="2027", baseline_fy="2026")  # target 2
        self._visit(self.core_school, "completed", "2027")  # one done this year
        visits = PriorityMilestone.objects.get(code="SCHOOL_VISITS")
        row = milestone_plan_progress([visits], fy="2027")[visits.id]
        self.assertEqual(row["pct"], 50.0)

    def test_derive_baseline_prefers_history_over_coverage(self):
        m = PriorityMilestone.objects.get(code="CORE_SSA_COVERAGE")
        target, unit, how = derive_baseline(
            m,
            {"unit": "schools", "completed": 5, "planned": 1},
            {"core": 100, "client": 0, "all": 100},
        )
        self.assertEqual((target, unit), (Decimal("6"), "schools"))
        target, unit, how = derive_baseline(
            m,
            {"unit": "schools", "completed": 0, "planned": 0},
            {"core": 100, "client": 0, "all": 100},
        )
        self.assertEqual((target, unit), (Decimal("100"), "schools"))

    def test_explicit_source_and_cadence_precede_the_one_unit_fallback(self):
        cla = PriorityMilestone.objects.get(code="CLA")
        target, unit, how = derive_baseline(
            cla,
            {"unit": "schools", "completed": 0, "planned": 0},
            {"core": 0, "client": 0, "all": 0},
        )
        self.assertEqual((target, unit), (Decimal("4119"), "schools"))
        self.assertIn("Uganda July Plan", how)

        monthly = PriorityMilestone.objects.get(code="MONTHLY_MFI_MENTORSHIP")
        target, unit, how = derive_baseline(
            monthly,
            {"unit": "activities", "completed": 0, "planned": 0},
            {"core": 0, "client": 0, "all": 0},
        )
        self.assertEqual((target, unit), (Decimal("12"), "activities"))
        self.assertIn("monthly", how)
