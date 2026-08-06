"""Regression tests for deployment-blocking workflow-health predicates."""

from django.test import TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.system_health.services import missing_cost_lines_count


class MissingCostLinesContractTest(TestCase):
    def _activity(self, *, cost: int) -> Activity:
        return Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            fy="FY26",
            quarter="Q1",
            est_cost_cents=cost,
        )

    def test_zero_cost_scheduled_work_does_not_require_a_budget_line(self):
        self._activity(cost=0)

        self.assertEqual(missing_cost_lines_count(), 0)

    def test_cost_bearing_scheduled_work_without_lines_blocks(self):
        activity = self._activity(cost=25_000)

        self.assertEqual(missing_cost_lines_count(), 1)

        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=25_000,
            amount=25_000,
        )
        self.assertEqual(missing_cost_lines_count(), 0)
