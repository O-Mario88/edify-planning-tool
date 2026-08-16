from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole

from .models import (
    ActivityPriorityLink,
    MilestoneAllocation,
    MilestoneMetricDefinition,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from .milestone_allocations import personal_milestone_targets
from .priority_linking import link_activity


class PriorityLinkingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="priority-owner@test.org",
            name="Priority Owner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="test-password",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, country="Uganda")
        cls.other = User.objects.create_user(
            email="other-priority-owner@test.org",
            name="Other Owner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="test-password",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.other, country="Uganda")
        cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year="2027",
            defaults={"title": "FY2027", "country_id": "Uganda"},
        )
        priority = StrategicPriority.objects.create(
            cycle=cycle,
            code="TRACE",
            fy="2027",
            level="country",
            country_id="Uganda",
            title="Traceable delivery",
            strategic_purpose="Test traceability",
            status="published",
        )
        metric = MilestoneMetricDefinition.objects.create(
            metric_key="trace_metric", canonical_label="Trace metric"
        )
        milestone = PriorityMilestone.objects.create(
            priority=priority,
            code="TRACE-1",
            title="Trace work",
            source_text="test",
            milestone_type="output",
            measurement_type="count",
            progress_source="trace_metric",
            metric_definition=metric,
            target_value=Decimal("10"),
            allocation_method="field_cascade",
            requires_definition=False,
            definition_status="approved",
            active=True,
        )
        cls.allocation = MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="employee",
            employee=cls.staff,
            allocated_target=Decimal("10"),
            allocation_reason="test",
            allocated_by="test",
            approved_by="test",
            effective_date=date(2026, 7, 1),
            status="approved",
        )

    def test_activity_is_explicitly_linked_to_owners_allocation(self):
        activity = Activity.objects.create(
            activity_type="school_visit",
            fy="2027",
            quarter="Q1",
            responsible_staff_id=self.staff.id,
        )
        link_activity(
            activity=activity,
            allocation_id=self.allocation.id,
            principal=self.user,
            planned_contribution="1",
        )
        link = ActivityPriorityLink.objects.get(activity=activity)
        self.assertEqual(link.allocation, self.allocation)
        self.assertEqual(link.planned_contribution, Decimal("1"))

    def test_another_employee_cannot_use_the_allocation(self):
        activity = Activity.objects.create(
            activity_type="school_visit",
            fy="2027",
            quarter="Q1",
            responsible_staff_id=self.other.staff_profile_id,
        )
        with self.assertRaises(Forbidden):
            link_activity(
                activity=activity,
                allocation_id=self.allocation.id,
                principal=self.other,
            )

    def test_annual_plan_falls_back_to_allocation_before_period_phasing(self):
        rows = personal_milestone_targets(
            staff=self.staff,
            fy="2027",
            month_of_fy=1,
        )

        self.assertEqual(rows[0]["fyPlan"], Decimal("10"))
        self.assertEqual(rows[0]["remaining"], Decimal("10"))
