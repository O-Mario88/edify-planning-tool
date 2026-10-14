"""A partner's invoice goes to the Programme Lead whose schools it is for.

Owner, 2026-10-08: the invoice "goes to the program lead for that region (The
PL own schools, schools of CCEOs under him)", and the platform writes it: the
partner neither types a total nor has to attach a document of its own.

Before, one invoice for visits in two teams sat in both Leads' queues and
either could confirm all of it; a visit at a school a Lead holds themselves
reached no Lead at all.
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_models import PartnerInvoice
from apps.fund_requests.invoice_routing import LeadResolver, split_by_lead
from apps.fund_requests.partner_invoices import (
    confirm_invoice,
    invoice_basis,
    invoice_document,
    pay_invoice,
    pl_invoice_queue,
    submit_invoice,
)
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

User = get_user_model()
ANCHOR = datetime.date(2026, 9, 10)


class _P:
    """The principal the services read: a user in one role."""

    def __init__(self, user, sp=None):
        self.id = user.id
        self.user_id = user.id
        self.name = user.name
        self.active_role = user.active_role
        self.staff_profile_id = sp.id if sp else None
        self.country_scope = False


def _person(key: str, role: str, name: str):
    user = User.objects.create(
        id=f"ir-{key}",
        email=f"ir-{key}@test.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user, StaffProfile.objects.create(id=f"ir-{key}-sp", user=user, title=role)


class _Fixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="IR Region")
        self.district = District.objects.create(
            name="IR District", region=self.region, district_type="primary"
        )
        self.partner_user = User.objects.create(
            id="ir-partner-user",
            email="ir-partner@test.org",
            name="Grace Nakato",
            roles=["PartnerAdmin"],
            active_role="PartnerAdmin",
            is_active=True,
        )
        self.partner = Partner.objects.create(
            id="ir-partner",
            name="Literacy Works",
            active_status=True,
            user=self.partner_user,
            contact_person="Grace Nakato",
        )
        self.north_lead, self.north_lead_sp = _person(
            "pl-n", "Program Lead", "Nora North"
        )
        self.south_lead, self.south_lead_sp = _person(
            "pl-s", "Program Lead", "Sam South"
        )
        self.north_cceo, self.north_cceo_sp = _person("cceo-n", "CCEO", "Nick Officer")
        self.south_cceo, self.south_cceo_sp = _person("cceo-s", "CCEO", "Sara Officer")
        self.accountant, _ = _person("acct", "Accountant", "Ada Accounts")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.north_lead_sp, supervisee=self.north_cceo_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.south_lead_sp, supervisee=self.south_cceo_sp
        )
        self.north_school = self._school("N1", holder=self.north_cceo_sp)
        self.south_school = self._school("S1", holder=self.south_cceo_sp)
        self.lead_school = self._school("L1", holder=self.north_lead_sp)

    def _school(self, code: str, holder=None):
        school = School.objects.create(
            school_id=f"IR-{code}",
            name=f"IR School {code}",
            region=self.region,
            district=self.district,
        )
        if holder is not None:
            StaffSchoolAssignment.objects.create(staff=holder, school_id=school.id)
        return school

    def _visit(self, school, day: int, amount: int, *, monitor=None, **fields):
        when = timezone.make_aware(datetime.datetime(2026, 9, day, 9, 0))
        activity = Activity.objects.create(
            school=school,
            activity_type=fields.pop("activity_type", "school_visit"),
            delivery_type=fields.pop("delivery_type", "partner"),
            assigned_partner_id=fields.pop("assigned_partner_id", self.partner.id),
            monitored_by_staff_id=getattr(monitor, "id", None),
            status="partner_scheduled",
            fy="2026",
            scheduled_date=when,
            delivery_contact_name="Grace Nakato",
            **fields,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=school,
            cost_setting_key="partner_visit_lump_sum",
            label="Partner rate",
            unit_cost=amount,
            quantity=1,
            amount=amount,
            planned_date=when.date(),
            fiscal_year="2026",
            catalogue_id="cat-ir",
        )
        return activity


class LeadOfAnActivityTest(_Fixture):
    """The rule itself (``invoice_routing.LeadResolver``)."""

    def _lead(self, activity):
        lead = LeadResolver([activity]).lead_of(activity)
        return lead.name if lead else None

    def test_a_school_an_officer_holds_goes_to_the_lead_they_report_to(self):
        self.assertEqual(self._lead(self._visit(self.north_school, 7, 1)), "Nora North")
        self.assertEqual(self._lead(self._visit(self.south_school, 8, 1)), "Sam South")

    def test_a_school_the_lead_holds_goes_to_that_lead(self):
        """It reached nobody: the old rule looked for the holder's supervisor,
        and a Lead's supervisor is the Country Director."""
        self.assertEqual(self._lead(self._visit(self.lead_school, 9, 1)), "Nora North")

    def test_who_holds_the_school_now_decides_not_who_was_named_when_it_was_dated(self):
        """A school handed on to another team after the partner dated its
        visit is that team's Lead's to confirm."""
        visit = self._visit(self.north_school, 10, 1, monitor=self.north_cceo_sp)
        StaffSchoolAssignment.objects.filter(school_id=self.north_school.id).update(
            staff=self.south_cceo_sp
        )
        self.assertEqual(self._lead(visit), "Sam South")

    def test_a_school_nobody_holds_goes_by_the_officer_on_the_activity(self):
        orphan = self._school("O1")
        self.assertEqual(
            self._lead(self._visit(orphan, 11, 1, monitor=self.south_cceo_sp)),
            "Sam South",
        )
        # The id may be the person's user id rather than their People record.
        self.assertEqual(
            self._lead(self._visit(orphan, 12, 1, monitor=self.north_cceo)),
            "Nora North",
        )

    def test_work_at_no_single_school_goes_by_the_officer_who_runs_it(self):
        """A group training an officer runs, the partner facilitating."""
        training = self._visit(
            None,
            13,
            1,
            activity_type="cluster_training",
            delivery_type="staff",
            assigned_partner_id=None,
            facilitating_partner_id=self.partner.id,
            responsible_staff_id=self.north_cceo_sp.id,
        )
        self.assertEqual(self._lead(training), "Nora North")

    def test_an_oversight_line_is_not_a_lead(self):
        """Impact Assessment and the Regional Vice President hold lines over
        the same officers. Neither confirms a partner's invoice."""
        _, ia_sp = _person("ia", "ImpactAssessment", "Ian Assess")
        _, loose_sp = _person("cceo-x", "CCEO", "Xavier Loose")
        StaffSupervisorAssignment.objects.create(supervisor=ia_sp, supervisee=loose_sp)
        school = self._school("X1", holder=loose_sp)
        self.assertIsNone(self._lead(self._visit(school, 14, 1)))

    def test_a_lead_working_in_a_second_role_is_still_the_lead(self):
        self.north_lead.roles = ["Program Lead", "ProjectCoordinator"]
        self.north_lead.active_role = "ProjectCoordinator"
        self.north_lead.save(update_fields=["roles", "active_role"])
        self.assertEqual(
            self._lead(self._visit(self.north_school, 15, 1)), "Nora North"
        )

    def test_lines_fold_by_lead_with_the_unrouted_last(self):
        orphan = self._school("O2")
        items = [
            {"activity": self._visit(self.south_school, 7, 1)},
            {"activity": self._visit(orphan, 8, 1)},
            {"activity": self._visit(self.north_school, 9, 1)},
            {"activity": self._visit(self.lead_school, 10, 1)},
        ]
        groups = split_by_lead(items)
        self.assertEqual(
            [(lead.name if lead else None, len(rows)) for lead, rows in groups],
            [("Nora North", 2), ("Sam South", 1), (None, 1)],
        )


