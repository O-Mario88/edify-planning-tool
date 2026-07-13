"""Tests for apps.budget.costing_service — the central activity-cost writer.

apply_to_activity() clears and rebuilds an activity's ActivityScheduleCostLine
rows in one sequence (delete existing lines -> bulk_create new ones -> save
the activity's cost fields). That sequence must be atomic: a crash partway
through must never leave the activity with a stale delete and no replacement
lines (or with new lines but stale est_cost_cents).
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget import costing_service
from apps.core.enums import ActivityType
from apps.geography.models import District, Region
from apps.schools.models import School

FY = "2026"


class ApplyToActivityAtomicityTest(TestCase):
    """apply_to_activity()'s delete + bulk_create + save must be all-or-nothing."""

    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-COST-1",
            name="Cost Test School",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT,
            school=self.school,
            delivery_type="staff",
            status="scheduled",
            responsible_staff_id="staff-1",
            fy=FY,
            scheduled_date=timezone.now(),
        )
        # Simulate a budget line already persisted by an earlier, successful
        # apply_to_activity() call — this is the state a mid-sequence crash
        # must not be allowed to destroy.
        self.pre_existing_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            fiscal_year=FY,
        )

    def _input(self):
        return {
            "activityType": self.activity.activity_type,
            "deliveryType": "staff",
            "districtType": "primary",
            "fy": FY,
        }

    def test_crash_during_bulk_create_leaves_no_partial_state(self):
        """A failure between the delete and the bulk_create must roll back the
        delete too — never leaving the activity with zero budget lines."""
        with patch(
            "apps.budget.costing_service.ActivityScheduleCostLine.objects.bulk_create",
            side_effect=RuntimeError("simulated crash mid-write"),
        ):
            with self.assertRaises(RuntimeError):
                costing_service.apply_to_activity(self.activity, self._input())

        # The pre-existing line must still be there: the delete was rolled
        # back together with the aborted bulk_create.
        lines = ActivityScheduleCostLine.objects.filter(activity=self.activity)
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().id, self.pre_existing_line.id)

    def test_crash_during_activity_save_rolls_back_new_lines_too(self):
        """A failure on activity.save() (after the new lines are already
        bulk_created) must roll back those new lines as well — never leaving
        freshly written lines orphaned against a stale est_cost_cents."""
        with patch(
            "apps.budget.costing_service.Activity.save",
            side_effect=RuntimeError("simulated crash on save"),
        ):
            with self.assertRaises(RuntimeError):
                costing_service.apply_to_activity(self.activity, self._input())

        lines = ActivityScheduleCostLine.objects.filter(activity=self.activity)
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().id, self.pre_existing_line.id)

    def test_successful_apply_still_replaces_lines_normally(self):
        """Sanity check: the happy path is unaffected by the atomic() wrapper —
        it still clears and rebuilds the budget lines as before."""
        costing_service.apply_to_activity(self.activity, self._input())
        lines = ActivityScheduleCostLine.objects.filter(activity=self.activity)
        self.assertFalse(lines.filter(id=self.pre_existing_line.id).exists())
        self.assertGreater(lines.count(), 0)
