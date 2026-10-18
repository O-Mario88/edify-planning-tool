"""The Staff Development Fund (owner, 2026-10-18).

* The request is the Staff Development Fund request form: its boxes, its
  attachment, and its four signatures — the manager, the Regional HRD, the
  Country Director and Accounting. The Country Director signs after HR; a
  Director's own request is signed by the Regional Vice President.
* A completed form is a PDF drawn as the paper form's first page.
* Table 2b lists every eligible staff member: Country, Staff Name, Staff Role,
  Allocation in USD, Status, Certificate and an Action.
* HR, the Country Director and the staff member's Programme Lead can view and
  download a certificate as a PDF, whatever it was uploaded as.
"""

from __future__ import annotations

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.hr_dashboard_service import (
    CERT_AWAITING,
    CERT_NONE,
    CERT_ON_BAMBOOHR,
    CERT_UPLOADED,
    FUND_APPLIED,
    FUND_COMPLETED,
    FUND_NOT_APPLIED,
    FUND_PROCESSING,
    HRPDDashboardService,
)
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentCertificate,
    ProfessionalDevelopmentRequest,
)
from apps.professional_development.sdf_form import render_pdf, sheet
from apps.professional_development.tests import FY, PDTestBase


def _client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


class CountryDirectorSignsTest(PDTestBase):
    def _at_hr(self, user=None, **fields):
        req = self._draft(
            user or self.cceo,
            funding_type="fully_funded",
            requested_amount_cents=200_00,
            course_fee_cents=200_00,
            **fields,
        )
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save()
        return req

    def test_hr_hands_the_request_to_the_country_director(self):
        req = self._at_hr()
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_CD)
        self.assertFalse(hasattr(req, "fund_request"))
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.hr))

    def test_the_directors_signature_releases_the_funding(self):
        req = self._at_hr()
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        PDApprovalRoutingService.cd_approve(req.id, self.cd, note="Go ahead")
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.APPROVED_PENDING_FUNDING)
        self.assertEqual(req.cd_reviewed_by, self.cd.id)
        self.assertTrue(req.cd_reviewed_at)
        self.assertTrue(hasattr(req, "fund_request"))
        self.assertTrue(req.calendar_block_id)

    def test_only_the_director_signs_and_a_denial_needs_its_reason(self):
        req = self._at_hr()
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        for outsider in (self.hr, self.pl, self.accountant):
            with self.subTest(role=outsider.active_role):
                with self.assertRaises(Forbidden):
                    PDApprovalRoutingService.cd_approve(req.id, outsider)
        with self.assertRaises(BadRequest):
            PDApprovalRoutingService.cd_reject(req.id, self.cd, "")
        PDApprovalRoutingService.cd_reject(
            req.id, self.cd, "The source of funding is not available"
        )
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.REJECTED)
        self.assertEqual(sheet(req)["decision"], "denied")

    def test_a_directors_own_request_is_signed_by_the_rvp(self):
        req = self._at_hr(self.cd)
        PDApprovalRoutingService.hr_approve(req.id, self.hr)
        req.refresh_from_db()
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.cd))
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.rvp))
        PDApprovalRoutingService.cd_approve(req.id, self.rvp)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.APPROVED_PENDING_FUNDING)