class InvoicePerLeadTest(_Fixture):
    """One invoice for each Lead, each confirming their own schools."""

    def setUp(self):
        super().setUp()
        self.north_visit = self._visit(self.north_school, 7, 40_000)
        self.lead_visit = self._visit(self.lead_school, 8, 60_000)
        self.south_visit = self._visit(self.south_school, 9, 100_000)
        self.partner_p = _P(self.partner_user)

    def test_the_preview_shows_which_lead_each_part_goes_to(self):
        basis = invoice_basis(self.partner_p, "month", ANCHOR, "advance")
        self.assertEqual(basis["system_total"], 200_000)
        self.assertEqual(
            [
                (g["lead"].name, g["system_total"], g["payable"])
                for g in basis["by_lead"]
            ],
            [("Nora North", 100_000, 50_000), ("Sam South", 100_000, 50_000)],
        )

    def test_sending_raises_one_invoice_for_each_lead(self):
        result = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        self.assertEqual(len(result["invoices"]), 2)
        self.assertEqual(result["payable"], 100_000)
        north = PartnerInvoice.objects.get(program_lead_staff_id=self.north_lead_sp.id)
        south = PartnerInvoice.objects.get(program_lead_staff_id=self.south_lead_sp.id)
        self.assertEqual(
            set(north.items.values_list("activity_id", flat=True)),
            {self.north_visit.id, self.lead_visit.id},
        )
        self.assertEqual(
            list(south.items.values_list("activity_id", flat=True)),
            [self.south_visit.id],
        )
        self.assertEqual((north.system_total, north.payable_amount), (100_000, 50_000))
        self.assertEqual((south.system_total, south.payable_amount), (100_000, 50_000))

    def test_each_lead_sees_and_confirms_only_their_own(self):
        submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        north = PartnerInvoice.objects.get(program_lead_staff_id=self.north_lead_sp.id)
        south = PartnerInvoice.objects.get(program_lead_staff_id=self.south_lead_sp.id)
        north_p = _P(self.north_lead, self.north_lead_sp)
        south_p = _P(self.south_lead, self.south_lead_sp)
        self.assertEqual([i.id for i in pl_invoice_queue(north_p)], [north.id])
        self.assertEqual([i.id for i in pl_invoice_queue(south_p)], [south.id])
        with self.assertRaises(Forbidden):
            confirm_invoice(south.id, north_p)
        confirm_invoice(north.id, north_p)
        north.refresh_from_db()
        south.refresh_from_db()
        self.assertEqual(north.status, "confirmed_by_pl")
        self.assertEqual(south.status, "submitted_to_pl")

    def test_the_accountant_still_reads_every_invoice(self):
        submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        self.assertEqual(len(pl_invoice_queue(_P(self.accountant))), 2)

    def test_work_no_lead_holds_is_invoiced_and_left_to_finance(self):
        orphan = self._school("O3")
        self._visit(orphan, 20, 30_000)
        result = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        self.assertEqual(len(result["invoices"]), 3)
        unrouted = PartnerInvoice.objects.get(program_lead_staff_id__isnull=True)
        self.assertEqual(unrouted.system_total, 30_000)
        for lead, sp in (
            (self.north_lead, self.north_lead_sp),
            (self.south_lead, self.south_lead_sp),
        ):
            self.assertNotIn(
                unrouted.id, [i.id for i in pl_invoice_queue(_P(lead, sp))]
            )
        self.assertIn(
            unrouted.id, [i.id for i in pl_invoice_queue(_P(self.accountant))]
        )

    def test_an_invoice_raised_before_the_split_keeps_its_leads(self):
        """An older invoice names no Lead and may cover two teams: the Leads
        of its schools still find it, as they did."""
        from apps.fund_requests.finance_models import PartnerInvoiceItem

        invoice = PartnerInvoice.objects.create(
            partner_id=self.partner.id,
            invoice_type="advance",
            period_kind="month",
            period_start=datetime.date(2026, 9, 1),
            period_end=datetime.date(2026, 9, 30),
            system_total=40_000,
            entered_total=40_000,
            payable_amount=20_000,
            stored_name="legacy.pdf",
            original_name="legacy.pdf",
            submitted_by=self.partner_user.id,
        )
        PartnerInvoiceItem.objects.create(
            invoice=invoice,
            activity=self.lead_visit,
            instalment="advance",
            planned_amount=60_000,
            payable_amount=30_000,
            category="School Visits",
        )
        north_p = _P(self.north_lead, self.north_lead_sp)
        self.assertIn(invoice.id, [i.id for i in pl_invoice_queue(north_p)])
        confirm_invoice(invoice.id, north_p)


