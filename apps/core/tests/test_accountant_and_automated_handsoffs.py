from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta

from apps.accounts.models import StaffProfile
from apps.fund_requests.models import (
    WeeklyFundRequest,
    WeeklyFundRequestLine,
    AdvanceRequest,
    AdvanceRequestStatus,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.fund_requests.weekly_service import disburse as disburse_weekly
from apps.fund_requests.advance_service import (
    submit_accountability,
    approve_accountability,
    submit_reimbursement,
    reimburse as process_reimburse,
)
from apps.core.rbac import EdifyRole

User = get_user_model()


class AccountantAndAutomatedHandoffsTest(TestCase):
    def setUp(self):
        # Create users
        self.accountant = User.objects.create_user(
            email="accountant@test.org",
            name="Edify Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="password",
            is_active=True,
        )
        self.cceo_user = User.objects.create_user(
            email="cceo@test.org",
            name="Edify CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo_user, title="CCEO")

        # Create activity and budget lines
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            fy="2026",
            quarter="Q1",
            responsible_staff_id=self.cceo_staff.id,
            status="scheduled",
            scheduled_date=timezone.now(),
            delivery_type="staff",
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user=self.cceo_user.user_id,
            line_item_type="transport",
            label="Transport",
            quantity=1,
            unit_cost=50000,
            amount=50000,
            currency="UGX",
        )

        # Generate weekly request
        self.wfr = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=date.today() - timedelta(days=date.today().weekday()),
            week_end_date=date.today()
            - timedelta(days=date.today().weekday())
            + timedelta(days=6),
            responsible_user=self.cceo_user.user_id,
            total_amount=50000,
            status="confirmed_for_advance",
            confirmed_at=timezone.now(),
        )
        self.wfr_line = WeeklyFundRequestLine.objects.create(
            weekly_fund_request=self.wfr,
            activity_budget_line=self.cost_line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=50000,
            total_cost=50000,
        )

        # Companion AdvanceRequest
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id=self.cceo_user.user_id,
            fy="2026",
            quarter="Q1",
            amount=50000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
            advance_type="advance",
        )

    def test_disburse_weekly_fund_request_sets_advances_to_disbursed(self):
        payload = {"method": "mobile_money", "reference": "TXN-MM-8899"}
        # Disburse
        disburse_weekly(self.wfr.id, payload, self.accountant)

        self.wfr.refresh_from_db()
        self.adv.refresh_from_db()

        self.assertEqual(self.wfr.status, "disbursed")
        self.assertEqual(self.wfr.disbursed_amount, 50000)
        self.assertEqual(self.wfr.disburse_method, "mobile_money")
        self.assertEqual(self.wfr.disburse_reference, "TXN-MM-8899")

        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)
        self.assertEqual(self.adv.disbursed_amount, 50000)
        self.assertEqual(self.adv.disburse_method, "mobile_money")
        self.assertEqual(self.adv.disburse_reference, "TXN-MM-8899")

    def test_submit_accountability_and_confirm(self):
        # First disburse
        self.adv.status = AdvanceRequestStatus.DISBURSED
        self.adv.save()

        # Submit accountability
        submit_accountability(
            self.adv.id,
            {"amountSpent": 45000, "amountReturned": 5000, "netsuiteId": "EXP-9900"},
            self.cceo_user,
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)
        self.assertEqual(self.adv.accounted_amount, 45000)
        self.assertEqual(self.adv.returned_amount, 5000)
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-9900")

        # Approve/Confirm — final clearance requires IA verification first.
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["ia_verification_status"])
        approve_accountability(self.adv.id, self.accountant)
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)

    def test_submit_reimbursement_and_disburse(self):
        # Change advance request to self-funded
        self.adv.status = AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT
        self.adv.advance_type = "self_funded"
        self.adv.save()

        # Submit claim
        submit_reimbursement(
            self.adv.id,
            {"amountSpent": 50000, "netsuiteId": "EXP-9901"},
            self.cceo_user,
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED)
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-9901")

        # Reimburse/Disburse
        process_reimburse(
            self.adv.id,
            {"method": "bank_transfer", "reference": "BANK-REF-99"},
            self.accountant,
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.REIMBURSED)
        self.assertEqual(self.adv.disburse_method, "bank_transfer")
        self.assertEqual(self.adv.disburse_reference, "BANK-REF-99")
