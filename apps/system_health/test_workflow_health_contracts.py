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


class WorkPricedLaterIsNotReportedTest(TestCase):
    """Health checks count what someone can correct, not work that the
    workflow prices, pools or clears at a later step by design (2026-09-13
    ecosystem audit)."""

    def test_a_visit_request_is_priced_when_its_owner_approves_it(self):
        Activity.objects.create(
            activity_type="school_visit",
            status="awaiting_owner_approval",
            fy="FY26",
            quarter="Q1",
            est_cost_cents=25_000,
        )
        self.assertEqual(missing_cost_lines_count(), 0)

    def test_an_unpriced_visit_request_is_neither_executed_nor_cleared(self):
        from apps.activities.closure_services import ClosureEligibilityService
        from apps.system_health.services import _workflow_issues

        request = Activity.objects.create(
            activity_type="school_visit", status="awaiting_owner_approval"
        )
        checklist, blockers = ClosureEligibilityService.evaluate(request)
        self.assertFalse(checklist.activity_executed)
        self.assertIn("Activity not executed", [b.blocking_reason for b in blockers])
        self.assertEqual(_workflow_issues()["accountsClearanceBeforeIa"], 0)

    def test_only_a_dated_live_plan_can_be_missing_its_day_batch(self):
        from apps.system_health.services import _workflow_issues

        school = _school()
        for status, planned_date in (
            ("planned", None),
            ("awaiting_owner_approval", "2026-08-20"),
            ("completed", "2026-03-02"),
        ):
            Activity.objects.create(
                activity_type="school_visit",
                delivery_type="staff",
                school=school,
                status=status,
                planned_date=planned_date,
            )
        self.assertEqual(_workflow_issues()["scheduledVisitsMissingBatch"], 0)
        Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            school=school,
            status="scheduled",
            planned_date="2026-08-21",
        )
        self.assertEqual(_workflow_issues()["scheduledVisitsMissingBatch"], 1)

    def test_a_meetings_share_of_the_field_day_is_not_a_wrong_meeting_cost(self):
        from apps.system_health.services import _workflow_issues

        meeting = Activity.objects.create(
            activity_type="cluster_meeting", status="scheduled"
        )
        for key in ("primary_transport_per_day", "lunch_per_day"):
            ActivityScheduleCostLine.objects.create(
                activity=meeting,
                cost_setting_key=key,
                label=key,
                unit_cost=5_000,
                amount=5_000,
            )
        issues = _workflow_issues()
        self.assertFalse(
            any("do not use Participant snacks" in b for b in issues["blockers"]),
            issues["blockers"],
        )
        ActivityScheduleCostLine.objects.create(
            activity=meeting,
            cost_setting_key="group_training_venue_cost",
            label="Venue",
            unit_cost=5_000,
            amount=5_000,
        )
        self.assertIn(
            "1 cluster meeting cost line(s) do not use Participant snacks.",
            _workflow_issues()["blockers"],
        )


def _school():
    from apps.geography.models import District, Region
    from apps.schools.models import School

    region = Region.objects.create(name="Health Contract Region")
    district = District.objects.create(name="Health Contract District", region=region)
    return School.objects.create(
        school_id="SCH-HEALTH-CONTRACT",
        name="Contract Primary",
        region=region,
        district=district,
    )
