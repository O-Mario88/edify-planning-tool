"""The Work Plan is the schedule, aggregated (§18, §25.9).

The defining property under test: there is no way to put a row here by hand.
Every figure follows the scheduled activity it came from — so rescheduling
moves it, cancelling removes it, and a cost amendment updates it, without
anyone maintaining a second copy of the plan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.monthly_work_plan.schedule_plan import monthly_work_plan

FY = "2026"


def _staff(email="wp@test.local"):
    user = User.objects.create_user(
        email=email,
        password="pw",
        name="Work Plan Staff",
        roles=["CCEO"],
        active_role="CCEO",
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        user=user, title="CCEO", country="Uganda", onboarding_state="active"
    )


class MonthlyWorkPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, cls.staff = _staff()

    def _activity(self, *, when, activity_type="school_visit", status="scheduled"):
        return Activity.objects.create(
            activity_type=activity_type,
            status=status,
            planned_date=when,
            fy=FY,
            responsible_staff_id=self.staff.id,
        )

    def _plan(self, month=None):
        return monthly_work_plan(staff_ids=[self.staff.id], fy=FY, month=month)

    def _section(self, plan, month):
        return next(s for s in plan["sections"] if s["month"] == month)

    def test_a_scheduled_school_activity_appears_in_its_month(self):
        self._activity(when=date(2025, 11, 12))
        section = self._section(self._plan(), 11)
        self.assertFalse(section["isEmpty"])
        self.assertEqual(section["rows"][0]["label"], "School Visit")
        self.assertEqual(section["rows"][0]["target"], 1)

    def test_a_scheduled_non_school_activity_appears_too(self):
        self._activity(when=date(2025, 11, 12), activity_type="cluster_meeting")
        row = self._section(self._plan(), 11)["rows"][0]
        self.assertEqual(row["label"], "Cluster Meeting")
        self.assertEqual(row["unit"], "sessions")

    def test_activities_of_one_type_aggregate_into_a_single_row(self):
        for day in (3, 10, 17):
            self._activity(when=date(2025, 11, day))
        section = self._section(self._plan(), 11)
        self.assertEqual(len(section["rows"]), 1)
        self.assertEqual(section["rows"][0]["target"], 3)
        self.assertEqual(section["rows"][0]["count"], 3)

    def test_a_draft_activity_is_not_a_plan(self):
        self._activity(when=date(2025, 11, 12), status="draft")
        self.assertTrue(self._section(self._plan(), 11)["isEmpty"])

    def test_a_cancelled_activity_leaves_the_plan(self):
        activity = self._activity(when=date(2025, 11, 12))
        self.assertFalse(self._section(self._plan(), 11)["isEmpty"])
        activity.status = "cancelled"
        activity.save(update_fields=["status"])
        self.assertTrue(self._section(self._plan(), 11)["isEmpty"])

    def test_rescheduling_moves_it_between_months(self):
        activity = self._activity(when=date(2025, 11, 12))
        self.assertFalse(self._section(self._plan(), 11)["isEmpty"])
        activity.planned_date = date(2025, 12, 3)
        activity.save(update_fields=["planned_date"])
        plan = self._plan()
        self.assertTrue(self._section(plan, 11)["isEmpty"])
        self.assertFalse(self._section(plan, 12)["isEmpty"])

    def test_reassigning_removes_it_from_this_persons_plan(self):
        other_user, other_staff = _staff("other@wp.test")
        activity = self._activity(when=date(2025, 11, 12))
        activity.responsible_staff_id = other_staff.id
        activity.save(update_fields=["responsible_staff_id"])
        self.assertTrue(self._section(self._plan(), 11)["isEmpty"])

    def test_the_months_run_in_financial_year_order(self):
        plan = monthly_work_plan(staff_ids=[self.staff.id], fy=FY)
        self.assertEqual(
            [s["month"] for s in plan["sections"]],
            [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9],
        )
        self.assertEqual(plan["sections"][0]["label"], "October 2025")
        self.assertEqual(plan["sections"][-1]["label"], "September 2026")

    def test_incompatible_units_are_reported_separately_never_added(self):
        """ "24 visits · 3 sessions" is true; "27" is not."""
        self._activity(when=date(2025, 11, 4))
        self._activity(when=date(2025, 11, 5), activity_type="cluster_training")
        units = {
            u["unit"]: u["count"] for u in self._section(self._plan(), 11)["unitTotals"]
        }
        self.assertEqual(units, {"visits": 1, "sessions": 1})

    def test_cost_comes_from_the_authoritative_cost_line_not_a_rate_here(self):
        from apps.activities.models import ActivityScheduleCostLine

        activity = self._activity(when=date(2025, 11, 12))
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            label="Transport",
            unit_cost=Decimal("43000"),
            quantity=2,
            amount=Decimal("86000"),
        )
        row = self._section(self._plan(), 11)["rows"][0]
        self.assertEqual(row["cost"], Decimal("86000"))
        self.assertEqual(self._section(self._plan(), 11)["totalCost"], Decimal("86000"))

    def test_a_month_filter_returns_only_that_month(self):
        self._activity(when=date(2025, 11, 12))
        self._activity(when=date(2025, 12, 12))
        plan = self._plan(month=11)
        self.assertEqual([s["month"] for s in plan["sections"]], [11])
        self.assertEqual(plan["scheduledCount"], 1)

    def test_there_is_no_write_path_into_the_work_plan(self):
        """§18.2 — no manual row creation endpoint exists. The module exposes
        one function and it only reads."""
        from apps.monthly_work_plan import schedule_plan

        writers = [
            name
            for name in dir(schedule_plan)
            if name.startswith(("create", "save", "add", "update", "delete"))
        ]
        self.assertEqual(writers, [])