class SystemWrittenInvoiceTest(_Fixture):
    """The platform writes the invoice from the plan."""

    def setUp(self):
        super().setUp()
        self.visit = self._visit(self.north_school, 7, 40_000)
        self.partner_p = _P(self.partner_user)

    def test_no_total_is_typed_and_no_document_is_attached(self):
        result = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        invoice = PartnerInvoice.objects.get(id=result["id"])
        self.assertEqual(invoice.system_total, 40_000)
        self.assertEqual(invoice.entered_total, 40_000)
        self.assertEqual(invoice.stored_name, "")

    def test_a_total_that_is_typed_must_still_be_the_plans(self):
        with self.assertRaises(BadRequest):
            submit_invoice(self.partner_p, "month", ANCHOR, "advance", 39_000)

    def test_the_invoice_lists_each_visit_with_who_went_and_its_evidence(self):
        EvidenceRecord.objects.create(
            activity=self.visit,
            kind="photo",
            uri="ir-1.jpg",
            uploaded_by="ir-partner-user",
        )
        EvidenceRecord.objects.create(
            activity=self.visit,
            kind="photo",
            uri="ir-2.jpg",
            uploaded_by="ir-partner-user",
        )
        result = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        doc = invoice_document(result["id"], self.partner_p)
        self.assertEqual(doc["partner_name"], "Literacy Works")
        self.assertEqual(doc["lead_name"], "Nora North")
        self.assertFalse(doc["has_file"])
        self.assertTrue(doc["reference"].startswith("INV-"))
        (line,) = doc["lines"]
        self.assertEqual(line["place"], "IR School N1")
        self.assertEqual(line["district"], "IR District")
        self.assertEqual(line["delivered_by"], "Grace Nakato")
        self.assertEqual(line["evidence"], 2)
        self.assertEqual((line["planned"], line["payable"]), (40_000, 20_000))

    def test_who_may_open_it(self):
        result = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        north_p = _P(self.north_lead, self.north_lead_sp)
        south_p = _P(self.south_lead, self.south_lead_sp)
        invoice_document(result["id"], self.partner_p)
        invoice_document(result["id"], north_p)
        invoice_document(result["id"], _P(self.accountant))
        with self.assertRaises(Forbidden):
            invoice_document(result["id"], south_p)
        with self.assertRaises(Forbidden):
            invoice_document(result["id"], _P(self.north_cceo, self.north_cceo_sp))
        stranger = User.objects.create(
            id="ir-other-partner",
            email="ir-other@test.org",
            name="Other Partner",
            roles=["PartnerAdmin"],
            active_role="PartnerAdmin",
            is_active=True,
        )
        Partner.objects.create(id="ir-partner-2", name="Other Org", user=stranger)
        with self.assertRaises(Forbidden):
            invoice_document(result["id"], _P(stranger))


