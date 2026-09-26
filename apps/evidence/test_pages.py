"""One evidence form from several pages (owner, 2026-09-26).

"Sometimes the attendance form has many pages. Allow multiple uploads and
merge them into one file with those pages and render as one file with many
pages (only the pages uploaded)."

The contract: the pages are joined in the order they were added, each photo
becomes exactly one upright A4 page and each PDF contributes exactly its own
pages — nothing is added. Every page passes the same gates as a single upload
(type, size, malware scan) before anything is stored, and one file still
takes the single-file path unchanged.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image
from pypdf import PdfReader, PdfWriter

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.core.private_storage import open_file
from apps.evidence import pages, services
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()

IN_MEMORY_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "private_uploads": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def photo(name="page.jpg", size=(600, 800), fmt="JPEG", content_type="image/jpeg"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color=(200, 200, 200)).save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def pdf(name="scan.pdf", count=2, password=None):
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=595, height=842)
    if password:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/pdf")


def page_sizes(data: bytes) -> list[tuple[int, int]]:
    return [
        (round(float(p.mediabox.width)), round(float(p.mediabox.height)))
        for p in PdfReader(io.BytesIO(data)).pages
    ]


class MergePagesTest(SimpleTestCase):
    def test_each_photo_is_one_a4_page_in_the_order_added(self):
        data, count = pages.merge_pages(
            [photo("p1.jpg", (600, 800)), photo("p2.jpg", (900, 500))]
        )
        self.assertEqual(count, 2)
        # A4 at 150 DPI is 595 x 842 points; the wide photo is a landscape page.
        self.assertEqual(page_sizes(data), [(595, 842), (842, 595)])

    def test_a_pdf_brings_exactly_its_own_pages(self):
        data, count = pages.merge_pages(
            [
                photo("cover.jpg"),
                pdf("register.pdf", count=3),
                photo("last.png", fmt="PNG"),
            ]
        )
        self.assertEqual(count, 5)
        self.assertEqual(len(PdfReader(io.BytesIO(data)).pages), 5)

    def test_more_than_the_page_limit_is_refused(self):
        with self.assertRaisesMessage(BadRequest, f"at most {pages.MAX_PAGES} pages"):
            pages.merge_pages([pdf(count=pages.MAX_PAGES), photo()])

    def test_a_password_protected_pdf_is_refused(self):
        with self.assertRaisesMessage(BadRequest, "password-protected"):
            pages.merge_pages([photo(), pdf(password="secret")])

    def test_a_file_that_is_not_a_photo_is_refused(self):
        broken = SimpleUploadedFile(
            "page.jpg", b"not an image", content_type="image/jpeg"
        )
        with self.assertRaisesMessage(BadRequest, "could not be read as a photo"):
            pages.merge_pages([photo(), broken])

    def test_a_sideways_camera_photo_is_turned_upright(self):
        """Phones store portrait shots landscape with an EXIF rotation."""
        buffer = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90° clockwise to display
        Image.new("RGB", (900, 500)).save(buffer, "JPEG", exif=exif)
        upload = SimpleUploadedFile(
            "cam.jpg", buffer.getvalue(), content_type="image/jpeg"
        )
        data, _ = pages.merge_pages([upload, photo()])
        self.assertEqual(page_sizes(data)[0], (595, 842))


@override_settings(STORAGES=IN_MEMORY_STORAGES, CLAMAV_HOST=None)
class RecordPagesUploadTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            id="cceo-pages-test",
            email="cceo-pages@edify.org",
            name="Pages CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id="staff-pages-test", user=self.user, title="CCEO"
        )
        region = Region.objects.create(name="Pages Region")
        district = District.objects.create(name="Pages District", region=region)
        self.school = School.objects.create(
            name="Pages School", region=region, district=district
        )
        StaffSchoolAssignment.objects.create(staff=profile, school_id=self.school.id)
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="in_progress",
            responsible_staff_id=self.user.staff_profile_id,
            salesforce_activity_id="SVE-PAGES-001",
        )

    def _upload(self, files, kind="visit_form"):
        return services.record_pages_upload(
            principal=self.user, activity_id=self.activity.id, kind=kind, files=files
        )

    def test_several_pages_are_stored_as_one_pdf_with_those_pages(self):
        result = self._upload([photo("p1.jpg"), photo("p2.jpg"), pdf(count=1)])
        record = EvidenceRecord.objects.get(id=result["id"])
        self.assertEqual(
            EvidenceRecord.objects.filter(activity=self.activity).count(), 1
        )
        self.assertEqual(record.kind, "visit_form")
        self.assertEqual(record.original_name, "Visit Form (3 pages).pdf")
        self.assertEqual(record.file_extension, ".pdf")
        with open_file(services.EVIDENCE_NAMESPACE, record.uri) as stored:
            self.assertEqual(len(PdfReader(io.BytesIO(stored.read())).pages), 3)

    def test_one_file_takes_the_single_upload_path_unchanged(self):
        result = self._upload([pdf("visit.pdf", count=2)])
        record = EvidenceRecord.objects.get(id=result["id"])
        self.assertEqual(record.original_name, "visit.pdf")

    def test_a_page_that_is_not_a_pdf_or_photo_is_refused(self):
        sheet = SimpleUploadedFile(
            "register.csv", b"name,school\nA,B\n", content_type="text/csv"
        )
        with self.assertRaisesMessage(BadRequest, "each page must be a PDF or a photo"):
            self._upload([photo(), sheet])
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.activity).exists())

    def test_an_infected_page_rejects_the_whole_upload_before_anything_is_stored(self):
        verdicts = iter([("clean", None), ("infected", "Eicar-Test-Signature")])
        with patch.object(
            services, "_scan_upload", side_effect=lambda _path: next(verdicts)
        ):
            with self.assertRaisesMessage(BadRequest, "flagged as a security threat"):
                self._upload([photo("p1.jpg"), photo("p2.jpg")])
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.activity).exists())

    def test_too_many_files_are_refused(self):
        with self.assertRaisesMessage(BadRequest, f"at most {pages.MAX_PAGES} pages"):
            self._upload([photo(f"p{i}.jpg") for i in range(pages.MAX_PAGES + 1)])

    def test_the_evidence_drawer_posts_every_page_as_one_form(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/activities/{self.activity.id}/evidence/action",
            {"evidence_file_visit_form": [photo("p1.jpg"), photo("p2.jpg")]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = EvidenceRecord.objects.get(activity=self.activity)
        self.assertEqual(record.kind, "visit_form")
        self.assertEqual(record.original_name, "Visit Form (2 pages).pdf")

    def test_the_evidence_drawer_offers_camera_and_several_files(self):
        self.client.force_login(self.user)
        html = self.client.get(
            f"/activities/{self.activity.id}/evidence"
        ).content.decode()
        self.assertIn("async add(event)", html)
        self.assertIn('capture="environment"', html)
        self.assertIn("Take photo", html)
        self.assertIn("Choose files", html)
        main = html.split('name="evidence_file_visit_form"', 1)[1].split(">", 1)[0]
        self.assertIn("multiple", main)
