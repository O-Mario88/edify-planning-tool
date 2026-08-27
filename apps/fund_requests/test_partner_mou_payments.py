"""The partner MOU payment split (PartnerPaymentService).

The MOU pays a partner in two instalments: exactly 50% of the planned
activity cost up front (before the work happens), and the remaining balance
cleared only once the partner finishes the work and IA verifies it. One
instalment of each kind per activity; both clamped to the plan; both entered
in NetSuite; the advance never pays cancelled work and the clearance never
jumps the verification gate.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_models import PartnerPayment
from apps.fund_requests.finance_services import PartnerPaymentService
from apps.geography.models import District, Region
from apps.schools.models import School

PLANNED = 200_000  # two 100k lines
ADVANCE = PLANNED // 2


class PartnerMouPaymentTest(TestCase):
    def setUp(self):
        # "acct-1" is a real Program Accountant, not a loose string: pay_partner
        # asserts `payment.act` on the actor it is handed (FIN-03), so the
        # fixture has to name someone who actually holds it.
        get_user_model().objects.create(
            id="acct-1",
            email="mou-acct@test.org",
            name="MOU Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.region = Region.objects.create(name="MOU Region")
        self.district = District.objects.create(name="MOU District", region=self.region)
        self.school = School.objects.create(
            school_id="MOU-SCH",
            name="MOU School",
            region=self.region,
            district=self.district,
        )
        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="partner_activity",
            delivery_type="partner",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.now(),
            salesforce_activity_id="SVE-MOU-1",
        )
        for key in ("partner_training_lump_sum", "partner_venue_contribution"):
            ActivityScheduleCostLine.objects.create(
                activity=self.activity,
                school=self.school,
                cost_setting_key=key,
                label=key.replace("_", " ").title(),
                unit_cost=100_000,
                quantity=1,
                amount=100_000,
            )

    # ── fixture helpers ──────────────────────────────────────────────────────
    def _pay(self, amount, payment_type, reference="REF-1"):
        return PartnerPaymentService.pay_partner(
            self.activity,
            "Literacy Uganda",
            amount,
            "Bank Transfer",
            reference,
            "acct-1",
            netsuite_id=f"NS-{reference}",
            payment_type=payment_type,
        )

    def _verify_work(self):
        """The partner finishes; IA verifies — the clearance gate opens."""
        self.activity.status = "ia_verified"
        self.activity.save(update_fields=["status"])
        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="photo",
            uri="mou-evidence.jpg",
            uploaded_by="cceo-1",
        )

    # ── the 50% advance ──────────────────────────────────────────────────────
    def test_advance_is_exactly_half_the_planned_cost(self):
        pay = self._pay(ADVANCE, "advance")
        self.assertEqual(pay.payment_type, "advance")
        self.assertEqual(pay.amount_paid, ADVANCE)
        self.activity.refresh_from_db()
        # Money moved, accountability open — NOT terminal.
        self.assertEqual(self.activity.payment_status, "disbursed")

    def test_advance_refuses_any_other_amount(self):
        for wrong in (ADVANCE - 1, ADVANCE + 1, PLANNED, 0, -5):
            with self.assertRaises(BadRequest):
                self._pay(wrong, "advance")

    def test_advance_is_paid_before_verification(self):
        # status is merely "scheduled" — the advance must NOT require the
        # execution blockers (IA verification, evidence).
        pay = self._pay(ADVANCE, "advance")
        self.assertIsNotNone(pay)

    def test_second_advance_is_refused(self):
        self._pay(ADVANCE, "advance")
        with self.assertRaises(BadRequest):
            self._pay(ADVANCE, "advance", reference="REF-2")

    def test_advance_refuses_cancelled_work(self):
        self.activity.status = "cancelled"
        self.activity.save(update_fields=["status"])
        with self.assertRaises(BadRequest):
            self._pay(ADVANCE, "advance")

    def test_advance_requires_costed_lines(self):
        bare = Activity.objects.create(
            school=self.school,
            activity_type="partner_activity",
            delivery_type="partner",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.now(),
        )
        with self.assertRaises(BadRequest):
            PartnerPaymentService.pay_partner(
                bare,
                "Literacy Uganda",
                1,
                "Bank Transfer",
                "REF-B",
                "acct-1",
                netsuite_id="NS-B",
                payment_type="advance",
            )

    # ── the clearance ────────────────────────────────────────────────────────
    def test_clearance_requires_verified_work(self):
        self._pay(ADVANCE, "advance")
        # Work not verified yet — the balance must not clear.
        with self.assertRaises(BadRequest):
            self._pay(PLANNED - ADVANCE, "clearance", reference="REF-C")

    def test_clearance_settles_the_balance_after_verification(self):
        self._pay(ADVANCE, "advance")
        self._verify_work()
        pay = self._pay(PLANNED - ADVANCE, "clearance", reference="REF-C")
        self.assertEqual(pay.amount_paid, PLANNED - ADVANCE)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.payment_status, "paid")
        total_paid = sum(
            p.amount_paid for p in PartnerPayment.objects.filter(activity=self.activity)
        )
        self.assertEqual(total_paid, PLANNED)

    def test_clearance_cannot_exceed_the_balance(self):
        self._pay(ADVANCE, "advance")
        self._verify_work()
        with self.assertRaises(BadRequest):
            self._pay(PLANNED - ADVANCE + 1, "clearance", reference="REF-C")

    def test_second_clearance_is_refused(self):
        self._pay(ADVANCE, "advance")
        self._verify_work()
        self._pay(PLANNED - ADVANCE, "clearance", reference="REF-C")
        with self.assertRaises(BadRequest):
            self._pay(1, "clearance", reference="REF-D")

    def test_full_clearance_without_an_advance_still_works(self):
        # Legacy path: a verified activity that never took its advance simply
        # clears in full — historical single payments keep their meaning.
        self._verify_work()
        pay = self._pay(PLANNED, "clearance", reference="REF-F")
        self.assertEqual(pay.amount_paid, PLANNED)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.payment_status, "paid")

    def test_advance_after_clearance_is_refused(self):
        self._verify_work()
        self._pay(PLANNED, "clearance", reference="REF-F")
        with self.assertRaises(BadRequest):
            self._pay(ADVANCE, "advance", reference="REF-G")

    def test_unknown_payment_type_is_refused(self):
        with self.assertRaises(BadRequest):
            self._pay(ADVANCE, "half-now")
