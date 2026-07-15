"""Regression tests for the UGX-vs-cents money-unit bug found in the
2026-07-15 system audit: several read paths divided Activity.est_cost_cents
(and other plain-UGX fields whose model comments wrongly said "Cents") by
100, silently understating real money amounts by 100x. None of these paths
had any prior test coverage, which is how the bug went undetected.

Ground truth: apps.budget.models.CostSetting documents "1 unit = 1 UGX",
apps.budget.costing_service is the sole writer of est_cost_cents and writes
the raw integer UGX amount straight through -- there is no cents scaling
anywhere in this codebase outside apps.professional_development (which is a
separate, genuinely cents-based subsystem).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine, ActivityType
from apps.core.rbac import EdifyRole
from apps.fund_requests.finance_services import AdvanceDisbursementService
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School

User = get_user_model()


class BatchPaymentsCsvMoneyUnitTest(TestCase):
    """The Batch Payments CSV export (used to actually pay people) must
    report the real UGX amount, not est_cost_cents/100."""

    def setUp(self):
        self.accountant = User.objects.create_user(
            email="accountant-money-unit@test.org",
            name="Money Unit Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="password",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.accountant, title="Accountant")

        region = Region.objects.create(name="Money Unit Region")
        district = District.objects.create(name="Money Unit District", region=region)
        self.school = School.objects.create(
            school_id="MU-SCH",
            name="Money Unit School",
            region=region,
            district=district,
        )

        self.staff_activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            fy="2026",
            responsible_staff_id="mu-staff-1",
            est_cost_cents=450000,  # plain UGX 450,000 despite the field name
        )
        cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.staff_activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=150000,
            quantity=3,
            amount=450000,
        )
        AdvanceRequest.objects.create(
            activity=self.staff_activity,
            budget_line=cost_line,
            fy="2026",
            quarter="Q4",
            amount=450000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
            responsible_user_id="mu-staff-1",
        )

        self.partner_activity = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="ia_verified",
            payment_status="ia_confirmed",
            assigned_partner_id="mu-partner-1",
            est_cost_cents=120000,
        )

        self.client.force_login(self.accountant)

    def test_advances_csv_reports_full_ugx_amount(self):
        resp = self.client.get("/accounts/batch-payments/?export=advances")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(str(self.staff_activity.id), body)
        self.assertIn("450000", body)
        self.assertNotIn("4500,", body)  # the old, wrong /100 value

    def test_partners_csv_reports_full_ugx_amount(self):
        resp = self.client.get("/accounts/batch-payments/?export=partners")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(str(self.partner_activity.id), body)
        self.assertIn("120000", body)
        self.assertNotIn("1200,", body)  # the old, wrong /100 value

    def test_batch_payments_page_amount_ugx_matches_est_cost_cents(self):
        resp = self.client.get("/accounts/batch-payments/")
        self.assertEqual(resp.status_code, 200)
        advances = list(resp.context["advances"])
        match = next(a for a in advances if a.id == self.staff_activity.id)
        self.assertEqual(match.amount_ugx, 450000)


class DisbursementNotificationMoneyUnitTest(TestCase):
    """The notification sent to field staff when their advance is
    disbursed must state the real UGX amount."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            email="notif-staff@test.org",
            name="Notif Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        region = Region.objects.create(name="Notif Region")
        district = District.objects.create(name="Notif District", region=region)
        school = School.objects.create(
            school_id="NOTIF-SCH", name="Notif School", region=region, district=district
        )
        self.activity = Activity.objects.create(
            school=school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            responsible_staff_id=self.staff_user.id,
        )
        cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=150000,
            quantity=3,
            amount=450000,
        )
        AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=cost_line,
            fy="2026",
            quarter="Q4",
            amount=450000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
            responsible_user_id=self.staff_user.id,
        )

    def test_disbursement_notification_states_full_amount(self):
        AdvanceDisbursementService.disburse_advance(
            activity=self.activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-NOTIF-1",
            user_id="notif-accountant",
        )
        note = Notification.objects.filter(
            recipient_id=self.staff_user.id, category="finance"
        ).latest("created_at")
        self.assertIn("450000 UGX", note.body)
        self.assertNotIn("4500 UGX", note.body)  # the old, wrong /100 value