class TheFormTest(PDTestBase):
    def test_the_form_posts_its_boxes_and_its_attachments(self):
        response = _client(self.cceo).post(
            "/my-professional-development/request",
            {
                "intent": "submit",
                "purpose": "Professional Development",
                "start_date": "2026-09-14",
                "end_date": "2027-09-14",
                "duration": "Year",
                "course_name": "Platform Administrator Exam-Ready Bundle",
                "relevance_to_role": "I can build the reports teams need.",
                "approximate_cost": "219.12",
                "requested_currency": "UGX",
                "requested_amount": "943,688.50",
                "fy": FY,
                "programme_file": SimpleUploadedFile(
                    "programme.pdf", b"%PDF-1.4\n" + b"x" * 64, "application/pdf"
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        req = ProfessionalDevelopmentRequest.objects.get(staff_id=self.cceo_sp.id)
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertEqual(req.duration, "Year")
        # The allocation is in USD: the approximate cost is what counts.
        self.assertEqual(req.total_cost_cents, 21912)
        self.assertEqual(req.requested_amount_cents, 21912)
        self.assertEqual(req.requested_local_currency, "UGX")
        self.assertEqual(req.requested_local_amount_cents, 94368850)
        self.assertTrue(req.evidence_files.filter(kind="programme").exists())
        boxes = sheet(req)
        self.assertEqual(boxes["approximate_cost"], "$219.12")
        self.assertEqual(boxes["amount_requested"], "UGX 943,688.50")
        self.assertEqual(boxes["manager"], "Pat Lead")

    def test_the_drawer_draws_the_form(self):
        body = _client(self.cceo).get("/my-professional-development/request")
        body = body.content.decode()
        for text in (
            "STAFF DEVELOPMENT FUND REQUEST FORM",
            "Purpose for Which Funding is Sought",
            "How will this course impact your work in Edify?",
            "What Fiscal Year are the Funds budgeted for?",
            "Office Use Only",
            "Country Director Signature:",
            "Accounting Autorization:",
        ):
            with self.subTest(text=text):
                self.assertIn(text, body)

    def test_the_completed_form_is_a_one_page_pdf_for_who_may_read_it(self):
        req = self._draft(self.cceo, supervisor_note="Approved to proceed")
        req.status = PDStatus.SUBMITTED_TO_HR
        req.supervisor_reviewed_by = self.pl.id
        req.supervisor_reviewed_at = timezone.now()
        req.save()
        data = render_pdf(req)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(data.count(b"/Type /Page\n"), 1)
        self.assertEqual(sheet(req)["manager_signature"].name, "Pat Lead")
        self.assertTrue(sheet(req)["manager_signature"].signed)
        url = f"/my-professional-development/request/{req.id}/form.pdf"
        for reader in (self.cceo, self.pl, self.hr, self.cd):
            with self.subTest(reader=reader.name):
                response = _client(reader).get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
        stranger, _ = self._staff("x@pd.org", "Stranger", "CCEO")
        self.assertEqual(_client(stranger).get(url).status_code, 404)


class CertificateAsPdfTest(PDTestBase):
    def _certificate(self, data, mime, name):
        from apps.core.private_storage import save_file
        from apps.professional_development.uploads import PD_NAMESPACE

        req = self._draft(self.cceo, status=PDStatus.CERTIFICATE_UPLOADED)
        stored = f"{req.id}{name[name.rfind('.') :]}"
        save_file(PD_NAMESPACE, stored, BytesIO(data))
        return ProfessionalDevelopmentCertificate.objects.create(
            request=req,
            uri=stored,
            original_name=name,
            mime_type=mime,
            uploaded_by=self.cceo.id,
        )

    def test_a_photographed_certificate_downloads_as_a_pdf(self):
        from PIL import Image

        image = BytesIO()
        Image.new("RGB", (600, 400), (240, 240, 240)).save(image, format="PNG")
        cert = self._certificate(image.getvalue(), "image/png", "certificate.png")
        url = f"/my-professional-development/certificate/{cert.id}/pdf?download=1"
        for reader in (self.hr, self.cd, self.pl):
            with self.subTest(reader=reader.name):
                response = _client(reader).get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertTrue(response.content.startswith(b"%PDF"))
                self.assertIn("attachment", response["Content-Disposition"])
                self.assertIn("certificate.pdf", response["Content-Disposition"])

    def test_a_pdf_certificate_is_served_as_it_was_uploaded(self):
        data = b"%PDF-1.4\n" + b"y" * 64
        cert = self._certificate(data, "application/pdf", "cert.pdf")
        response = _client(self.hr).get(
            f"/my-professional-development/certificate/{cert.id}/pdf"
        )
        self.assertEqual(response.content, data)


class FundTableTest(PDTestBase):
    def _rows(self):
        return {
            row["staff_id"]: row
            for row in HRPDDashboardService.staff_fund_rows(self.hr, FY)
        }

    def test_every_eligible_person_with_their_status_and_certificate(self):
        self._allocate(self.cceo, 500_00)
        submitted = self._draft(self.pl, status=PDStatus.SUBMITTED_TO_SUPERVISOR)
        self._draft(self.accountant, status=PDStatus.REJECTED)
        processing = self._draft(self.cd, status=PDStatus.DISBURSED)
        done = self._draft(self.rvp, status=PDStatus.MARKED_COMPLETE)
        rows = self._rows()

        cceo = rows[self.cceo_sp.id]
        self.assertEqual(
            (cceo["country"], cceo["role"], cceo["allocation"]),
            ("Uganda", "CCEO", "USD 500"),
        )
        self.assertEqual(
            (cceo["status"], cceo["certificate"]), (FUND_NOT_APPLIED, CERT_NONE)
        )
        self.assertEqual(cceo["reminder"]["action"], "send_apply_reminder")
        self.assertEqual(rows[self.pl_sp.id]["status"], FUND_APPLIED)
        self.assertEqual(rows[self.pl_sp.id]["request_id"], submitted.id)
        # A rejected request leaves its owner free to apply again.
        self.assertEqual(rows[self.acct_sp.id]["status"], FUND_NOT_APPLIED)
        self.assertEqual(rows[self.cd_sp.id]["status"], FUND_PROCESSING)
        self.assertEqual(rows[self.cd_sp.id]["request_id"], processing.id)
        rvp = rows[self.rvp_sp.id]
        self.assertEqual(
            (rvp["status"], rvp["certificate"]), (FUND_COMPLETED, CERT_AWAITING)
        )
        self.assertEqual(rvp["reminder"]["label"], "Remind: Certificate")
        # Not Applied first.
        ordered = HRPDDashboardService.staff_fund_rows(self.hr, FY)
        self.assertEqual(ordered[0]["status"], FUND_NOT_APPLIED)

        ProfessionalDevelopmentCertificate.objects.create(
            request=done, uri="c.pdf", original_name="c.pdf", uploaded_by=self.rvp.id
        )
        self.assertEqual(self._rows()[self.rvp_sp.id]["certificate"], CERT_UPLOADED)
        done.status = PDStatus.BAMBOOHR_CONFIRMED
        done.save()
        self.assertEqual(self._rows()[self.rvp_sp.id]["certificate"], CERT_ON_BAMBOOHR)

    def test_the_table_is_drawn_with_its_columns(self):
        body = _client(self.hr).get(f"/cpd-learning?fy={FY}").content.decode()
        for column in (
            "Country",
            "Staff Name",
            "Staff Role",
            "Allocation (USD)",
            "Status",
            "Certificate",
            "Action",
        ):
            with self.subTest(column=column):
                self.assertIn(f">{column}</th>", body)
        self.assertIn("2b. Staff Development Fund", body)
        self.assertIn("Remind to Apply", body)