class CompletedWorkIsPaidInFullTest(_Fixture):
    """Owner, 2026-10-08: "if the activity is completed and evidence uploaded,
    payable become full amount". Finished work was offered at 50% like work
    still to come, and its other half could not be invoiced until that 50%
    had been paid."""

    def setUp(self):
        super().setUp()
        self.partner_p = _P(self.partner_user)
        self.north_p = _P(self.north_lead, self.north_lead_sp)
        self.acct_p = _P(self.accountant)
        self.done = self._visit(self.north_school, 7, 40_000)
        self.coming = self._visit(self.lead_school, 20, 60_000)

    def _complete(self, activity, *, evidence=True, status="ia_verified"):
        activity.status = status
        activity.salesforce_activity_id = f"SF-{activity.id[-6:]}"
        activity.save(update_fields=["status", "salesforce_activity_id"])
        if evidence:
            EvidenceRecord.objects.create(
                activity=activity,
                kind="photo",
                uri=f"{activity.id}.jpg",
                uploaded_by=self.partner_user.id,
            )

    def _lines(self, instalment):
        basis = invoice_basis(self.partner_p, "month", ANCHOR, instalment)
        return {i["activity"].id: i["payable"] for i in basis["items"]}

    def test_completed_with_evidence_is_payable_in_full(self):
        self._complete(self.done)
        self.assertEqual(self._lines("clearance"), {self.done.id: 40_000})

    def test_it_is_no_longer_offered_at_half(self):
        self._complete(self.done)
        self.assertEqual(self._lines("advance"), {self.coming.id: 30_000})

    def test_scheduled_work_stays_at_half_and_is_not_payable_in_full(self):
        self.assertEqual(
            self._lines("advance"), {self.done.id: 20_000, self.coming.id: 30_000}
        )
        self.assertEqual(self._lines("clearance"), {})

    def test_completed_means_verified_with_evidence_on_file(self):
        """What the balance has always required, and what the accountant's
        payment step refuses without."""
        self._complete(self.done, evidence=False)
        self.assertEqual(self._lines("clearance"), {})
        self.assertIn(self.done.id, self._lines("advance"))

        other = self._visit(self.north_school, 9, 50_000)
        self._complete(other, status="awaiting_ia_verification")
        self.assertNotIn(other.id, self._lines("clearance"))

    def test_where_the_half_was_paid_the_rest_is_payable(self):
        first = submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        confirm_invoice(first["id"], self.north_p)
        pay_invoice(first["id"], {"payment_reference": "EFT-1"}, self.acct_p)
        self._complete(self.done)
        self.assertEqual(self._lines("clearance"), {self.done.id: 20_000})

    def test_a_half_still_on_an_unpaid_invoice_is_not_asked_for_twice(self):
        """Its 50% is with the Lead. Invoicing the whole cost beside it would
        ask for 150%, and the second payment would be refused."""
        submit_invoice(self.partner_p, "month", ANCHOR, "advance")
        self._complete(self.done)
        self.assertEqual(self._lines("clearance"), {})

    def test_the_full_amount_is_paid_in_one_payment(self):
        self._complete(self.done)
        result = submit_invoice(self.partner_p, "month", ANCHOR, "clearance")
        invoice = PartnerInvoice.objects.get(id=result["id"])
        self.assertEqual(
            (invoice.system_total, invoice.payable_amount), (40_000, 40_000)
        )
        self.assertEqual(invoice.get_invoice_type_display(), "Completed Work Invoice")
        confirm_invoice(invoice.id, self.north_p)
        paid = pay_invoice(invoice.id, {"payment_reference": "EFT-2"}, self.acct_p)
        self.assertEqual(paid["paid"], 40_000)
        self.done.refresh_from_db()
        self.assertEqual(self.done.payment_status, "paid")
        # Nothing of it is left to invoice, at half or in full.
        self.assertNotIn(self.done.id, self._lines("advance"))
        self.assertNotIn(self.done.id, self._lines("clearance"))


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class InvoicePagesTest(_Fixture):
    """The drawer the partner sends it from, and the page everyone reads."""

    def setUp(self):
        super().setUp()
        self.visit = self._visit(self.north_school, 7, 40_000)
        self._visit(self.south_school, 9, 100_000)

    def test_the_drawer_lists_the_work_by_lead_and_asks_for_no_total(self):
        self.client.force_login(self.partner_user)
        body = self.client.get(
            "/partner/invoices/new?period_kind=month&instalment=advance&anchor=2026-09-10",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn("Nora North", body)
        self.assertIn("Sam South", body)
        self.assertIn("IR School N1", body)
        self.assertNotIn('name="entered_total"', body)
        self.assertNotIn("required accept", body)

    def test_sending_from_the_drawer_raises_the_invoices(self):
        self.client.force_login(self.partner_user)
        response = self.client.post(
            "/partner/invoices",
            {"period_kind": "month", "instalment": "advance", "anchor": "2026-09-10"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PartnerInvoice.objects.count(), 2)
        self.assertIn("2 invoices", response.content.decode())

    def test_the_invoice_page_opens_for_the_partner_and_its_lead(self):
        result = submit_invoice(_P(self.partner_user), "month", ANCHOR, "advance")
        north = PartnerInvoice.objects.get(program_lead_staff_id=self.north_lead_sp.id)
        self.assertIn(north.id, [i["id"] for i in result["invoices"]])
        url = f"/partner-invoices/{north.id}"

        self.client.force_login(self.partner_user)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("Programme Lead: Nora North", body)
        self.assertIn("IR School N1", body)
        self.assertNotIn("IR School S1", body)

        self.client.force_login(self.north_lead)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.south_lead)
        self.assertEqual(self.client.get(url).status_code, 403)
