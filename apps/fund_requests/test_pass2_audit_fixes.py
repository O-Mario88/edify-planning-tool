"""Regression tests for three finance-integrity gaps found in the Pass 2
functionality audit of the Weekly Fund Request / PL Approval handoff:

1. pl_approval_service.approve() had no status guard — re-approving an
   already-disbursed/held monthly plan flipped it back to
   "sent_to_accountant", reopening it for a second payout.
2. weekly_service.disburse() had no bounds check on the entered amount and
   hard-set every linked AdvanceRequest.disbursed_amount to the FULL line
   cost regardless of what fraction was actually disbursed.
3. The Accountant's "Return" action (finance_return_action) bypassed the
   service layer: no reason enforcement, no status guard (could un-disburse
   an already-disbursed/accounted advance), and no audit log.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import (
    AdvanceRequest,
    AdvanceRequestStatus,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class PlApprovalIdempotencyTest(TestCase):
    """pl_approval_service.approve() must not reopen an already-processed plan."""

    def setUp(self):
        self.region = Region.objects.create(name="Idem Region")
        self.district = District.objects.create(
            name="Idem District", region=self.region
        )
        self.school = School.objects.create(
            school_id="IDEM-SCH",
            name="Idem School",
            region=self.region,
            district=self.district,
        )
        self.pl = User.objects.create_user(
            email="pl-idem@test.org",
            name="Idem PL",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        self.pl_sp = StaffProfile.objects.create(user=self.pl, title="Program Lead")
        self.cceo = User.objects.create_user(
            email="cceo-idem@test.org",
            name="Idem CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            fy="2026",
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 8, 9, 0)),
        )
        ActivityScheduleCostLine.objects.create(
            activity=Activity.objects.get(responsible_staff_id=self.cceo.id),
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            month=4,
            fiscal_year="2026",
            responsible_user=self.cceo.id,
            catalogue_id="cat-v1",
            catalogue_version=1,
        )

    def test_reapproving_a_disbursed_plan_is_blocked(self):
        from apps.fund_requests.pl_approval_service import approve

        principal = self.pl
        fr = approve(principal, self.cceo.id, "2026", 4)
        self.assertEqual(fr.status, "sent_to_accountant")

        # The accountant disburses it — out of band from PL approval.
        fr.status = "disbursed"
        fr.save(update_fields=["status"])

        with self.assertRaises(BadRequest):
            approve(principal, self.cceo.id, "2026", 4)

        fr.refresh_from_db()
        self.assertEqual(fr.status, "disbursed")


class WeeklyDisburseBoundsAndScalingTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="WD Region")
        self.district = District.objects.create(name="WD District", region=self.region)
        self.school = School.objects.create(
            school_id="WD-SCH",
            name="WD School",
            region=self.region,
            district=self.district,
        )
        self.cceo = User.objects.create_user(
            email="cceo-wd@test.org",
            name="WD CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.accountant = User.objects.create_user(
            email="acct-wd@test.org",
            name="WD Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        act = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            fy="2026",
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 8, 9, 0)),
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            month=7,
            fiscal_year="2026",
            responsible_user=self.cceo.id,
        )
        self.adv = AdvanceRequest.objects.create(
            activity=act,
            budget_line=self.line,
            responsible_user_id=self.cceo.id,
            fy="2026",
            quarter="Q3",
            amount=100_000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
            advance_type="advance",
        )
        week_start = _monday(date(2026, 7, 6))
        self.wfr = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=self.cceo.id,
            total_amount=100_000,
            status="confirmed_for_advance",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=self.wfr,
            activity_budget_line=self.line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=100_000,
            total_cost=100_000,
        )

    class _Principal:
        def __init__(self, u):
            self.user_id = u.id
            self.active_role = u.active_role

    def test_disburse_rejects_amount_over_total(self):
        from apps.fund_requests.weekly_service import disburse

        with self.assertRaises(BadRequest):
            disburse(
                self.wfr.id, {"amount": "999999"}, self._Principal(self.accountant)
            )
        self.wfr.refresh_from_db()
        self.assertEqual(self.wfr.status, "confirmed_for_advance")

    def test_disburse_rejects_zero_or_negative_amount(self):
        from apps.fund_requests.weekly_service import disburse

        with self.assertRaises(BadRequest):
            disburse(self.wfr.id, {"amount": "0"}, self._Principal(self.accountant))

    def test_partial_disburse_scales_advance_proportionally(self):
        from apps.fund_requests.weekly_service import disburse

        disburse(self.wfr.id, {"amount": "40000"}, self._Principal(self.accountant))
        self.adv.refresh_from_db()
        # 40,000 / 100,000 = 40% of the 100,000 line -> 40,000, not the full
        # 100,000 the old code hard-set regardless of the entered amount.
        self.assertEqual(self.adv.disbursed_amount, 40_000)
        self.assertEqual(self.adv.status, "disbursed")

    def test_full_disburse_still_works(self):
        from apps.fund_requests.weekly_service import disburse

        disburse(self.wfr.id, {"amount": "100000"}, self._Principal(self.accountant))
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.disbursed_amount, 100_000)


class AccountantReturnGuardTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="AR Region")
        self.district = District.objects.create(name="AR District", region=self.region)
        self.school = School.objects.create(
            school_id="AR-SCH",
            name="AR School",
            region=self.region,
            district=self.district,
        )
        self.cceo = User.objects.create_user(
            email="cceo-ar@test.org",
            name="AR CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.accountant = User.objects.create_user(
            email="acct-ar@test.org",
            name="AR Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        act = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            fy="2026",
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 8, 9, 0)),
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            month=7,
            fiscal_year="2026",
            responsible_user=self.cceo.id,
        )
        self.adv = AdvanceRequest.objects.create(
            activity=act,
            budget_line=self.line,
            responsible_user_id=self.cceo.id,
            fy="2026",
            quarter="Q3",
            amount=100_000,
            status=AdvanceRequestStatus.DISBURSED,
            advance_type="advance",
        )
        week_start = _monday(date(2026, 7, 6))
        self.wfr = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=self.cceo.id,
            total_amount=100_000,
            status="disbursed",
            disbursed_amount=100_000,
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=self.wfr,
            activity_budget_line=self.line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=100_000,
            total_cost=100_000,
        )
        self.client = Client()
        self.client.force_login(self.accountant)

    def test_cannot_return_an_already_disbursed_request(self):
        resp = self.client.post(
            "/finance/actions/return_correction",
            {"request_id": self.wfr.id, "reason": "test"},
        )
        self.assertEqual(resp.status_code, 400)
        self.wfr.refresh_from_db()
        self.assertEqual(self.wfr.status, "disbursed")
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)

    def test_empty_reason_is_rejected(self):
        self.wfr.status = "confirmed_for_advance"
        self.wfr.save(update_fields=["status"])
        resp = self.client.post(
            "/finance/actions/return_correction",
            {"request_id": self.wfr.id, "reason": ""},
        )
        self.assertEqual(resp.status_code, 400)
        self.wfr.refresh_from_db()
        self.assertEqual(self.wfr.status, "confirmed_for_advance")

    def test_valid_return_on_confirmed_request_creates_audit_log(self):
        from apps.audit.models import AuditLog

        self.wfr.status = "confirmed_for_advance"
        self.wfr.save(update_fields=["status"])
        self.adv.status = AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        self.adv.save(update_fields=["status"])

        resp = self.client.post(
            "/finance/actions/return_correction",
            {"request_id": self.wfr.id, "reason": "Missing SF ID"},
        )
        self.assertEqual(resp.status_code, 200)
        self.wfr.refresh_from_db()
        self.assertEqual(self.wfr.status, "returned_by_accountant")
        self.assertTrue(
            AuditLog.objects.filter(
                action="weekly_fund_request.return_by_accountant",
                subject_id=str(self.wfr.id),
            ).exists()
        )
