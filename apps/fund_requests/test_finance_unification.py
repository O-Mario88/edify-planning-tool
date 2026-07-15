"""2026-07-15 finance-unification mandate: the responsible employee is the
only normal originator of the NetSuite Expense ID; the Accountant verifies
but never originates it; over-spend and self-funded reimbursements are
auto-created and require the employee's own receipt confirmation before
accountability is financially cleared; no accountability closes with an
unresolved (unverified) return; the legacy System A disburse/netsuite-entry
endpoints are retired (they used to share the same AdvanceRequest rows the
canonical weekly/advance queues disburse from — a real double-disbursement
hazard).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.closure_services import (
    ActivityClosureService,
    ClosureEligibilityService,
)
from apps.activities.models import Activity, ActivityScheduleCostLine, CompletedActivitySnapshot
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.advance_service import (
    approve_accountability,
    confirm_reimbursement_receipt,
    reimburse,
    submit_accountability,
    submit_reimbursement,
    verify_return,
)
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


def _make_activity_and_advance(school, cceo, amount=100_000, advance_type="advance", status=None):
    activity = Activity.objects.create(
        school=school,
        activity_type="school_visit",
        delivery_type="staff",
        status="completed",
        responsible_staff_id=cceo.id,
        fy="2026",
        quarter="Q3",
        scheduled_date=timezone.now(),
        salesforce_activity_id=f"SV-{activity_counter()}",
    )
    line = ActivityScheduleCostLine.objects.create(
        activity=activity,
        cost_setting_key="staff_visit_transport_primary",
        label="Transport",
        unit_cost=amount,
        quantity=1,
        amount=amount,
        responsible_user=cceo.id,
    )
    adv = AdvanceRequest.objects.create(
        activity=activity,
        budget_line=line,
        responsible_user_id=cceo.id,
        fy="2026",
        quarter="Q3",
        amount=amount,
        advance_type=advance_type,
        status=status or AdvanceRequestStatus.DISBURSED,
        disbursed_amount=amount if advance_type == "advance" else None,
    )
    return activity, adv


_counter = [0]


def activity_counter():
    _counter[0] += 1
    return f"{88000000 + _counter[0]}"


class FinanceUnificationBaseTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="FU Region")
        district = District.objects.create(name="FU District", region=region)
        self.school = School.objects.create(
            school_id="FU-SCH", name="FU School", region=region, district=district
        )
        self.cceo = User.objects.create_user(
            email="cceo@fu.org",
            name="Fu CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.accountant = User.objects.create_user(
            email="acct@fu.org",
            name="Fu Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )

    def _ia_verify(self, activity):
        activity.ia_verification_status = "confirmed"
        activity.save(update_fields=["ia_verification_status"])


class OverspendReimbursementTest(FinanceUnificationBaseTest):
    """§9: over-spend on an advance-funded activity auto-creates a
    reimbursement — the employee never files a second, manual claim."""

    def test_overspend_routes_to_reimbursement_not_accounted(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-OVER-1"},
            self.cceo,
        )
        self._ia_verify(activity)

        approve_accountability(adv.id, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED)
        self.assertNotEqual(adv.status, AdvanceRequestStatus.ACCOUNTED)

    def test_reimbursement_amount_is_the_variance_not_the_full_spend(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-OVER-2"},
            self.cceo,
        )
        self._ia_verify(activity)
        approve_accountability(adv.id, self.accountant)
        adv.refresh_from_db()

        result = reimburse(
            adv.id, {"method": "bank_transfer", "reference": "BANK-OVER-2"}, self.accountant
        )
        # Variance = 150,000 - 100,000 = 50,000 — not the full 150,000 spend,
        # and the original advance's own disbursed_amount is untouched.
        self.assertEqual(result["reimbursedAmount"], 50_000)
        adv.refresh_from_db()
        self.assertEqual(adv.disbursed_amount, 100_000)
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_DISBURSED)

    def test_double_click_disburse_reimbursement_does_not_duplicate(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-DUP-1"},
            self.cceo,
        )
        self._ia_verify(activity)
        approve_accountability(adv.id, self.accountant)

        reimburse(adv.id, {"method": "cash", "reference": "REF-1"}, self.accountant)
        with self.assertRaises(BadRequest):
            reimburse(adv.id, {"method": "cash", "reference": "REF-2"}, self.accountant)

        adv.refresh_from_db()
        self.assertEqual(adv.reimburse_reference, "REF-1")

    def test_calling_approve_accountability_twice_does_not_reroute(self):
        """A second approve_accountability() call after the first already
        routed to REIMBURSEMENT_SUBMITTED must be rejected, not silently
        re-create a second reimbursement claim."""
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-TWICE-1"},
            self.cceo,
        )
        self._ia_verify(activity)
        approve_accountability(adv.id, self.accountant)
        with self.assertRaises(BadRequest):
            approve_accountability(adv.id, self.accountant)

    def test_employee_must_confirm_reimbursement_receipt_before_cleared(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-RCPT-1"},
            self.cceo,
        )
        self._ia_verify(activity)
        approve_accountability(adv.id, self.accountant)
        reimburse(adv.id, {"method": "cash", "reference": "REF-RCPT-1"}, self.accountant)

        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_DISBURSED)
        # Not yet accountant-cleared for closure purposes at this stage.
        checklist, _ = ClosureEligibilityService.evaluate(activity)
        self.assertFalse(checklist.accounts_cleared)

        confirm_reimbursement_receipt(adv.id, {"amount": 50_000}, self.cceo)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSED)
        self.assertIsNotNone(adv.reimbursement_receipt_confirmed_at)

        checklist, _ = ClosureEligibilityService.evaluate(activity)
        self.assertTrue(checklist.accounts_cleared)


class SelfFundedReimbursementTest(FinanceUnificationBaseTest):
    def test_self_funded_reimbursement_full_cycle(self):
        activity, adv = _make_activity_and_advance(
            self.school,
            self.cceo,
            amount=80_000,
            advance_type="self_funded",
            status=AdvanceRequestStatus.SELF_FUNDED_PENDING_REIMBURSEMENT,
        )
        submit_reimbursement(
            adv.id, {"amountSpent": 80_000, "netsuiteId": "EXP-SF-1"}, self.cceo
        )
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED)

        reimburse(adv.id, {"method": "cash", "reference": "REF-SF-1"}, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_DISBURSED)
        self.assertEqual(adv.reimbursed_amount, 80_000)
        # A self-funded advance was never actually disbursed.
        self.assertIsNone(adv.disbursed_amount)

        confirm_reimbursement_receipt(adv.id, {"amount": 80_000}, self.cceo)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSED)


class UnderSpendReturnVerificationTest(FinanceUnificationBaseTest):
    """§11: the Accountant must verify a declared return before
    accountability may clear — the employee's self-declaration alone is not
    enough."""

    def test_cannot_clear_underspend_without_verifying_return(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 70_000, "amountReturned": 30_000, "netsuiteId": "EXP-UND-1"},
            self.cceo,
        )
        self._ia_verify(activity)
        with self.assertRaises(BadRequest):
            approve_accountability(adv.id, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)

    def test_verify_return_then_clear_succeeds(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 70_000, "amountReturned": 30_000, "netsuiteId": "EXP-UND-2"},
            self.cceo,
        )
        self._ia_verify(activity)
        verify_return(adv.id, {"reference": "RET-REF-1"}, self.accountant)
        adv.refresh_from_db()
        self.assertIsNotNone(adv.return_verified_at)
        self.assertEqual(adv.return_reference, "RET-REF-1")

        approve_accountability(adv.id, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.ACCOUNTED)

    def test_exact_spend_clears_without_return_verification(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        submit_accountability(
            adv.id,
            {"amountSpent": 100_000, "amountReturned": 0, "netsuiteId": "EXP-EXACT-1"},
            self.cceo,
        )
        self._ia_verify(activity)
        approve_accountability(adv.id, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.ACCOUNTED)

    def test_returned_amount_rejected_on_overspend(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        with self.assertRaises(BadRequest):
            submit_accountability(
                adv.id,
                {"amountSpent": 120_000, "amountReturned": 5_000, "netsuiteId": "EXP-BAD-1"},
                self.cceo,
            )


class LegacyEntryPointRetiredTest(FinanceUnificationBaseTest):
    """§1/§27: the Accountant may never originate the employee's NetSuite ID,
    and the legacy activity-level disburse path (which shared the same
    AdvanceRequest rows the canonical weekly/advance queues disburse from)
    must not be able to move money anymore."""

    def test_mark_disbursed_action_no_longer_mutates(self):
        activity, adv = _make_activity_and_advance(
            self.school,
            self.cceo,
            amount=100_000,
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )
        adv.disbursed_amount = None
        adv.save(update_fields=["disbursed_amount"])
        self.client.force_login(self.accountant)

        resp = self.client.post(
            f"/accounts/activities/{activity.id}/disburse",
            {
                "amount_disbursed": "100000",
                "payment_method": "Cash",
                "payment_reference": "TXN-RETIRED-1",
            },
        )
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/disbursements", resp.headers.get("Location", ""))

        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE)
        self.assertIsNone(adv.disbursed_amount)
        activity.refresh_from_db()
        self.assertNotEqual(activity.payment_status, "disbursed")

    def test_netsuite_id_action_no_longer_lets_accountant_originate_id(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        self.client.force_login(self.accountant)

        resp = self.client.post(
            f"/accounts/activities/{activity.id}/netsuite-id",
            {
                "netsuite_expense_id": "ACCT-TYPED-ID",
                "amount_entered": "100000",
                "expense_date": "2026-07-15",
            },
        )
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn("/disbursements", resp.headers.get("Location", ""))

        from apps.fund_requests.models import NetSuiteExpenseRecord

        self.assertFalse(
            NetSuiteExpenseRecord.objects.filter(
                activity=activity, netsuite_expense_id="ACCT-TYPED-ID"
            ).exists()
        )
        activity.refresh_from_db()
        self.assertNotEqual(activity.status, "closed")


class CompletedActivitySnapshotFromAdvanceRequestTest(FinanceUnificationBaseTest):
    """§28 (this pass): the closure snapshot must not silently read 0 for an
    activity funded purely through the weekly-advance path (System B),
    which never creates a legacy Disbursement (System A) row."""

    def test_snapshot_disbursed_amount_reflects_advance_request_only(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        EvidenceRecord.objects.create(
            activity=activity, kind="photo", uri="p.jpg", uploaded_by=self.cceo.id
        )
        activity.status = "ia_verified"
        activity.ia_verification_status = "confirmed"
        activity.save(update_fields=["status", "ia_verification_status"])

        submit_accountability(
            adv.id,
            {"amountSpent": 100_000, "amountReturned": 0, "netsuiteId": "EXP-SNAP-1"},
            self.cceo,
        )
        approve_accountability(adv.id, self.accountant)

        from apps.fund_requests.models import Disbursement

        self.assertFalse(Disbursement.objects.filter(activity=activity).exists())

        self.assertTrue(ClosureEligibilityService.is_eligible(activity))
        ActivityClosureService.close(activity, closed_by=self.accountant.id)

        snapshot = CompletedActivitySnapshot.objects.get(activity=activity)
        self.assertEqual(snapshot.disbursed_amount, 100_000)
        self.assertEqual(snapshot.actual_spend_amount, 100_000)
        self.assertEqual(snapshot.netsuite_expense_id, "EXP-SNAP-1")

    def test_snapshot_includes_reimbursement_leg_for_overspend(self):
        activity, adv = _make_activity_and_advance(self.school, self.cceo, amount=100_000)
        EvidenceRecord.objects.create(
            activity=activity, kind="photo", uri="p2.jpg", uploaded_by=self.cceo.id
        )
        activity.status = "ia_verified"
        activity.ia_verification_status = "confirmed"
        activity.save(update_fields=["status", "ia_verification_status"])

        submit_accountability(
            adv.id,
            {"amountSpent": 150_000, "amountReturned": 0, "netsuiteId": "EXP-SNAP-2"},
            self.cceo,
        )
        approve_accountability(adv.id, self.accountant)
        reimburse(adv.id, {"method": "cash", "reference": "REF-SNAP-2"}, self.accountant)
        confirm_reimbursement_receipt(adv.id, {"amount": 50_000}, self.cceo)

        self.assertTrue(ClosureEligibilityService.is_eligible(activity))
        ActivityClosureService.close(activity, closed_by=self.accountant.id)

        snapshot = CompletedActivitySnapshot.objects.get(activity=activity)
        # 100,000 original advance + 50,000 reimbursement = 150,000 total disbursed.
        self.assertEqual(snapshot.disbursed_amount, 150_000)
        self.assertEqual(snapshot.actual_spend_amount, 150_000)
