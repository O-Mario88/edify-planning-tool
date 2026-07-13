from django.test import TestCase
from datetime import date
from apps.activities.models import (
    Activity,
    ActivityClosure,
    ActivityScheduleCostLine,
    ActivityType,
    CompletedActivitySnapshot,
)
from apps.schools.models import School
from apps.geography.models import Region, District
from apps.fund_requests.models import (
    AccountabilityRecord,
    AdvanceRequest,
    AdvanceRequestStatus,
    Disbursement,
    NetSuiteExpenseRecord,
    VarianceReview,
)
from apps.fund_requests.finance_services import (
    FinanceBlockedReasonService,
    AdvanceDisbursementService,
    PartnerPaymentService,
    ReimbursementService,
    AccountabilityService,
    NetSuiteExpenseService,
)


class FinanceOperatingSystemTest(TestCase):
    def setUp(self):
        # Create Geography Hierarchy
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # Create School
        self.school = School.objects.create(
            name="St. Jude Academy", region=self.region, district=self.district
        )

        # Create staff activity
        self.staff_activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            responsible_staff_id="cceo_user",
            planned_date=date(2026, 7, 15),
        )

        # Create activity budget line
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.staff_activity,
            cost_setting_key="transport_allowance",
            label="Transport to St. Jude",
            unit_cost=150000,
            quantity=3,
            amount=450000,
        )

        # The responsible user has already confirmed this advance — the
        # precondition AdvanceDisbursementService.disburse_advance() now
        # requires (mirrors advance_service.disburse()'s finance-safety gate).
        self.advance_request = AdvanceRequest.objects.create(
            activity=self.staff_activity,
            budget_line=self.cost_line,
            responsible_user_id="cceo_user",
            fy="FY26",
            quarter="Q1",
            amount=450000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )

        # Create partner activity
        self.partner_activity = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            activity_type=ActivityType.PARTNER_ACTIVITY,
            status="scheduled",
            payment_status="pending",
            assigned_partner_id="partner_abc",
            planned_date=date(2026, 7, 20),
        )

        # Create partner activity budget line
        ActivityScheduleCostLine.objects.create(
            activity=self.partner_activity,
            cost_setting_key="partner_allowance",
            label="Partner training fees",
            unit_cost=600000,
            quantity=1,
            amount=600000,
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
            user_id="accountant_jane",
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

    def test_disburse_advance_requires_responsible_confirmation(self):
        """AdvanceDisbursementService.disburse_advance() must mirror
        advance_service.disburse()'s finance-safety gate: the Accountant may
        NOT disburse before the responsible user confirms the advance."""
        activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type=ActivityType.SCHOOL_VISIT,
            status="scheduled",
            payment_status="pending",
            responsible_staff_id="cceo_gate_test",
            planned_date=date(2026, 7, 22),
        )
        cost_line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport_allowance",
            label="Transport",
            unit_cost=100000,
            quantity=1,
            amount=100000,
        )
        adv = AdvanceRequest.objects.create(
            activity=activity,
            budget_line=cost_line,
            responsible_user_id="cceo_gate_test",
            fy="FY26",
            quarter="Q1",
            amount=100000,
            status=AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION,
        )

        # Still pending responsible-user confirmation -> blocked, no writes.
        with self.assertRaises(ValueError):
            AdvanceDisbursementService.disburse_advance(
                activity=activity,
                amount=100000,
                method="Mobile Money",
                reference="TXN-GATE-1",
                user_id="accountant_jane",
            )
        self.assertFalse(Disbursement.objects.filter(activity=activity).exists())

        # Responsible user confirms -> disbursement now succeeds.
        adv.status = AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        adv.save(update_fields=["status"])

        disb = AdvanceDisbursementService.disburse_advance(
            activity=activity,
            amount=100000,
            method="Mobile Money",
            reference="TXN-GATE-1",
            user_id="accountant_jane",
        )
        self.assertEqual(disb.amount_disbursed, 100000)
        activity.refresh_from_db()
        self.assertEqual(activity.payment_status, "disbursed")

    def test_partner_payment_blocked_and_success(self):
        # Partner payment should fail if blockers exist (e.g. IA missing)
        with self.assertRaises(ValueError):
            PartnerPaymentService.pay_partner(
                activity=self.partner_activity,
                partner_name="Partner ABC",
                amount=600000,
                method="Bank Transfer",
                reference="TXN-PART-123",
                user_id="accountant_jane",
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
            uploaded_by="partner_abc",
        )

        # Even with the other 4 checks satisfied, a missing NetSuite Expense
        # ID must still block payment — the HIGH-severity gap this fix closes.
        with self.assertRaises(ValueError):
            PartnerPaymentService.pay_partner(
                activity=self.partner_activity,
                partner_name="Partner ABC",
                amount=600000,
                method="Bank Transfer",
                reference="TXN-PART-123",
                user_id="accountant_jane",
            )
        self.partner_activity.refresh_from_db()
        self.assertNotEqual(self.partner_activity.status, "closed")

        # Now pay partner (with NetSuite ID) should pass
        pay = PartnerPaymentService.pay_partner(
            activity=self.partner_activity,
            partner_name="Partner ABC",
            amount=600000,
            method="Bank Transfer",
            reference="TXN-PART-123",
            user_id="accountant_jane",
            netsuite_id="NS-EXP-PARTNER-1",
        )
        self.assertEqual(pay.amount_paid, 600000)

        # Verify status updates to closed via the canonical
        # ClosureEligibilityService/ActivityClosureService.close() gate (not
        # a direct status="closed" write) and leaves a snapshot + NetSuite record.
        self.partner_activity.refresh_from_db()
        self.assertEqual(self.partner_activity.payment_status, "paid")
        self.assertEqual(self.partner_activity.status, "closed")

        self.assertTrue(
            NetSuiteExpenseRecord.objects.filter(
                activity=self.partner_activity, netsuite_expense_id="NS-EXP-PARTNER-1"
            ).exists()
        )
        snapshot = CompletedActivitySnapshot.objects.get(activity=self.partner_activity)
        self.assertEqual(snapshot.netsuite_expense_id, "NS-EXP-PARTNER-1")
        self.assertTrue(
            ActivityClosure.objects.filter(
                activity=self.partner_activity, status="closed"
            ).exists()
        )

    def test_clear_partner_payment_view_blocks_unverified_activity(self):
        """The /finance/actions/clear_partner_payment HTMX action is a second,
        independent entry point to the same closure PartnerPaymentService.pay_partner
        performs — it must enforce the same IA/evidence/SF-ID gate directly
        (not just rely on the queue UI only ever surfacing eligible activities),
        or a direct POST with an arbitrary activity_id could close an
        unverified activity."""
        from django.contrib.auth import get_user_model
        from apps.core.rbac import EdifyRole

        User = get_user_model()
        accountant = User.objects.create_user(
            email="accountant-clear@test.org",
            name="Clearing Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="password",
            is_active=True,
        )
        self.client.force_login(accountant)

        resp = self.client.post(
            "/finance/actions/clear_partner_payment",
            {
                "activity_id": self.partner_activity.id,
                "netsuite_id": "EXP-BLOCKED-1",
                "amount": "600000",
                "reference": "TXN-BLOCKED-1",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"IA Verification Missing", resp.content)

        self.partner_activity.refresh_from_db()
        self.assertNotEqual(self.partner_activity.status, "closed")
        self.assertEqual(self.partner_activity.payment_status, "pending")

    def _make_partner_activity_verification_eligible(self):
        """Same recipe test_partner_payment_blocked_and_success uses to clear
        the 4 FinanceBlockedReasonService checks (IA verified, evidence,
        SF ID) — leaves only the NetSuite ID requirement outstanding."""
        from apps.evidence.models import EvidenceRecord

        self.partner_activity.status = "ia_verified"
        self.partner_activity.salesforce_activity_id = "SF-ACT-CLEAR-1"
        self.partner_activity.save()
        EvidenceRecord.objects.create(
            activity=self.partner_activity,
            kind="visit_form",
            uri="https://s3.aws/report-clear.pdf",
            original_name="report-clear.pdf",
            file_size=1024,
            uploaded_by="partner_abc",
        )

    def _accountant_client(self):
        from django.contrib.auth import get_user_model
        from apps.core.rbac import EdifyRole

        User = get_user_model()
        accountant = User.objects.create_user(
            email="accountant-clear2@test.org",
            name="Clearing Accountant Two",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="password",
            is_active=True,
        )
        client = self.client_class()
        client.force_login(accountant)
        return client

    def test_clear_partner_payment_view_requires_netsuite_id(self):
        """Regression guard: the view used to accept an empty netsuite_id,
        write status="closed" directly, and only stash netsuite_id in an
        audit-log metadata blob — never creating a NetSuiteExpenseRecord.
        It must now enforce the same NetSuite-ID requirement
        PartnerPaymentService.pay_partner() enforces."""
        self._make_partner_activity_verification_eligible()
        client = self._accountant_client()

        resp = client.post(
            "/finance/actions/clear_partner_payment",
            {
                "activity_id": self.partner_activity.id,
                "netsuite_id": "",
                "amount": "600000",
                "reference": "TXN-NO-NETSUITE",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"NetSuite", resp.content)

        self.partner_activity.refresh_from_db()
        self.assertNotEqual(self.partner_activity.status, "closed")
        self.assertFalse(
            NetSuiteExpenseRecord.objects.filter(activity=self.partner_activity).exists()
        )

    def test_clear_partner_payment_view_success_creates_netsuite_record_and_snapshot(self):
        self._make_partner_activity_verification_eligible()
        client = self._accountant_client()

        resp = client.post(
            "/finance/actions/clear_partner_payment",
            {
                "activity_id": self.partner_activity.id,
                "netsuite_id": "NS-EXP-CLEAR-1",
                "amount": "600000",
                "reference": "TXN-CLEAR-1",
            },
        )
        self.assertEqual(resp.status_code, 200)

        self.partner_activity.refresh_from_db()
        self.assertEqual(self.partner_activity.payment_status, "paid")
        self.assertEqual(self.partner_activity.status, "closed")
        self.assertTrue(
            NetSuiteExpenseRecord.objects.filter(
                activity=self.partner_activity, netsuite_expense_id="NS-EXP-CLEAR-1"
            ).exists()
        )
        self.assertTrue(
            CompletedActivitySnapshot.objects.filter(activity=self.partner_activity).exists()
        )

    def test_reimbursement_claim_calculations(self):
        # Staff overspent or self-funded
        # Create advance disbursement first
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-123",
            user_id="accountant_jane",
        )

        # Staff actual spend is 600,000 (disbursed is 450,000) -> Claim is 150,000
        claim = ReimbursementService.claim_reimbursement(
            activity=self.staff_activity, actual_spend=600000, staff_id="cceo_user"
        )
        self.assertEqual(claim.reimbursement_amount, 150000)
        self.assertEqual(claim.status, "pending")

    def test_disburse_reimbursement_creates_completed_snapshot(self):
        """ReimbursementService.disburse_reimbursement() writes
        activity.status="closed" directly (it bypasses the canonical
        ActivityClosureService.close() gate — reimbursement claims carry no
        NetSuite ID of their own) but it must not skip the
        CompletedActivitySnapshot the canonical path always leaves behind."""
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-777",
            user_id="accountant_jane",
        )
        claim = ReimbursementService.claim_reimbursement(
            activity=self.staff_activity, actual_spend=600000, staff_id="cceo_user"
        )

        # A closed activity requires a Salesforce ID at the DB level
        # (closed_activity_must_have_sf_id) — satisfy it like a real
        # IA-verified activity would have.
        self.staff_activity.status = "ia_verified"
        self.staff_activity.salesforce_activity_id = "SF-ACT-STAFF-REIMB-1"
        self.staff_activity.save(update_fields=["status", "salesforce_activity_id"])

        self.assertFalse(
            CompletedActivitySnapshot.objects.filter(
                activity=self.staff_activity
            ).exists()
        )

        ReimbursementService.disburse_reimbursement(
            claim=claim,
            method="Bank Transfer",
            reference="TXN-REIMB-1",
            user_id="accountant_jane",
        )

        self.staff_activity.refresh_from_db()
        self.assertEqual(self.staff_activity.status, "closed")
        snapshot = CompletedActivitySnapshot.objects.get(activity=self.staff_activity)
        # 450,000 advance + 150,000 reimbursement = 600,000 total disbursed.
        self.assertEqual(snapshot.disbursed_amount, 600000)

    def test_accountability_and_netsuite_entry(self):
        # 1. Disburse advance
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-123",
            user_id="accountant_jane",
        )

        # 2. Staff submits accountability with variance (spent 500,000 instead of 450,000)
        acc = AccountabilityService.submit_accountability(
            activity=self.staff_activity,
            actual_spend=500000,
            variance_reason="Extra transport fees",
            staff_id="cceo_user",
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
            user_id="accountant_jane",
        )

        # Accountability record should resolve to cleared
        acc.refresh_from_db()
        self.assertEqual(acc.status, "cleared")
        self.assertEqual(acc.netsuite_expense_id, "NS-EXP-777")

        # Check NetSuite record was saved
        ns = NetSuiteExpenseRecord.objects.get(activity=self.staff_activity)
        self.assertEqual(ns.netsuite_expense_id, "NS-EXP-777")

    def test_netsuite_id_entry_closes_via_canonical_gate_and_snapshots(self):
        """NetSuiteExpenseService.enter_netsuite_id() must close through the
        canonical ClosureEligibilityService/ActivityClosureService.close()
        gate and leave a CompletedActivitySnapshot behind — not just flip
        status directly off the weaker 4-check FinanceBlockedReasonService set."""
        AdvanceDisbursementService.disburse_advance(
            activity=self.staff_activity,
            amount=450000,
            method="Mobile Money",
            reference="TXN-ADV-999",
            user_id="accountant_jane",
        )

        # Meet the remaining closure checklist items.
        self.staff_activity.status = "ia_verified"
        self.staff_activity.salesforce_activity_id = "SF-ACT-STAFF-1"
        self.staff_activity.save()

        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity=self.staff_activity,
            kind="visit_form",
            uri="https://s3.aws/staff-report.pdf",
            original_name="staff-report.pdf",
            file_size=2048,
            uploaded_by="cceo_user",
        )

        NetSuiteExpenseService.enter_netsuite_id(
            activity=self.staff_activity,
            netsuite_id="NS-EXP-CLOSE-1",
            amount=450000,
            expense_date=date(2026, 7, 20),
            user_id="accountant_jane",
        )

        self.staff_activity.refresh_from_db()
        self.assertEqual(self.staff_activity.status, "closed")

        snapshot = CompletedActivitySnapshot.objects.get(activity=self.staff_activity)
        self.assertEqual(snapshot.netsuite_expense_id, "NS-EXP-CLOSE-1")
        self.assertEqual(snapshot.disbursed_amount, 450000)
        self.assertTrue(
            ActivityClosure.objects.filter(
                activity=self.staff_activity, status="closed"
            ).exists()
        )

    # ── payment_status enum-reconciliation regression guards ────────────────
    # The advances/partner queues used to filter on payment_status="pending",
    # a value that does not exist in apps.core.enums.PaymentStatus and that
    # no code ever writes — both Accountant queues were permanently empty.

    def test_ready_for_advance_queue_lists_confirmed_advances(self):
        client = self._accountant_client()

        resp = client.get("/accounts/advances/")
        self.assertEqual(resp.status_code, 200)
        ids = {a.id for a in resp.context["advances"]}
        self.assertIn(self.staff_activity.id, ids)

        # Once disbursed it must leave the queue.
        self.staff_activity.payment_status = "disbursed"
        self.staff_activity.save(update_fields=["payment_status"])
        resp = client.get("/accounts/advances/")
        ids = {a.id for a in resp.context["advances"]}
        self.assertNotIn(self.staff_activity.id, ids)

    def test_partner_payments_queue_covers_both_real_pre_payment_states(self):
        self._make_partner_activity_verification_eligible()
        client = self._accountant_client()

        for state in ("none", "ia_confirmed"):
            self.partner_activity.payment_status = state
            self.partner_activity.save(update_fields=["payment_status"])
            resp = client.get("/accounts/partner-payments/")
            self.assertEqual(resp.status_code, 200)
            ids = {a.id for a in resp.context["payments"]}
            self.assertIn(self.partner_activity.id, ids, state)

        self.partner_activity.payment_status = "paid"
        self.partner_activity.save(update_fields=["payment_status"])
        resp = client.get("/accounts/partner-payments/")
        ids = {a.id for a in resp.context["payments"]}
        self.assertNotIn(self.partner_activity.id, ids)

    def test_live_certify_path_enters_partner_payment_queue(self):
        """ActivityCertificationService.certify_activity (the IA path wired
        to the real UI) must stamp partner activities ia_confirmed — the
        same payment-queue entry apps.activities.services.ia_confirm()
        documents — instead of leaving them at "none"."""
        from apps.activities.ia_services import ActivityCertificationService

        activity = Activity.objects.create(
            school=self.school,
            delivery_type="partner",
            activity_type=ActivityType.PARTNER_ACTIVITY,
            status="awaiting_ia_verification",
            payment_status="none",
            assigned_partner_id="partner_abc",
            planned_date=date(2026, 7, 25),
        )
        ActivityCertificationService.certify_activity(activity, {}, "ia_user")
        activity.refresh_from_db()
        self.assertEqual(activity.payment_status, "ia_confirmed")
