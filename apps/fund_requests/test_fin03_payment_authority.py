"""FIN-03 — partner-payment authority is `payment.act`, on every door.

Partner-payment authority was gated three different ways depending on which
screen you came in through:

  * the disbursements screens (`pay_partner_action`, `pay_transport_action`)
    carried only `require_page_permission("disbursements")`, and
    navigation maps that page to {Accountant, Admin};
  * `partner_invoices._FINANCE_ROLES` and `vendor_channel._assert_may_decide`
    admitted ("Accountant", "CountryDirector", "Admin") by role name;
  * `PartnerPaymentService.pay_partner` took a bare `user_id` and checked
    nothing at all.

The permission matrix is the authority, not the role tuples: `payment.act` is
held by the Program Accountant ALONE. The 2026-08 audit's AUD-004 put
`Permission.PAYMENT_ACT` into `ADMIN_EXCLUDED_PERMISSIONS` precisely so the
account that can approve a budget or verify an activity cannot also release
its money, and `disbursement_dashboard_service._require_accountant_action`
records the same rule in prose: "Admin may READ this dashboard but may not
move money from it."

These are the repros. Reading the payment queues stays open to Admin;
releasing money does not.
"""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests.finance_models import PartnerPayment, TransportPayment
from apps.fund_requests.finance_services import PartnerPaymentService
from apps.geography.models import District, Region
from apps.schools.models import School

PLANNED = 200_000  # two 100k lines
ADVANCE = PLANNED // 2


class _P:
    """The principal shape the finance services are handed by the views."""

    def __init__(self, user):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = None
        self.country_scope = False


