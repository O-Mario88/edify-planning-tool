"""§4/§5 Daily Field Cost (School Visit) — the analytical layer.

The spec's own worked examples, as tests: weighted allocation on mixed days,
planned vs actual per-school figures, the never-divide-by-zero rule, and the
versioned CD-configurable weights. None of this ever touches funding lines.
"""

from types import SimpleNamespace

from django.test import TestCase

from apps.core.exceptions import BadRequest, Forbidden
from apps.daily_visit_batches.models import ActivityWorkloadWeight
from apps.daily_visit_batches.workload import (
    allocate_mission_cost,
    live_weights,
    set_weight,
)


def _act(activity_type):
    return SimpleNamespace(activity_type=activity_type)


class _P:
    def __init__(self, role, user_id="w-user"):
        self.active_role = role
        self.user_id = user_id


class MixedMissionAllocationTest(TestCase):
    def test_spec_example_two_visits_one_cluster_meeting(self):
        """§5: 2 visits (1.0 each) + 1 cluster meeting (2.0) on an 80,000
        mission → 40,000 allocated to visits → 20,000 per school."""
        result = allocate_mission_cost(
            [_act("school_visit"), _act("school_visit"), _act("cluster_meeting")],
            80_000,
        )
        self.assertEqual(result["total_units"], 400)
        self.assertEqual(result["visit_units"], 200)
        self.assertEqual(result["school_visit_allocation"], 40_000)
        self.assertEqual(result["planned_field_cost_per_school"], 20_000)

    def test_visit_only_day_allocates_the_whole_mission(self):
        """§4.1: school-visit-only day — mission ÷ planned visits."""
        result = allocate_mission_cost([_act("school_visit")] * 4, 80_000)
        self.assertEqual(result["school_visit_allocation"], 80_000)
        self.assertEqual(result["planned_field_cost_per_school"], 20_000)

    def test_no_visits_means_no_school_figure(self):
        result = allocate_mission_cost([_act("cluster_meeting")], 80_000)
        self.assertIsNone(result["school_visit_allocation"])
        self.assertIsNone(result["planned_field_cost_per_school"])

    def test_ssa_weight_is_heavier_than_a_standard_visit(self):
        weights = live_weights()
        self.assertEqual(weights["school_visit"], 100)
        self.assertEqual(weights["baseline_ssa_visit"], 150)
        self.assertEqual(weights["cluster_meeting"], 200)


class WeightConfigurationTest(TestCase):
    def test_cd_sets_a_weight_and_it_becomes_live(self):
        set_weight("cluster_meeting", 3.0, _P("CountryDirector"), reason="pilot")
        self.assertEqual(live_weights()["cluster_meeting"], 300)

    def test_weights_are_versioned_for_audit(self):
        set_weight("cluster_meeting", 3.0, _P("CountryDirector"))
        set_weight("cluster_meeting", 2.5, _P("Admin"), reason="revised")
        versions = list(
            ActivityWorkloadWeight.objects.filter(activity_type="cluster_meeting")
            .order_by("version")
            .values_list("version", "weight_hundredths")
        )
        self.assertEqual(versions, [(1, 300), (2, 250)])
        self.assertEqual(live_weights()["cluster_meeting"], 250)

    def test_only_cd_or_admin_may_configure(self):
        with self.assertRaises(Forbidden):
            set_weight("cluster_meeting", 3.0, _P("CCEO"))

    def test_a_weight_must_be_positive(self):
        with self.assertRaises(BadRequest):
            set_weight("cluster_meeting", 0, _P("CountryDirector"))


class ActualFieldCostTest(TestCase):
    """§4.2/§11 against a real batch: actual divides by COMPLETED visits and
    is Not Calculable (None) at zero completions."""

    def _batch(self, statuses):
        from datetime import date

        from django.contrib.auth import get_user_model

        from apps.activities.models import Activity
        from apps.daily_visit_batches.models import DailyVisitBatch
        from apps.daily_visit_batches.workload import actual_field_cost_per_school
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="W Region")
        district = District.objects.create(
            name="W District", region=region, district_type="primary"
        )
        get_user_model().objects.create(
            id="w-cceo",
            email="w@t.org",
            name="W",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        batch = DailyVisitBatch.objects.create(
            responsible_user="w-cceo",
            visit_date=date(2026, 8, 6),
            district_type="primary",
            daily_pool_amount=80_000,
            school_visit_allocation=80_000,
            planned_field_cost_per_school=20_000,
            workload_snapshot={"visit_count": 4},
        )
        for i, status in enumerate(statuses):
            school = School.objects.create(
                school_id=f"W-{i}", name=f"W {i}", region=region, district=district
            )
            Activity.objects.create(
                school=school,
                activity_type="school_visit",
                delivery_type="staff",
                status=status,
                responsible_staff_id="w-cceo",
                fy="2026",
                daily_visit_batch=batch,
            )
        return batch, actual_field_cost_per_school(batch)

    def test_three_of_four_completed_recalculates_actual(self):
        _batch, actual = self._batch(
            ["completed", "completed", "completed", "cancelled"]
        )
        self.assertEqual(actual, 26_667)

    def test_zero_completed_is_not_calculable_never_divide_by_zero(self):
        _batch, actual = self._batch(["cancelled", "cancelled"])
        self.assertIsNone(actual)
