"""Partner period invoices — partner → PL confirmation → accountant.

One invoice per instalment sums the partner's planned work for a period,
grouped by category; the entered amount must equal the system-fetched plan
total; the PL confirms against the plan before the accountant can pay; and
the money still lands per activity through the guarded instalment payer.
"""

import datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.fund_requests.finance_models import (
    PartnerInvoice,
    PartnerPayment,
)
from apps.fund_requests.partner_invoices import (
    confirm_invoice,
    invoice_basis,
    pay_invoice,
    pl_invoice_queue,
    return_invoice,
    submit_invoice,
)
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

PDF = b"%PDF-1.4 minimal partner invoice body"


def _pdf(name="invoice.pdf"):
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


class _P:
    def __init__(self, user, role=None, sp=None):
        self.user_id = user.id
        self.active_role = role or user.active_role
        self.staff_profile_id = sp.id if sp else None
        self.country_scope = False


class PartnerInvoiceTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.region = Region.objects.create(name="PI Region")
        self.district = District.objects.create(
            name="PI District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="PI-SCH",
            name="PI School",
            region=self.region,
            district=self.district,
        )
        self.partner_user = User.objects.create(
            id="pi-partner-user",
            email="pi-partner@test.org",
            name="PI Partner Officer",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            id="pi-partner",
            name="Literacy Uganda",
            active_status=True,
            user=self.partner_user,
        )
        self.cceo = User.objects.create(
            id="pi-cceo",
            email="pi-cceo@test.org",
            name="PI CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(
            id="pi-cceo-sp", user=self.cceo, title="CCEO"
        )
        self.pl = User.objects.create(
            id="pi-pl",
            email="pi-pl@test.org",
            name="PI PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.pl_sp = StaffProfile.objects.create(
            id="pi-pl-sp", user=self.pl, title="PL"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self.other_pl = User.objects.create(
            id="pi-pl2",
            email="pi-pl2@test.org",
            name="Other PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        self.other_pl_sp = StaffProfile.objects.create(
            id="pi-pl2-sp", user=self.other_pl, title="PL"
        )
        self.acct = User.objects.create(
            id="pi-acct",
            email="pi-acct@test.org",
            name="PI Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            is_active=True,
        )
        self.anchor = datetime.date(2026, 9, 10)
        # Two partner school visits (40k each) + one partner training (200k)
        # inside September.
        self.visits = [
            self._activity("school_visit", day=7 + i, amount=40_000) for i in range(2)
        ]
        self.training = self._activity("in_school_training", day=15, amount=200_000)

    def _activity(self, activity_type, day, amount):
        when = timezone.make_aware(datetime.datetime(2026, 9, day, 9, 0))
        activity = Activity.objects.create(
            school=self.school,
            activity_type=activity_type,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            responsible_staff_id=self.cceo_sp.id,
            status="scheduled",
            fy="2026",
            scheduled_date=when,
            salesforce_activity_id=f"SVE-PI-{activity_type}-{day}",
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="partner_training_lump_sum"
            if "training" in activity_type
            else "partner_visit_lump_sum",
            label="Partner rate",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            planned_date=when.date(),
            fiscal_year="2026",
            catalogue_id="cat-pi",
        )
        return activity

    def _verify(self, activity):
        from apps.evidence.models import EvidenceRecord

        activity.status = "ia_verified"
        activity.save(update_fields=["status"])
        EvidenceRecord.objects.create(
            activity=activity,
            kind="photo",
            uri="pi-evidence.jpg",
            uploaded_by="pi-cceo",
        )

    # ── the basis ────────────────────────────────────────────────────────────
    def test_basis_groups_by_category_and_sums_the_period(self):
        basis = invoice_basis(_P(self.partner_user), "month", self.anchor, "advance")
        self.assertEqual(basis["system_total"], 280_000)
        self.assertEqual(basis["payable"], 140_000)
        self.assertEqual(basis["groups"]["School Visits"]["planned"], 80_000)
        self.assertEqual(
            basis["groups"]["Training Facilitation Fee"]["planned"], 200_000
        )

    def test_non_partner_cannot_read_the_basis(self):
        with self.assertRaises(Forbidden):
            invoice_basis(_P(self.cceo), "month", self.anchor, "advance")

    # ── submit ───────────────────────────────────────────────────────────────
    def test_entered_total_must_equal_the_plan(self):
        with self.assertRaises(BadRequest):
            submit_invoice(
                _P(self.partner_user),
                "month",
                self.anchor,
                "advance",
                280_001,
                _pdf(),
            )

    def test_submit_routes_to_the_pl_with_items(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        invoice = PartnerInvoice.objects.get(id=result["id"])
        self.assertEqual(invoice.status, "submitted_to_pl")
        self.assertEqual(invoice.items.count(), 3)
        self.assertEqual(invoice.payable_amount, 140_000)
        # the instalment is consumed — nothing left to invoice this period
        basis = invoice_basis(_P(self.partner_user), "month", self.anchor, "advance")
        self.assertEqual(basis["items"], [])

    # ── the PL stage ─────────────────────────────────────────────────────────
    def test_pl_queue_scopes_to_the_supervising_pl(self):
        submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        self.assertEqual(len(pl_invoice_queue(_P(self.pl))), 1)
        self.assertEqual(len(pl_invoice_queue(_P(self.other_pl))), 0)

    def test_only_the_supervising_pl_confirms(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        with self.assertRaises(Forbidden):
            confirm_invoice(result["id"], _P(self.other_pl))
        confirm_invoice(result["id"], _P(self.pl))
        self.assertEqual(
            PartnerInvoice.objects.get(id=result["id"]).status, "confirmed_by_pl"
        )

    def test_return_frees_the_instalment_for_resubmission(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        return_invoice(result["id"], "Rates look wrong", _P(self.pl))
        invoice = PartnerInvoice.objects.get(id=result["id"])
        self.assertEqual(invoice.status, "returned_by_pl")
        self.assertEqual(invoice.items.count(), 0)
        basis = invoice_basis(_P(self.partner_user), "month", self.anchor, "advance")
        self.assertEqual(len(basis["items"]), 3)

    # ── the accountant stage ─────────────────────────────────────────────────
    def test_payment_requires_pl_confirmation(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        with self.assertRaises(BadRequest):
            pay_invoice(
                result["id"],
                {"payment_reference": "R1", "netsuite_expense_id": "NS-1"},
                _P(self.acct),
            )

    def test_paying_the_advance_lands_per_activity_with_all_guards(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        confirm_invoice(result["id"], _P(self.pl))
        paid = pay_invoice(
            result["id"],
            {"payment_reference": "EFT-PI-1", "netsuite_expense_id": "NS-PI-1"},
            _P(self.acct),
        )
        self.assertEqual(paid["paid"], 140_000)
        payments = PartnerPayment.objects.filter(payment_type="advance")
        self.assertEqual(payments.count(), 3)
        self.assertEqual(sum(p.amount_paid for p in payments), 140_000)
        with self.assertRaises(BadRequest):
            pay_invoice(
                result["id"],
                {"payment_reference": "EFT-PI-2", "netsuite_expense_id": "NS-PI-2"},
                _P(self.acct),
            )

    def test_clearance_opens_only_after_ia_and_completes_the_activity(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        confirm_invoice(result["id"], _P(self.pl))
        pay_invoice(
            result["id"],
            {"payment_reference": "EFT-PI-1", "netsuite_expense_id": "NS-PI-1"},
            _P(self.acct),
        )
        # Before IA clearance the clearance basis is empty.
        basis = invoice_basis(_P(self.partner_user), "month", self.anchor, "clearance")
        self.assertEqual(basis["items"], [])

        for activity in [*self.visits, self.training]:
            self._verify(activity)
        basis = invoice_basis(_P(self.partner_user), "month", self.anchor, "clearance")
        self.assertEqual(len(basis["items"]), 3)
        self.assertEqual(basis["payable"], 140_000)

        result2 = submit_invoice(
            _P(self.partner_user),
            "month",
            self.anchor,
            "clearance",
            280_000,
            _pdf("clearance.pdf"),
        )
        confirm_invoice(result2["id"], _P(self.pl))
        paid = pay_invoice(
            result2["id"],
            {"payment_reference": "EFT-PI-3", "netsuite_expense_id": "NS-PI-3"},
            _P(self.acct),
        )
        self.assertEqual(paid["paid"], 140_000)
        for activity in [*self.visits, self.training]:
            activity.refresh_from_db()
            self.assertEqual(activity.payment_status, "paid")

    def test_only_finance_pays(self):
        result = submit_invoice(
            _P(self.partner_user), "month", self.anchor, "advance", 280_000, _pdf()
        )
        confirm_invoice(result["id"], _P(self.pl))
        with self.assertRaises(Forbidden):
            pay_invoice(
                result["id"],
                {"payment_reference": "R", "netsuite_expense_id": "N"},
                _P(self.partner_user),
            )
