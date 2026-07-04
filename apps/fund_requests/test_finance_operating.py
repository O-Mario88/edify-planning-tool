from django.test import TestCase
from datetime import date
from apps.activities.models import Activity, ActivityScheduleCostLine, ActivityType
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.fund_requests.models import (
    AccountabilityRecord,
    NetSuiteExpenseRecord,
    VarianceReview
)
from apps.fund_requests.finance_services import (
    FinanceBlockedReasonService,
    AdvanceDisbursementService,
    PartnerPaymentService,
    ReimbursementService,
    AccountabilityService,
    NetSuiteExpenseService
)

class FinanceOperatingSystemTest(TestCase):
    def setUp(self):
        # Create Geography Hierarchy
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        
        # Create School
        self.school = School.objects.create(
            name="St. Jude Academy",
            region=self.region,
            district=self.district
        )
        
        # Create staff activity
        self.staff_activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            responsible_staff_id="cceo_user",
            planned_date=date(2026, 7, 15)
        )
        
        # Create activity budget line
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.staff_activity,
            cost_setting_key="transport_allowance",
            label="Transport to St. Jude",
            unit_cost=150000,
            quantity=3,
            amount=450000
        )
        
        # Create partner activity
        self.partner_activity = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            activity_type=ActivityType.PARTNER_ACTIVITY,
            status="scheduled",
            payment_status="pending",
            assigned_partner_id="partner_abc",
            planned_date=date(2026, 7, 20)
        )
        
        # Create partner activity budget line
        ActivityScheduleCostLine.objects.create(
            activity=self.partner_activity,
            cost_setting_key="partner_allowance",
            label="Partner training fees",
            unit_cost=600000,
            quantity=1,
            amount=600000
        )

    def test_finance_blocked_rules(self):
        # Fresh staff activity should be blocked for final clearance due to:
        # IA Verification Missing, Evidence Missing, Activity SF ID Missing
        reasons = FinanceBlockedReasonService.get_blocked_reasons(self.staff_activity)
        self.assertIn("IA Verification Missing", reasons)
        self.assertIn("Evidence Missing", reasons)
        self.assertIn("Activity SF ID Missing", reasons)
        self.assertTrue(FinanceBlockedReasonService.is_blocked(self.staff_activity))

    def test_advance_disbursement_flow(self):
        # Accountant disburses approved advance BEFORE execution and IA
        disb = AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-123",
            user_id="accountant_jane"
        )
        
        # Verify Disbursement record
        self.assertEqual(disb.amount_disbursed, 450000)
        self.assertEqual(disb.payment_method, "Mobile Money")
        
        # Verify Activity payment status
        self.staff_activity.refresh_from_db()
        self.assertEqual(self.staff_activity.payment_status, "disbursed")
        
        # Verify shell accountability record was generated
        acc = AccountabilityRecord.objects.get(activity=self.staff_activity)
        self.assertEqual(acc.status, "pending")
        self.assertEqual(acc.amount_disbursed, 450000)

    def test_partner_payment_blocked_and_success(self):
        # Partner payment should fail if blockers exist (e.g. IA missing)
        with self.assertRaises(ValueError):
            PartnerPaymentService.pay_partner(
                activity=self.partner_activity,
                partner_name="Partner ABC",
                amount=600000,
                method="Bank Transfer",
                reference="TXN-PART-123",
                user_id="accountant_jane"
            )
            
        # Simulate meeting qualifications: IA verified, evidence present, Salesforce ID set
        self.partner_activity.status = "ia_verified"
        self.partner_activity.salesforce_activity_id = "SF-ACT-999"
        self.partner_activity.save()
        
        # Create evidence mock
        from apps.evidence.models import EvidenceRecord
        EvidenceRecord.objects.create(
            activity=self.partner_activity,
            kind="visit_form",
            uri="https://s3.aws/report.pdf",
            original_name="report.pdf",
            file_size=1024,
            uploaded_by="partner_abc"
        )
        
        # Now pay partner should pass
        pay = PartnerPaymentService.pay_partner(
            activity=self.partner_activity,
            partner_name="Partner ABC",
            amount=600000,
            method="Bank Transfer",
            reference="TXN-PART-123",
            user_id="accountant_jane"
        )
        self.assertEqual(pay.amount_paid, 600000)
        
        # Verify status updates to closed
        self.partner_activity.refresh_from_db()
        self.assertEqual(self.partner_activity.payment_status, "paid")
        self.assertEqual(self.partner_activity.status, "closed")

    def test_reimbursement_claim_calculations(self):
        # Staff overspent or self-funded
        # Create advance disbursement first
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-123",
            user_id="accountant_jane"
        )
        
        # Staff actual spend is 600,000 (disbursed is 450,000) -> Claim is 150,000
        claim = ReimbursementService.claim_reimbursement(
            activity=self.staff_activity,
            actual_spend=600000,
            staff_id="cceo_user"
        )
        self.assertEqual(claim.reimbursement_amount, 150000)
        self.assertEqual(claim.status, "pending")

    def test_accountability_and_netsuite_entry(self):
        # 1. Disburse advance
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-123",
            user_id="accountant_jane"
        )
        
        # 2. Staff submits accountability with variance (spent 500,000 instead of 450,000)
        acc = AccountabilityService.submit_accountability(
            activity=self.staff_activity,
            actual_spend=500000,
            variance_reason="Extra transport fees",
            staff_id="cceo_user"
        )
        self.assertEqual(acc.status, "variance_review")
        self.assertEqual(acc.variance, 500000 - 450000)
        
        # Check that variance review record was created
        vr = VarianceReview.objects.get(activity=self.staff_activity)
        self.assertEqual(vr.status, "pending")
        self.assertEqual(vr.variance, 500000 - 450000)

        # 3. Enter NetSuite Expense ID
        NetSuiteExpenseService.enter_netsuite_id(
            activity=self.staff_activity,
            netsuite_id="NS-EXP-777",
            amount=500000,
            expense_date=date(2026, 7, 2),
            user_id="accountant_jane"
        )
        
        # Accountability record should resolve to cleared
        acc.refresh_from_db()
        self.assertEqual(acc.status, "cleared")
        self.assertEqual(acc.netsuite_expense_id, "NS-EXP-777")
        
        # Check NetSuite record was saved
        ns = NetSuiteExpenseRecord.objects.get(activity=self.staff_activity)
        self.assertEqual(ns.netsuite_expense_id, "NS-EXP-777")
