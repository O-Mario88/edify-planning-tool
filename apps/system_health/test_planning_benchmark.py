"""The planning benchmark must refuse to conclude what it cannot measure."""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.system_health.planning_benchmark import (
    Benchmark,
    Observation,
    mechanical_profile,
    report,
)


def _observation(variant, active, **overrides):
    payload = dict(
        role="CCEO",
        task="schedule one funded school visit",
        variant=variant,
        elapsed_seconds=active * 1.2,
        active_seconds=active,
        pages_visited=3,
        clicks=12,
        fields_typed=4,
        repeated_entries=0,
        validation_errors=0,
    )
    payload.update(overrides)
    return Observation(**payload)


class MechanicalProfileTests(SimpleTestCase):
    def test_the_planner_supplies_only_the_genuine_decisions(self):
        profile = mechanical_profile()
        self.assertEqual(
            set(profile["human_field_names"]),
            {"school_or_cluster", "scheduled_date", "executor", "override_reason"},
        )

    def test_nothing_is_re_entered_downstream(self):
        """§2's second gate: no duplicate entry of school, cost, period or approver."""
        self.assertEqual(mechanical_profile()["repeated_entries"], 0)

    def test_the_automation_ratio_is_computed_from_the_field_list(self):
        profile = mechanical_profile()
        self.assertEqual(
            profile["fields_human"] + profile["fields_platform"],
            profile["fields_total"],
        )
        self.assertGreater(profile["automation_ratio"], 80)


class ReductionHonestyTests(SimpleTestCase):
    """The half that matters: refusing to claim what was not observed."""

    def test_no_observations_means_no_percentage(self):
        result = Benchmark().reduction()
        self.assertFalse(result["verified"])
        self.assertIn("representative staff", result["reason"])
        self.assertNotIn("reduction_percent", result)

    def test_optimised_alone_proves_nothing(self):
        bench = Benchmark()
        for seconds in (55, 60, 58):
            bench.record(_observation("optimised", seconds))
        result = bench.reduction()
        self.assertFalse(result["verified"])
        self.assertIsNone(result["baseline_median_active_seconds"])

    def test_a_near_miss_is_reported_as_a_miss(self):
        """The case worth pinning: 94.7% is not 95%, and must not round up."""
        bench = Benchmark()
        for seconds in (1200, 1140, 1260):
            bench.record(_observation("baseline", seconds))
        # Median 64s against a median baseline of 1200s = 94.67%.
        for seconds in (62, 64, 66):
            bench.record(_observation("optimised", seconds))
        result = bench.reduction()
        self.assertTrue(result["verified"])
        self.assertAlmostEqual(result["reduction_percent"], 94.7, places=1)
        self.assertFalse(result["meets_95_percent_target"])

    def test_the_target_is_met_only_when_it_is_actually_met(self):
        bench = Benchmark()
        for seconds in (1200, 1200, 1200):
            bench.record(_observation("baseline", seconds))
        for seconds in (50, 55, 45):
            bench.record(_observation("optimised", seconds))
        result = bench.reduction()
        self.assertTrue(result["meets_95_percent_target"])

    def test_abandoned_attempts_are_excluded_from_the_median(self):
        """An abandoned attempt is not a fast one."""
        bench = Benchmark()
        bench.record(_observation("baseline", 1200))
        bench.record(_observation("baseline", 1, abandoned=True))
        bench.record(_observation("optimised", 60))
        self.assertEqual(bench.reduction()["baseline_median_active_seconds"], 1200)

    def test_the_platform_report_states_the_time_gate_as_unverified(self):
        result = report()
        self.assertFalse(result["time_reduction"]["verified"])
        self.assertGreater(result["mechanical"]["automation_ratio"], 80)
