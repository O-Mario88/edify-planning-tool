from django.test import SimpleTestCase

from apps.analytics.platform_engine import (
    ENGINE_NAME,
    completion_analysis,
    correlation_analysis,
    describe_numeric,
    finance_health,
    planning_health,
    robust_outlier_analysis,
    trend_analysis,
    variance_analysis,
)


class PlatformAnalyticsEngineTest(SimpleTestCase):
    def test_numeric_description_cleans_missing_values_and_compares_periods(self):
        result = describe_numeric(
            [4, 6, None, "8", "bad"],
            previous_values=[3, 5, 7],
            target=6,
        )
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["missing"], 2)
        self.assertEqual(result["mean"], 6.0)
        self.assertEqual(result["median"], 6.0)
        self.assertEqual(result["delta"], 1.0)
        self.assertEqual(result["target_gap"], 0.0)

    def test_completion_and_variance_use_one_operational_definition(self):
        completion = completion_analysis(8, 10)
        variance = variance_analysis(1_000_000, 900_000)
        self.assertEqual(completion["rate"], 80.0)
        self.assertEqual(completion["remaining"], 2)
        self.assertEqual(variance["variance"], -100_000.0)
        self.assertEqual(variance["variance_pct"], -10.0)
        self.assertEqual(variance["status"], "off_plan")

    def test_trend_and_correlation_are_statistically_interpreted(self):
        trend = trend_analysis([2, 3, 4, 5, 6])
        correlation = correlation_analysis([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12])
        self.assertEqual(trend["direction"], "improving")
        self.assertGreater(trend["r_squared"], 0.99)
        self.assertEqual(correlation["direction"], "positive")
        self.assertEqual(correlation["strength"], "very_strong")

    def test_small_or_constant_samples_are_not_overclaimed(self):
        result = correlation_analysis([1, 1, 1], [4, 5, 6], minimum_sample=3)
        self.assertIsNone(result["coefficient"])
        self.assertEqual(result["strength"], "insufficient_data")

    def test_robust_outliers_identify_material_anomalies(self):
        result = robust_outlier_analysis(
            [10, 10, 11, 9, 10, 100],
            labels=["A", "B", "C", "D", "E", "Risk"],
        )
        self.assertEqual(len(result["outliers"]), 1)
        self.assertEqual(result["outliers"][0]["label"], "Risk")

    def test_domain_health_models_share_engine_provenance(self):
        planning = planning_health(
            total=100, ready=72, scheduled=60, at_risk=8, overdue=4
        )
        finance = finance_health(
            approved=1_000_000,
            disbursed=800_000,
            accounted=700_000,
            returned=50_000,
            reconciled_count=7,
            disbursed_count=10,
        )
        self.assertEqual(planning["engine"]["name"], ENGINE_NAME)
        self.assertEqual(finance["engine"]["name"], ENGINE_NAME)
        self.assertEqual(finance["reconciliation"]["rate"], 70.0)
