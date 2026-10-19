"""A partner's form is one document, opened as one PDF (owner, 2026-10-14).

"it displays list of all the uploads even if the same document is uploaded 3
tines it will display all the 3. can you fix it to show only one upload ...
if many pages, combine them all into one single PDF file with many pages. and
from the verifiers side, no need to show the uploaded image, just use the
link View Uploaded {visit form} or {Training attendance} in a beautiful
button which allow them to click and open the upload in PDF which can be
downloaded."

The upload drawer's own behaviour (the question, the pages joined, the same
file refused) is in apps/frontend/test_evidence_drawer_submit.py; this file
holds the address a reader opens the form through, what it answers for work
uploaded before one document was the rule, and the API's upload door.
"""

from __future__ import annotations

import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from pypdf import PdfReader
from rest_framework.test import APIClient

from apps.core.private_storage import save_file
from apps.evidence import form_document
from apps.evidence.models import EvidenceRecord
from apps.evidence.services import EVIDENCE_NAMESPACE
from apps.frontend.test_evidence_drawer_submit import (
    IN_MEMORY_STORAGES,
    UploadFixture,
    photo,
)


def pdf(pages: int = 1, mark: str = "a") -> bytes:
    """A small real PDF with this many blank pages."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": mark})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@override_settings(STORAGES=IN_MEMORY_STORAGES, CLAMAV_HOST=None)
class FormDocumentTest(UploadFixture):
    def _record(self, activity, name: str, data: bytes, *, kind="visit_form", **extra):
        """A record as an older upload left it: its own row and its own file."""
        extension = "." + name.rsplit(".", 1)[-1]
        stored = f"{uuid.uuid4().hex}{extension}"
        save_file(EVIDENCE_NAMESPACE, stored, io.BytesIO(data))
        return EvidenceRecord.objects.create(
            activity=activity,
            kind=kind,
            uri=stored,
            original_name=name,
            mime_type="application/pdf" if extension == ".pdf" else "image/jpeg",
            file_extension=extension,
            file_size=len(data),
            uploaded_by=self.partner_user.id,
            **extra,
        )

    def _open(self, user, activity, **params):
        self.client.force_login(user)
        return self.client.get(f"/api/evidence/activity/{activity.id}/form", params)

    def _pages(self, response) -> int:
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response["Content-Type"], "application/pdf")
        return len(PdfReader(io.BytesIO(response.content)).pages)

    # -- what the button is ----------------------------------------------------

    def test_the_button_names_the_form_the_activity_is_verified_from(self):
        self.assertIsNone(form_document.uploaded_form(self.partner_visit))
        self._record(self.partner_visit, "visit.pdf", pdf())
        self.assertEqual(
            form_document.uploaded_form(self.partner_visit),
            {
                "kind": "visit_form",
                "name": "Visit Form",
                "label": "View Uploaded Visit Form",
                "url": f"/api/evidence/activity/{self.partner_visit.id}/form",
            },
        )
        self.partner_visit.activity_type = "cluster_training"
        self.assertEqual(
            form_document.form_name(self.partner_visit), "Training Attendance"
        )

    # -- one PDF, whatever was uploaded -----------------------------------------

    def test_one_pdf_is_answered_as_it_is(self):
        data = pdf(pages=3)
        self._record(self.partner_visit, "visit.pdf", data)
        response = self._open(self.cceo, self.partner_visit)
        self.assertEqual(self._pages(response), 3)
        self.assertEqual(response.content, data)
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn("Visit Form - EDS School.pdf", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_it_may_be_framed_by_this_site_and_no_other_address_may(self):
        """The popup holds it in a frame (owner, 2026-10-14: "make the pdf
        upload view a popup with download button"); a single file's own
        address stays unframeable."""
        record = self._record(self.partner_visit, "visit.pdf", pdf())
        response = self._open(self.cceo, self.partner_visit)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(
            response["Content-Security-Policy"],
            "default-src 'none'; frame-ancestors 'self'",
        )
        single = self.client.get(f"/api/evidence/{record.id}/file")
        self.assertEqual(single.status_code, 200)
        self.assertEqual(single["X-Frame-Options"], "DENY")

    def test_the_popup_shows_the_pdf_with_download_and_close(self):
        from django.template.loader import render_to_string

        self._record(self.partner_visit, "visit.pdf", pdf())
        html = render_to_string(
            "components/uploaded_form_link.html",
            {"form": form_document.uploaded_form(self.partner_visit)},
        )
        address = f"/api/evidence/activity/{self.partner_visit.id}/form"
        self.assertIn("<dialog", html)
        self.assertIn("View Uploaded Visit Form</span>", html)
        self.assertIn(f"$refs.frame.src = '{address}'", html)
        self.assertIn(f'href="{address}?download=1"', html)
        self.assertIn("<iframe", html)
        # The frame has no address until the popup opens: a page of rows
        # does not fetch a PDF per row.
        self.assertNotRegex(html, r"<iframe[^>]*\ssrc=")
        self.assertIn("This device cannot show a PDF inside the page", html)
        self.assertNotIn('type="submit"', html)
        self.assertNotIn("<form", html)

    def test_it_can_be_downloaded(self):
        self._record(self.partner_visit, "visit.pdf", pdf())
        response = self._open(self.cceo, self.partner_visit, download="1")
        self.assertIn("attachment", response["Content-Disposition"])

    def test_the_same_document_uploaded_three_times_is_read_once(self):
        data = pdf(pages=2)
        for _ in range(3):
            self._record(self.partner_visit, "visit.pdf", data)
        self.assertEqual(
            EvidenceRecord.objects.filter(activity=self.partner_visit).count(), 3
        )
        self.assertEqual(self._pages(self._open(self.cceo, self.partner_visit)), 2)

    def test_pages_uploaded_one_at_a_time_are_read_as_one_pdf_in_order(self):
        self._record(self.partner_visit, "page-1.jpg", photo("p1.jpg", 200).read())
        self._record(self.partner_visit, "pages-2-3.pdf", pdf(pages=2))
        self._record(self.partner_visit, "page-1.jpg", photo("p1.jpg", 200).read())
        self.assertEqual(self._pages(self._open(self.cceo, self.partner_visit)), 3)

    def test_a_photo_is_read_as_a_pdf(self):
        self._record(self.partner_visit, "page.jpg", photo("page.jpg", 150).read())
        self.assertEqual(self._pages(self._open(self.cceo, self.partner_visit)), 1)

    def test_a_quarantined_file_is_not_part_of_the_form(self):
        self._record(self.partner_visit, "visit.pdf", pdf(pages=1))
        self._record(
            self.partner_visit, "bad.pdf", pdf(pages=4, mark="b"), quarantined=True
        )
        self.assertEqual(self._pages(self._open(self.cceo, self.partner_visit)), 1)

    def test_older_uploads_filed_as_a_photo_are_still_the_form(self):
        """A file that is there is never reported missing."""
        self._record(
            self.partner_visit, "snap.jpg", photo("s.jpg", 99).read(), kind="photo"
        )
        self.assertEqual(
            form_document.uploaded_form(self.partner_visit)["label"],
            "View Uploaded Visit Form",
        )
        self.assertEqual(self._pages(self._open(self.cceo, self.partner_visit)), 1)

    def test_nothing_uploaded_is_not_found(self):
        self.assertEqual(self._open(self.cceo, self.partner_visit).status_code, 404)

    def test_it_is_read_only_by_someone_who_may_read_the_activity(self):
        from django.contrib.auth import get_user_model

        self._record(self.partner_visit, "visit.pdf", pdf())
        stranger = get_user_model().objects.create(
            id="eds-stranger",
            email="eds-stranger@edify.org",
            name="EDS Stranger",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        self.assertEqual(
            self._open(self.partner_user, self.partner_visit).status_code, 200
        )
        self.assertIn(self._open(stranger, self.partner_visit).status_code, (403, 404))

    # -- the API's upload door ----------------------------------------------------

    def _api_upload(self, user, activity, upload, **extra):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(
            "/api/evidence/upload",
            {"activityId": activity.id, "kind": "visit_form", "file": upload, **extra},
            format="multipart",
        )

    def test_the_api_takes_a_partners_form_once_and_then_only_another_page(self):
        first = self._api_upload(
            self.partner_user, self.partner_visit, photo("p1.jpg", 200)
        )
        self.assertEqual(first.status_code, 201, first.content)
        again = self._api_upload(
            self.partner_user, self.partner_visit, photo("p2.jpg", 80)
        )
        self.assertEqual(again.status_code, 400)
        self.assertIn(b"already uploaded", again.content)
        page = self._api_upload(
            self.partner_user,
            self.partner_visit,
            photo("p2.jpg", 80),
            anotherPage="yes",
        )
        self.assertEqual(page.status_code, 201, page.content)
        self.assertEqual(page.json()["pages"], 2)
        self.assertEqual(
            EvidenceRecord.objects.filter(activity=self.partner_visit).count(), 1
        )

    def test_the_api_takes_no_upload_for_staff_work(self):
        response = self._api_upload(
            self.cceo,
            self.visit,
            SimpleUploadedFile("visit.pdf", pdf(), content_type="application/pdf"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No form is uploaded for it", response.content)
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.visit).exists())
