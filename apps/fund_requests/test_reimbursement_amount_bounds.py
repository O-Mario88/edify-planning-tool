"""FIN-02 (2026-08-24 audit, P1): the reimbursement payout must be bounded
BEFORE the money moves.

`reimburse()` accepted any integer — negative, zero, absurd, or simply wrong —
wrote it to reimbursed_amount and moved the advance to
REIMBURSEMENT_DISBURSED. The settlement identity (`_reconciliation_ok`,
mandate §22: accounted == disbursed - returned + reimbursed) was only checked
afterwards, at `confirm_reimbursement_receipt` — the ONLY exit from
REIMBURSEMENT_DISBURSED. There is no correction, reversal or override
transition, so a mistyped figure paid out real money AND stranded the record
permanently.

The identity leaves exactly one payable figure:
    reimbursed == accounted - (disbursed - returned)
These tests hold `reimburse()` to it, and prove the correct figure still pays
out and still settles through to REIMBURSED.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.fund_requests import advance_service
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()

FY = "2026"


class ReimbursementAmountBoundsTest(TestCase):
    """A PL-approved, IA-verified claim sitting in the Accountant's
    reimbursement queue — the exact state `reimburse()` pays out from."""

    def setUp(self):
        region = Region.objects.create(name="FIN02 Region")
        district = District.objects.create(name="FIN02 District", region=region)
        school = School.objects.create(
            school_id="FIN02-SCH", name="FIN02 School", region=region, district=district
        )
        self.owner = User.objects.create_user(
            email="owner@fin02.org",
            name="Olive Owner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.owner, title="CCEO")
        self.accountant = User.objects.create_user(
            email="acct@fin02.org",
            name="Alan Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        self.activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=self.owner.id,
            fy=FY,
            quarter="Q3",
            scheduled_date=timezone.now(),
            salesforce_activity_id="SV-11223344",
            ia_verification_status="confirmed",
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            responsible_user=self.owner.id,
        )

    def _claim(self, **overrides) -> AdvanceRequest:
        """A self-funded claim: nothing was disbursed, so the whole accounted
        spend (UGX 100,000) is the reimbursement due."""
        fields = {
            "activity": self.activity,
            "budget_line": self.line,
            "responsible_user_id": self.owner.id,
            "fy": FY,
            "quarter": "Q3",
            "amount": 100_000,
            "advance_type": "self_funded",
            "status": AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED,
            "accounted_amount": 100_000,
            "accountability_netsuite_id": "EXP-2026-902",
            "accountability_submitted_at": timezone.now(),
            "accountability_pl_approved_at": timezone.now(),
        }
        fields.update(overrides)
        return AdvanceRequest.objects.create(**fields)

    def _assert_no_money_moved(self, adv: AdvanceRequest):
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED)
        self.assertIsNone(adv.reimbursed_amount)
        self.assertIsNone(adv.reimbursed_at)

    # ── Refusals: every one of these must happen BEFORE the write ──────────
    def test_negative_reimbursement_amount_is_refused(self):
        adv = self._claim()
        with self.assertRaises(BadRequest):
            advance_service.reimburse(adv.id, {"amount": -50_000}, self.accountant)
        self._assert_no_money_moved(adv)

    def test_zero_reimbursement_amount_is_refused(self):
        """Zero is an explicit instruction to pay nothing, not an omission —
        it must not silently fall through to the default."""
        adv = self._claim()
        with self.assertRaises(BadRequest):
            advance_service.reimburse(adv.id, {"amount": 0}, self.accountant)
        self._assert_no_money_moved(adv)

    def test_absurd_reimbursement_amount_is_refused(self):
        adv = self._claim()
        with self.assertRaises(BadRequest):
            advance_service.reimburse(adv.id, {"amount": 999_999_999}, self.accountant)
        self._assert_no_money_moved(adv)

    def test_amount_breaking_the_settlement_identity_is_refused(self):
        """UGX 200,000 against an accounted UGX 100,000 is a plausible
        fat-finger (a doubled figure) and is unsettleable by construction."""
        adv = self._claim()
        with self.assertRaises(BadRequest):
            advance_service.reimburse(adv.id, {"amount": 200_000}, self.accountant)
        self._assert_no_money_moved(adv)

    def test_overspend_claim_refuses_the_full_spend_instead_of_the_variance(self):
        """Advance-funded over-spend: UGX 60,000 was already disbursed against
        an accounted UGX 100,000, so only the UGX 40,000 variance is due.
        Paying the full accounted spend would double-fund the disbursed part."""
        adv = self._claim(
            advance_type="advance",
            disbursed_amount=60_000,
            disbursed_at=timezone.now(),
        )
        with self.assertRaises(BadRequest):
            advance_service.reimburse(adv.id, {"amount": 100_000}, self.accountant)
        self._assert_no_money_moved(adv)

    def test_unparseable_amount_is_refused_rather_than_silently_defaulted(self):
        adv = self._claim()
        with self.assertRaises(BadRequest):
            advance_service.reimburse(
                adv.id, {"amount": "one hundred"}, self.accountant
            )
        self._assert_no_money_moved(adv)

    # ── The correct amount must still pay out and still settle ─────────────
    def test_correct_amount_pays_out_and_settles_through_receipt_confirmation(self):
        adv = self._claim()
        advance_service.reimburse(
            adv.id,
            {"amount": 100_000, "method": "Bank", "reference": "RB-FIN02"},
            self.accountant,
        )
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSEMENT_DISBURSED)
        self.assertEqual(adv.reimbursed_amount, 100_000)

        advance_service.confirm_reimbursement_receipt(adv.id, {}, self.owner)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSED)
        self.assertEqual(adv.reimbursement_receipt_confirmed_amount, 100_000)

    def test_omitted_amount_still_defaults_to_the_reimbursement_due(self):
        adv = self._claim(
            advance_type="advance",
            disbursed_amount=60_000,
            disbursed_at=timezone.now(),
        )
        advance_service.reimburse(adv.id, {"method": "Bank"}, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.reimbursed_amount, 40_000)
        advance_service.confirm_reimbursement_receipt(adv.id, {}, self.owner)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSED)

    def test_variance_amount_pays_out_on_an_overspend_claim(self):
        adv = self._claim(
            advance_type="advance",
            disbursed_amount=60_000,
            disbursed_at=timezone.now(),
        )
        advance_service.reimburse(adv.id, {"amount": 40_000}, self.accountant)
        adv.refresh_from_db()
        self.assertEqual(adv.reimbursed_amount, 40_000)
        advance_service.confirm_reimbursement_receipt(adv.id, {}, self.owner)
        adv.refresh_from_db()
        self.assertEqual(adv.status, AdvanceRequestStatus.REIMBURSED)


class AccountabilityNegativeFiguresTest(TestCase):
    """FIN-02, second half: `submit_accountability` read accounted/returned
    straight from the payload, so a negative figure persisted and inverted the
    variance branch in `approve_accountability`."""

    def setUp(self):
        region = Region.objects.create(name="FIN02B Region")
        district = District.objects.create(name="FIN02B District", region=region)
        school = School.objects.create(
            school_id="FIN02B-SCH",
            name="FIN02B School",
            region=region,
            district=district,
        )
        self.owner = User.objects.create_user(
            email="owner@fin02b.org",
            name="Owen Owner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.owner, title="CCEO")
        self.activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=self.owner.id,
            fy=FY,
            quarter="Q3",
            scheduled_date=timezone.now(),
            salesforce_activity_id="SV-99887766",
        )
        self.line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="staff_visit_transport_primary",
            label="Transport",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
            responsible_user=self.owner.id,
        )
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.line,
            responsible_user_id=self.owner.id,
            fy=FY,
            quarter="Q3",
            amount=100_000,
            status=AdvanceRequestStatus.DISBURSED,
            disbursed_amount=100_000,
            disbursed_at=timezone.now(),
        )

    def test_negative_amount_spent_is_refused(self):
        # A variance note is supplied so the pre-existing under-spend guard is
        # satisfied — the ONLY thing left that can refuse this is the sign
        # check itself.
        with self.assertRaisesMessage(BadRequest, "must not be negative"):
            advance_service.submit_accountability(
                self.adv.id,
                {
                    "amountSpent": -100_000,
                    "netsuiteId": "EXP-2026-903",
                    "varianceNote": "Typed the figure with a minus sign.",
                },
                self.owner,
            )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)
        self.assertIsNone(self.adv.accounted_amount)

    def test_negative_amount_returned_is_refused(self):
        with self.assertRaisesMessage(BadRequest, "must not be negative"):
            advance_service.submit_accountability(
                self.adv.id,
                {
                    "amountSpent": 90_000,
                    "amountReturned": -10_000,
                    "netsuiteId": "EXP-2026-904",
                    "varianceNote": "Return keyed as a negative adjustment.",
                },
                self.owner,
            )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)
        self.assertIsNone(self.adv.returned_amount)

    def test_valid_accountability_still_submits(self):
        advance_service.submit_accountability(
            self.adv.id,
            {
                "amountSpent": 90_000,
                "amountReturned": 10_000,
                "netsuiteId": "EXP-2026-905",
            },
            self.owner,
        )
        self.adv.refresh_from_db()
        self.assertEqual(
            self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PL_PENDING
        )
        self.assertEqual(self.adv.accounted_amount, 90_000)
        self.assertEqual(self.adv.returned_amount, 10_000)
