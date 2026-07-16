"""§9/§18-mandated closure & accountant-clearance tests added by the
2026-07-15 full-platform audit. Covers the defects the verification pass
found: closure must require genuine accountant final-clearance (not a mere
disbursed/accountability_pending state), the NetSuite ID must be format-
validated, a cleared record is immutable, and clearance never dead-ends on
an unresolved variance.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ActivityType,
)
from apps.activities.closure_services import ClosureEligibilityService
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_services import (
    AdvanceDisbursementService,
    AccountabilityService,
    NetSuiteExpenseService,
    is_valid_netsuite_id,
)
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class NetSuiteFormatValidationTest(TestCase):
    def test_valid_and_invalid_ids(self):
        self.assertTrue(is_valid_netsuite_id("EXP-77"))
        self.assertTrue(is_valid_netsuite_id("NS12345"))
        self.assertFalse(is_valid_netsuite_id(""))
        self.assertFalse(is_valid_netsuite_id("   "))
        self.assertFalse(is_valid_netsuite_id("ab"))  # too short
        self.assertFalse(is_valid_netsuite_id("has spaces"))


class SystemAClearanceGateTest(TestCase):
    """The System A activity-level flow: disburse -> submit accountability
    -> accountant enters NetSuite ID (= clearance) -> closeable."""

    def setUp(self):
        region = Region.objects.create(name="Clr Region")
        district = District.objects.create(name="Clr District", region=region)
        self.school = School.objects.create(
            name="Clr School", region=region, district=district
        )
        self.cceo = User.objects.create(
            id="cceo-clr",
            email="cceo-clr@edify.org",
            name="Clr CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            responsible_staff_id="cceo-clr",
            salesforce_activity_id="SV-CLR-1",
            planned_date=date(2026, 7, 15),
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=150000,
            quantity=3,
            amount=450000,
        )
        AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id="cceo-clr",
            fy="2026",
            quarter="Q4",
            amount=450000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )
        EvidenceRecord.objects.create(
            activity=self.activity, kind="photo", uri="p.jpg", uploaded_by="cceo-clr"
        )
        self.activity.status = "ia_verified"
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["status", "ia_verification_status"])

    def _disburse_and_submit(self, spend=450000):
        AdvanceDisbursementService.disburse_advance(
            activity=self.activity,
            amount=450000,
            method="Cash",
            reference="TXN-CLR",
            user_id="acct",
        )
        AccountabilityService.submit_accountability(
            activity=self.activity,
            actual_spend=spend,
            variance_reason="ok" if spend == 450000 else "overspend",
            staff_id="cceo-clr",
        )

    def test_disbursed_but_uncleared_is_not_closeable(self):
        self._disburse_and_submit()
        # Money disbursed + accountability submitted, but the accountant has
        # NOT entered the NetSuite ID yet -> not accountant-cleared.
        checklist, _ = ClosureEligibilityService.evaluate(self.activity)
        self.assertFalse(checklist.accounts_cleared)
        self.assertFalse(ClosureEligibilityService.is_eligible(self.activity))

    def test_netsuite_entry_clears_and_closes(self):
        self._disburse_and_submit()
        NetSuiteExpenseService.enter_netsuite_id(
            activity=self.activity,
            netsuite_id="EXP-CLR-1",
            amount=450000,
            expense_date=date(2026, 7, 16),
            user_id="acct",
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "closed")

    def test_blank_netsuite_id_rejected(self):
        self._disburse_and_submit()
        with self.assertRaises(ValueError):
            NetSuiteExpenseService.enter_netsuite_id(
                activity=self.activity,
                netsuite_id="   ",
                amount=450000,
                expense_date=date(2026, 7, 16),
                user_id="acct",
            )

    def test_variance_resolved_at_clearance_no_dead_end(self):
        # An overspend creates a pending VarianceReview; the accountant's
        # NetSuite entry resolves it and clears — never a dead end.
        self._disburse_and_submit(spend=500000)
        NetSuiteExpenseService.enter_netsuite_id(
            activity=self.activity,
            netsuite_id="EXP-VAR-1",
            amount=500000,
            expense_date=date(2026, 7, 16),
            user_id="acct",
        )
        from apps.fund_requests.finance_models import VarianceReview

        self.assertFalse(
            VarianceReview.objects.filter(
                activity=self.activity, status="pending"
            ).exists()
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "closed")

    def test_cleared_record_is_immutable_after_close(self):
        self._disburse_and_submit()
        NetSuiteExpenseService.enter_netsuite_id(
            activity=self.activity,
            netsuite_id="EXP-IMM-1",
            amount=450000,
            expense_date=date(2026, 7, 16),
            user_id="acct",
        )
        # Re-entering after the activity is closed must be refused.
        with self.assertRaises(ValueError):
            NetSuiteExpenseService.enter_netsuite_id(
                activity=self.activity,
                netsuite_id="EXP-IMM-2",
                amount=450000,
                expense_date=date(2026, 7, 16),
                user_id="acct",
            )
