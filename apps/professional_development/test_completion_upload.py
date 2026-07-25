"""Proof of course completion: a certificate or a transcript.

The model, the storage helper and the route all existed; nothing in the
interface ever called them, so the page told people a certificate was required
and gave them no way to provide one. These tests cover the control that closes
that gap, and the rules it must not be able to talk its way around.
"""

from __future__ import annotations

import datetime as dt

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.core.fy import get_operational_fy
from apps.professional_development.completion_service import PDCourseTrackingService
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentRequest,
)

# A minimal but genuinely PDF-shaped file: the platform's upload validation
# checks magic bytes, not just the extension.
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def _pdf(name="certificate.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


class CompletionUploadTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="learner@pd.test",
            password="password123",
            name="Lena Learner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        self.request = ProfessionalDevelopmentRequest.objects.create(
            staff_id=self.staff.id,
            staff_name=self.user.name,
            course_name="Instructional Leadership",
            course_category="leadership",
            fy=get_operational_fy(),
            requested_amount_cents=100_00,
            status=PDStatus.MARKED_COMPLETE,
            start_date=dt.date(2026, 1, 5),
            end_date=dt.date(2026, 3, 5),
        )

    def test_a_certificate_can_be_uploaded_once_the_course_is_complete(self):
        cert = PDCourseTrackingService.upload_certificate(
            self.request.id, self.user, _pdf()
        )
        self.assertEqual(cert.document_type, "certificate")
        self.assertEqual(cert.original_name, "certificate.pdf")
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, PDStatus.CERTIFICATE_UPLOADED)

    def test_a_transcript_is_recorded_as_a_transcript(self):
        """Some providers issue one and not the other; HR should not have to
        infer which arrived from the filename."""
        cert = PDCourseTrackingService.upload_certificate(
            self.request.id,
            self.user,
            _pdf("results.pdf"),
            document_type="transcript",
        )
        self.assertEqual(cert.document_type, "transcript")
        self.assertEqual(cert.get_document_type_display(), "Transcript")

    def test_an_unknown_document_type_is_refused(self):
        with self.assertRaises(BadRequest):
            PDCourseTrackingService.upload_certificate(
                self.request.id, self.user, _pdf(), document_type="diploma"
            )

    def test_upload_is_refused_before_the_course_is_marked_complete(self):
        self.request.status = PDStatus.IN_PROGRESS
        self.request.save(update_fields=["status"])
        with self.assertRaises(BadRequest):
            PDCourseTrackingService.upload_certificate(
                self.request.id, self.user, _pdf()
            )

    def test_a_second_document_can_be_added(self):
        """A certificate and a transcript are not mutually exclusive, and a
        returned upload has to be replaceable."""
        PDCourseTrackingService.upload_certificate(self.request.id, self.user, _pdf())
        PDCourseTrackingService.upload_certificate(
            self.request.id, self.user, _pdf("t.pdf"), document_type="transcript"
        )
        self.assertEqual(self.request.certificates.count(), 2)

    def test_someone_else_cannot_upload_against_your_course(self):
        other = User.objects.create_user(
            email="other@pd.test",
            password="password123",
            name="Otto Other",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=other, title="CCEO")
        with self.assertRaises(Exception):
            PDCourseTrackingService.upload_certificate(self.request.id, other, _pdf())


class CompletionUploadSurfaceTest(TestCase):
    """The control has to actually appear, or the backend may as well not
    exist — which was the situation this replaced."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="surface@pd.test",
            password="password123",
            name="Sam Surface",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        self.client = Client()
        self.client.force_login(self.user)

    def _request(self, status):
        return ProfessionalDevelopmentRequest.objects.create(
            staff_id=self.staff.id,
            staff_name=self.user.name,
            course_name="Coaching Skills",
            course_category="leadership",
            fy=get_operational_fy(),
            requested_amount_cents=50_00,
            status=status,
            start_date=dt.date(2026, 2, 1),
            end_date=dt.date(2026, 4, 1),
        )

    def test_the_upload_appears_once_the_course_is_complete(self):
        self._request(PDStatus.MARKED_COMPLETE)
        response = self.client.get("/my-professional-development")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Proof of completion", body)
        self.assertIn('name="file"', body)
        self.assertIn('name="document_type"', body)

    def test_it_stays_hidden_while_the_course_is_still_running(self):
        """Offering an action the service would refuse is worse than not
        offering it."""
        self._request(PDStatus.IN_PROGRESS)
        body = self.client.get("/my-professional-development").content.decode()
        self.assertNotIn("Proof of completion", body)