class PaymentAuthorityTest(TestCase):
    def setUp(self):
        from apps.daily_visit_batches.models import DailyVisitBatch

        User = get_user_model()
        self.admin = User.objects.create_user(
            email="fin03-admin@test.org",
            name="FIN03 Admin",
            roles=["Admin"],
            active_role="Admin",
            password="password",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="fin03-cd@test.org",
            name="FIN03 Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="password",
            is_active=True,
        )
        self.acct = User.objects.create_user(
            email="fin03-acct@test.org",
            name="FIN03 Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password="password",
            is_active=True,
        )

        self.region = Region.objects.create(name="FIN03 Region")
        self.district = District.objects.create(
            name="FIN03 District", region=self.region
        )
        self.school = School.objects.create(
            school_id="FIN03-SCH",
            name="FIN03 School",
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
            salesforce_activity_id="SVE-FIN03-1",
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

        self.batch = DailyVisitBatch.objects.create(
            responsible_user="fin03-cceo",
            visit_date=datetime.date(2026, 8, 7),
            district_type="primary",
            rate_snapshot={
                "primary_transport_per_day": 280_000,
                "primary_lunch_per_day": 30_000,
            },
            daily_pool_amount=310_000,
        )
        Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            planned_date=self.batch.visit_date,
            responsible_staff_id=self.batch.responsible_user,
            daily_visit_batch=self.batch,
        )

    # ── fixture helpers ──────────────────────────────────────────────────────
    def _post_partner_pay(self, user):
        self.client.force_login(user)
        return self.client.post(
            f"/accounts/partner-payments/{self.activity.id}/pay",
            {
                "partner_name": "Literacy Uganda",
                "amount_paid": str(ADVANCE),
                "payment_method": "Bank Transfer",
                "payment_reference": "EFT-FIN03-1",
                "payment_type": "advance",
                "notes": "",
                "netsuite_expense_id": "",
            },
        )

    def _transport_obligation(self):
        from apps.fund_requests.vendor_channel import ensure_transport_obligation

        return ensure_transport_obligation(self.batch)

    def _post_transport_pay(self, user):
        payment = self._transport_obligation()
        self.client.force_login(user)
        self.client.post(
            f"/accounts/transport-payments/{payment.id}/pay",
            {
                "provider_name": "Kampala Fleet Ltd",
                "payment_method": "Bank Transfer",
                "payment_reference": "EFT-TP-FIN03",
                "netsuite_expense_id": "",
                "notes": "",
            },
        )
        return TransportPayment.objects.get(id=payment.id)

    def _pay_partner_as(self, user):
        return PartnerPaymentService.pay_partner(
            self.activity,
            "Literacy Uganda",
            ADVANCE,
            "Bank Transfer",
            "EFT-FIN03-SVC",
            user.id,
            payment_type=PartnerPayment.TYPE_ADVANCE,
        )

    def _pay_transport_as(self, user):
        from apps.fund_requests.vendor_channel import pay_transport_provider

        payment = self._transport_obligation()
        return pay_transport_provider(
            payment.id,
            {
                "provider_name": "Kampala Fleet Ltd",
                "payment_method": "Bank Transfer",
                "payment_reference": "EFT-TP-SVC",
                "netsuite_expense_id": "",
            },
            _P(user),
        )

    def _pay_invoice_as(self, user):
        """Probe the invoice gate alone.

        The authority check is the FIRST statement in `pay_invoice`, ahead of
        the invoice lookup, so a caller who clears it is refused with
        BadRequest("Invoice not found.") and one who does not is refused with
        Forbidden. That difference is the gate, without standing up the whole
        partner/PL/confirmation fixture.
        """
        from apps.fund_requests.partner_invoices import pay_invoice

        return pay_invoice(
            "no-such-invoice",
            {"payment_reference": "EFT-INV-FIN03", "payment_method": "Bank Transfer"},
            _P(user),
        )

    def _assert_no_partner_money_moved(self):
        self.assertEqual(
            PartnerPayment.objects.filter(activity=self.activity).count(),
            0,
            "partner money moved for a role that does not hold payment.act",
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.payment_status, "none")

    # ── the screens: Admin can SEE the queue but must not pay from it ────────
    def test_admin_cannot_pay_a_partner_from_the_disbursements_screen(self):
        self._post_partner_pay(self.admin)
        self._assert_no_partner_money_moved()

    def test_admin_cannot_pay_transport_from_the_disbursements_screen(self):
        payment = self._post_transport_pay(self.admin)
        self.assertEqual(payment.status, "pending")
        self.assertIsNone(payment.paid_by)

    # ── the services: every door, not just the screen that had the hole ──────
    def test_admin_cannot_pay_a_partner_at_the_service_layer(self):
        with self.assertRaises(Forbidden):
            self._pay_partner_as(self.admin)
        self._assert_no_partner_money_moved()

    def test_country_director_cannot_pay_a_partner_at_the_service_layer(self):
        with self.assertRaises(Forbidden):
            self._pay_partner_as(self.cd)
        self._assert_no_partner_money_moved()

    def test_admin_cannot_pay_transport_at_the_service_layer(self):
        with self.assertRaises(Forbidden):
            self._pay_transport_as(self.admin)

    def test_country_director_cannot_pay_transport_at_the_service_layer(self):
        with self.assertRaises(Forbidden):
            self._pay_transport_as(self.cd)

    def test_admin_cannot_pay_a_partner_invoice(self):
        with self.assertRaises(Forbidden):
            self._pay_invoice_as(self.admin)

    def test_country_director_cannot_pay_a_partner_invoice(self):
        with self.assertRaises(Forbidden):
            self._pay_invoice_as(self.cd)

    # ── the positive half: the Accountant must still be able to pay ──────────
    def test_the_accountant_still_pays_the_partner_from_the_screen(self):
        self._post_partner_pay(self.acct)
        payment = PartnerPayment.objects.get(activity=self.activity)
        self.assertEqual(payment.amount_paid, ADVANCE)
        self.assertEqual(payment.paid_by, self.acct.id)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.payment_status, "disbursed")

    def test_the_accountant_still_pays_transport_from_the_screen(self):
        payment = self._post_transport_pay(self.acct)
        self.assertEqual(payment.status, "paid")
        self.assertEqual(payment.paid_by, self.acct.id)

    def test_the_accountant_still_pays_the_partner_at_the_service_layer(self):
        payment = self._pay_partner_as(self.acct)
        self.assertEqual(payment.amount_paid, ADVANCE)

    def test_the_accountant_still_pays_transport_at_the_service_layer(self):
        result = self._pay_transport_as(self.acct)
        self.assertEqual(result["status"], "paid")

    def test_the_accountant_still_clears_the_invoice_gate(self):
        # Past the authority gate and into the invoice lookup — the proof the
        # fix refuses the right roles rather than everyone.
        with self.assertRaises(BadRequest):
            self._pay_invoice_as(self.acct)
