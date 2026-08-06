"""Once an activity's cost line has a disbursed/accounted/reimbursed
AdvanceRequest against it, that cost snapshot must be immutable.

Regression test: apps.budget.costing_service.apply_to_activity() used to
unconditionally `ActivityScheduleCostLine.objects.filter(activity=activity)
.delete()` on every re-price (reschedule, partner re-schedule, daily-batch
recalculation). AdvanceRequest.budget_line and WeeklyFundRequestLine.
activity_budget_line are both on_delete=CASCADE onto ActivityScheduleCostLine,
so that delete silently erased the disbursed AdvanceRequest — before
advance_service.sync_for_activity() ever got a chance to apply its own
"never touch a disbursed advance" rule, because by then the row was already
gone. A plain reschedule of an activity that already had money disbursed
against it would permanently destroy that disbursement record.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.services import reschedule
from apps.budget.models import CostSetting
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class CostSnapshotLockTest(TestCase):
    def setUp(self):
        self.cceo = User.objects.create_user(
            email="cceo-lock@test.org",
            name="Lock CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        region = Region.objects.create(name="Lock Region")
        district = District.objects.create(
            name="Lock District", region=region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="LOCK-SCH",
            name="Lock School",
            region=region,
            district=district,
        )
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.school.id)

        for key, cost in [
            ("staff_visit_transport_primary", 15000),
            ("lunch", 8000),
            ("primary_transport_per_day", 15000),
            ("primary_lunch_per_day", 8000),
        ]:
            CostSetting.objects.update_or_create(
                key=key, defaults={"label": key, "unit_cost": cost, "version": 1}
            )

        self.activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            responsible_staff_id=self.cceo.id,
            status="scheduled",
            scheduled_date=timezone.now(),
            delivery_type="staff",
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=50_000,
            amount=50_000,
            currency="UGX",
        )
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.line,
            responsible_user_id=self.cceo.id,
            fy="2026",
            quarter="Q1",
            amount=50_000,
            status=AdvanceRequestStatus.DISBURSED,
            advance_type="advance",
        )

    def test_reschedule_blocked_when_advance_already_disbursed(self):
        with self.assertRaises(BadRequest):
            reschedule(
                self.activity.id,
                {"scheduledDate": date(2026, 8, 1).isoformat()},
                principal=self.cceo,
            )

    def test_disbursed_advance_and_cost_line_survive_the_blocked_attempt(self):
        try:
            reschedule(
                self.activity.id,
                {"scheduledDate": date(2026, 8, 1).isoformat()},
                principal=self.cceo,
            )
        except BadRequest:
            pass
        # The disbursed financial record must still exist, unchanged — not
        # silently cascade-deleted by a cost-line rebuild.
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(id=self.line.id).exists()
        )

    def test_reschedule_still_works_before_any_disbursement(self):
        """The lock must only engage once money has actually moved — a
        perfectly normal reschedule on a pending-confirmation advance must
        keep working exactly as before."""
        self.adv.status = AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION
        self.adv.save(update_fields=["status"])

        original_date = self.activity.scheduled_date
        reschedule(
            self.activity.id,
            {
                "scheduledDate": date(2026, 8, 1).isoformat(),
                "reason": "Below CD daily target — single-school reschedule for test.",
            },
            principal=self.cceo,
        )
        self.activity.refresh_from_db()
        self.assertNotEqual(self.activity.scheduled_date, original_date)
        self.assertEqual(self.activity.reschedule_count, 1)
