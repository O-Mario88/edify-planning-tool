"""§6-mandated evidence-pipeline tests added by the 2026-07-15 full-platform
audit. Covers the gates the verification pass found CODE-ONLY or defective:
upload validation rejections, original-file preservation, image→PDF and
office→PDF renditions, permission denial (including the Accountant's
finance-only scope), oversized files, and corrupted-PDF rejection.
"""

import io
import os

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.evidence import services
from apps.evidence.models import EvidenceRecord
from apps.evidence.validation import MAX_FILE_SIZE
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


# Minimal real JPEG header + body so both the magic-byte sniff and Pillow work.
def _tiny_jpeg_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


_PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"


class _EvidenceTestBase(TestCase):
    def setUp(self):
        self.cceo = User.objects.create(
            id="cceo-evpipe",
            email="cceo-evpipe@edify.org",
            name="Pipeline CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo.set_password("pass123")
        self.cceo.save()
        profile = StaffProfile.objects.create(
            id="staff-evpipe", user=self.cceo, title="CCEO"
        )
        region = Region.objects.create(name="EvPipe Region")
        district = District.objects.create(name="EvPipe District", region=region)
        self.school = School.objects.create(
            name="EvPipe School", region=region, district=district
        )
        StaffSchoolAssignment.objects.create(staff=profile, school_id=self.school.id)
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="in_progress",
            responsible_staff_id=self.cceo.staff_profile_id,
        )

    def _upload(self, name, content, content_type, user=None, kind="photo"):
        return services.record_upload(
            principal=user or self.cceo,
            activity_id=self.activity.id,
            kind=kind,
            file_obj=SimpleUploadedFile(name, content, content_type=content_type),
        )


class UploadValidationRejectionTest(_EvidenceTestBase):
    def test_blocked_extension_rejected(self):
        with self.assertRaises(BadRequest):
            self._upload("payload.svg", b"<svg></svg>", "image/svg+xml")

    def test_extension_mime_mismatch_rejected(self):
        with self.assertRaises(BadRequest):
            self._upload("photo.jpg", _tiny_jpeg_bytes(), "application/pdf")

    def test_magic_byte_mismatch_rejected(self):
        # Declared and named as JPEG, but the bytes are not a JPEG.
        with self.assertRaises(BadRequest):
            self._upload("photo.jpg", b"not-actually-a-jpeg", "image/jpeg")

    def test_corrupted_pdf_rejected(self):
        # .pdf name + PDF MIME but no %PDF magic bytes.
        with self.assertRaises(BadRequest):
            self._upload("report.pdf", b"garbage-not-pdf", "application/pdf")

    def test_oversized_file_rejected(self):
        big = b"\xff\xd8\xff" + b"0" * (MAX_FILE_SIZE + 1)
        with self.assertRaises(BadRequest):
            self._upload("huge.jpg", big, "image/jpeg")

    def test_valid_pdf_accepted(self):
        result = self._upload("report.pdf", _PDF_BYTES, "application/pdf")
        record = EvidenceRecord.objects.get(id=result["id"])
        self.assertEqual(record.preview_status, "ready")
        self.assertEqual(record.file_extension, ".pdf")


class RenditionTest(_EvidenceTestBase):
    def test_image_gets_pdf_rendition_and_original_preserved(self):
        result = self._upload("photo.jpg", _tiny_jpeg_bytes(), "image/jpeg")
        record = EvidenceRecord.objects.get(id=result["id"])
        original_path = os.path.join(services.evidence_dir(), record.uri)
        original_bytes = open(original_path, "rb").read()

        out = services.prepare_inline_view(record.id, self.cceo)
        record.refresh_from_db()
        self.assertEqual(out["previewStatus"], "ready")
        self.assertEqual(out["viewKind"], "pdf_rendition")
        self.assertTrue(record.pdf_rendition_storage_key)
        rendition_path = os.path.join(
            services.evidence_dir(), record.pdf_rendition_storage_key
        )
        self.assertTrue(os.path.exists(rendition_path))
        self.assertTrue(open(rendition_path, "rb").read().startswith(b"%PDF"))
        # The original is untouched — same path, same bytes.
        self.assertEqual(open(original_path, "rb").read(), original_bytes)

    def test_office_conversion_tool_missing_fails_gracefully(self):
        from unittest.mock import patch

        result = self._upload(
            "notes.docx",
            b"PK\x03\x04fakedocxzip",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        record = EvidenceRecord.objects.get(id=result["id"])
        with patch("shutil.which", return_value=None):
            out = services.prepare_inline_view(record.id, self.cceo)
        record.refresh_from_db()
        self.assertNotEqual(out["viewKind"], "pdf_rendition")
        self.assertEqual(record.preview_status, "failed")
        self.assertIn("LibreOffice", record.pdf_rendition_error)


class EvidenceAccessScopeTest(_EvidenceTestBase):
    def _make_user(self, email, role):
        u = User.objects.create(
            id=f"u-{email.split('@')[0]}",
            email=email,
            name=email,
            roles=[role],
            active_role=role,
            is_active=True,
        )
        u.set_password("pass123")
        u.save()
        return u

    def test_unrelated_field_staff_denied(self):
        other = self._make_user("other-cceo-evpipe@edify.org", "CCEO")
        StaffProfile.objects.create(id="staff-other-evpipe", user=other, title="CCEO")
        self._upload("photo.jpg", _tiny_jpeg_bytes(), "image/jpeg")
        record = EvidenceRecord.objects.get(activity=self.activity)
        with self.assertRaises(Forbidden):
            services.file_for(record.id, other)

    def test_accountant_denied_on_unfunded_activity(self):
        accountant = self._make_user("acct-evpipe@edify.org", "Accountant")
        self._upload("photo.jpg", _tiny_jpeg_bytes(), "image/jpeg")
        record = EvidenceRecord.objects.get(activity=self.activity)
        # No advances, payment_status untouched -> no financial involvement.
        with self.assertRaises(Forbidden):
            services.file_for(record.id, accountant)

    def test_accountant_allowed_once_activity_is_funded(self):
        accountant = self._make_user("acct2-evpipe@edify.org", "Accountant")
        self.activity.payment_status = "disbursed"
        self.activity.save(update_fields=["payment_status"])
        self._upload("photo.jpg", _tiny_jpeg_bytes(), "image/jpeg")
        record = EvidenceRecord.objects.get(activity=self.activity)
        response = services.file_for(record.id, accountant)
        self.assertEqual(response.status_code, 200)

    def test_ia_country_scope_allowed(self):
        ia = self._make_user("ia-evpipe@edify.org", "ImpactAssessment")
        self._upload("photo.jpg", _tiny_jpeg_bytes(), "image/jpeg")
        record = EvidenceRecord.objects.get(activity=self.activity)
        response = services.file_for(record.id, ia)
        self.assertEqual(response.status_code, 200)
