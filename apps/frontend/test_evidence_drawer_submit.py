"""The upload drawer: a partner's form, one document, one Submit.

Owner, 2026-09-26: "Partner evidence upload should only have upload, not the
Salesforce field. The staff can complete the Salesforce side ... the Done
button on the upload drawer should be Submit."

Owner, 2026-10-13 and 2026-10-14: staff no longer upload ("use strictly visit
ID and training IDs to complete the activities"), and "partners HAVE to upload
because that is how we verify their work". So the drawer is the partner's
alone, and the form it takes is ONE document: "ask the partner if it is a
different page from the one they have uploaded if they say yes then allow if
they say no then reject the second upload. if many pages, combine them all
into one single PDF file with many pages."
"""

from __future__ import annotations

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.completion_columns import completion_columns
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

User = get_user_model()

IN_MEMORY_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "private_uploads": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def photo(name="page.jpg", shade=210):
    """A page. Two pages of one form differ, so pass each its own shade."""
    buffer = io.BytesIO()
    Image.new("RGB", (600, 800), color=(shade, shade, shade)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def page_count(client, activity) -> int:
    """How many pages the activity's one document has, read as a reader does."""
    from pypdf import PdfReader

    response = client.get(f"/api/evidence/activity/{activity.id}/form")
    assert response.status_code == 200, response.content[:200]
    assert response["Content-Type"] == "application/pdf"
    return len(PdfReader(io.BytesIO(response.content)).pages)


class UploadFixture(TestCase):
    """A staff visit and a partner visit at one school, and who holds each.
    Shared with apps/evidence/test_form_document.py; it has no tests."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="EDS Region")
        district = District.objects.create(name="EDS District", region=region)
        cls.school = School.objects.create(
            school_id="EDS-SCH", name="EDS School", region=region, district=district
        )
        cls.cceo = User.objects.create(
            id="eds-cceo",
            email="eds-cceo@edify.org",
            name="EDS Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.cceo_sp = StaffProfile.objects.create(
            user=cls.cceo, staff_number="EDS-CCEO", country="Uganda", title="CCEO"
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)
        cls.partner_user = User.objects.create(
            id="eds-partner-user",
            email="eds-partner@edify.org",
            name="EDS Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="EDS Partner Org", user_id=cls.partner_user.id, active_status=True
        )

    def setUp(self):
        self.visit = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            delivery_type="staff",
            responsible_staff_id=self.cceo_sp.id,
            status="in_progress",
            scheduled_date=timezone.now(),
        )
        self.partner_visit = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            monitored_by_staff_id=self.cceo_sp.id,
            status="in_progress",
            scheduled_date=timezone.now(),
        )

    def _drawer(self, user, activity, path="evidence", status=200):
        self.client.force_login(user)
        response = self.client.get(f"/activities/{activity.id}/{path}")
        self.assertEqual(response.status_code, status)
        return response.content.decode()

    def _submit(self, user, activity, data):
        self.client.force_login(user)
        return self.client.post(
            f"/activities/{activity.id}/evidence/action", data, HTTP_HX_REQUEST="true"
        )


@override_settings(STORAGES=IN_MEMORY_STORAGES, CLAMAV_HOST=None)
class EvidenceDrawerSubmitTest(UploadFixture):
    # -- staff work takes no upload ------------------------------------------

    def test_staff_work_has_no_upload_drawer(self):
        html = self._drawer(self.cceo, self.visit, status=400)
        self.assertIn("No form is uploaded for it", html)
        self.assertNotIn('type="file"', html)
        self.assertNotIn("<form ", html)

    def test_a_staff_upload_is_refused(self):
        response = self._submit(
            self.cceo,
            self.visit,
            {"evidence_file_visit_form": [photo()], "salesforce_id": "SVE-EDS-0001"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"No form is uploaded for it", response.content)
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.visit).exists())
        self.visit.refresh_from_db()
        self.assertFalse(self.visit.salesforce_activity_id)

    def test_the_salesforce_drawer_on_staff_work_is_its_own_drawer(self):
        """It opened the upload drawer for staff work, where the form and the
        ID went in together; with no staff upload it is the ID drawer."""
        html = self._drawer(self.cceo, self.visit, path="salesforce-id")
        self.assertNotIn('type="file"', html)
        self.assertIn('name="salesforce_id"', html)
        self.assertIn(
            f'hx-post="/activities/{self.visit.id}/salesforce-id/action"', html
        )

    # -- the partner's drawer --------------------------------------------------

    def test_partner_work_has_the_upload_only(self):
        for viewer in (self.partner_user, self.cceo):
            with self.subTest(viewer=viewer.email):
                html = self._drawer(viewer, self.partner_visit)
                self.assertNotIn('name="salesforce_id"', html)
                self.assertIn('name="evidence_file_visit_form"', html)
                self.assertIn(">Submit</button>", html)

    def test_a_partner_submit_saves_the_upload_and_never_a_salesforce_id(self):
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {
                "evidence_file_visit_form": [photo()],
                "salesforce_id": "SVE-EDS-0004",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.partner_visit.refresh_from_db()
        self.assertFalse(self.partner_visit.salesforce_activity_id)
        self.assertEqual(
            EvidenceRecord.objects.get(activity=self.partner_visit).kind, "visit_form"
        )

    def test_pages_chosen_together_become_one_pdf(self):
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {"evidence_file_visit_form": [photo("p1.jpg", 200), photo("p2.jpg", 120)]},
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = EvidenceRecord.objects.get(activity=self.partner_visit)
        self.assertEqual(record.original_name, "Visit Form (2 pages).pdf")
        self.assertEqual(page_count(self.client, self.partner_visit), 2)
        # A partner's row reads its form; the Salesforce ID is the staff's.
        columns = completion_columns([(self.partner_visit.id, "school_visit")])
        self.assertEqual(columns[self.partner_visit.id]["evidence_label"], "Visit Form")
        self.assertTrue(columns[self.partner_visit.id]["evidence_ok"])

    def test_a_request_saved_offline_still_uploads(self):
        """The field outbox replays the form as it was saved: the one-form
        field (evidence_file, with or without evidence_kind), every page in
        it."""
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {"evidence_file": [photo("a.jpg", 200), photo("b.jpg", 90)]},
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = EvidenceRecord.objects.get(activity=self.partner_visit)
        self.assertEqual(
            (record.kind, record.original_name),
            ("visit_form", "Visit Form (2 pages).pdf"),
        )

    # -- one document: a second upload is another page, or it is refused -------

    def _first(self):
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {"evidence_file_visit_form": [photo("page-1.jpg", 200)]},
        )
        self.assertEqual(response.status_code, 200, response.content)
        return EvidenceRecord.objects.get(activity=self.partner_visit)

    def test_a_second_upload_is_refused_unless_it_is_called_a_different_page(self):
        first = self._first()
        for answer in (
            {},
            {"another_page_visit_form": ""},
            {"another_page_visit_form": "no"},
        ):
            with self.subTest(answer=answer):
                response = self._submit(
                    self.partner_user,
                    self.partner_visit,
                    {"evidence_file_visit_form": [photo("page-2.jpg", 90)], **answer},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(b"already uploaded", response.content)
        self.assertEqual(
            list(EvidenceRecord.objects.filter(activity=self.partner_visit)), [first]
        )
        self.assertEqual(page_count(self.client, self.partner_visit), 1)

    def test_a_different_page_joins_the_one_pdf(self):
        first = self._first()
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {
                "evidence_file_visit_form": [photo("page-2.jpg", 90)],
                "another_page_visit_form": "yes",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = EvidenceRecord.objects.get(activity=self.partner_visit)
        # One record, and it is the new document: the first page is inside it.
        self.assertNotEqual(record.id, first.id)
        self.assertEqual(record.original_name, "Visit Form (2 pages).pdf")
        self.assertEqual(record.kind, "visit_form")
        self.assertEqual(page_count(self.client, self.partner_visit), 2)

        # And a third page the same way: still one record, three pages.
        self._submit(
            self.partner_user,
            self.partner_visit,
            {
                "evidence_file_visit_form": [photo("page-3.jpg", 30)],
                "another_page_visit_form": "yes",
            },
        )
        self.assertEqual(
            EvidenceRecord.objects.filter(activity=self.partner_visit).count(), 1
        )
        self.assertEqual(page_count(self.client, self.partner_visit), 3)

    def test_the_same_file_is_refused_even_when_called_a_different_page(self):
        first = self._first()
        response = self._submit(
            self.partner_user,
            self.partner_visit,
            {
                "evidence_file_visit_form": [photo("page-1-again.jpg", 200)],
                "another_page_visit_form": "yes",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"is already in the uploaded Visit Form", response.content)
        self.assertEqual(
            list(EvidenceRecord.objects.filter(activity=self.partner_visit)), [first]
        )

    def test_a_file_sent_with_no_kind_follows_the_same_rule(self):
        """The offline drawer cannot name the form. Once the form is uploaded
        a file it sends is that form again, not a loose photo beside it."""
        self._first()
        refused = self._submit(
            self.partner_user,
            self.partner_visit,
            {"evidence_file": [photo("offline.jpg", 60)]},
        )
        self.assertEqual(refused.status_code, 400)
        taken = self._submit(
            self.partner_user,
            self.partner_visit,
            {"evidence_file": [photo("offline.jpg", 60)], "another_page": "yes"},
        )
        self.assertEqual(taken.status_code, 200, taken.content)
        record = EvidenceRecord.objects.get(activity=self.partner_visit)
        self.assertEqual(record.kind, "visit_form")
        self.assertEqual(page_count(self.client, self.partner_visit), 2)

    def test_the_drawer_on_an_uploaded_form_asks_and_offers_the_one_button(self):
        fresh = self._drawer(self.partner_user, self.partner_visit)
        self.assertIn("held = false", fresh)
        self.assertNotIn("View Uploaded Visit Form", fresh)

        self._first()
        html = self._drawer(self.partner_user, self.partner_visit)
        self.assertIn("held = true", html)
        self.assertIn("Is this a different page from the one you have uploaded?", html)
        self.assertIn('data-page-answer="yes"', html)
        self.assertIn('data-page-answer="no"', html)
        self.assertIn('name="another_page_visit_form"', html)
        # The one button, and no list of the files behind it.
        self.assertEqual(html.count("View Uploaded Visit Form</span>"), 1)
        self.assertIn(f"/api/evidence/activity/{self.partner_visit.id}/form", html)
        self.assertNotIn("Already uploaded", html)
        self.assertNotRegex(html, r"/api/evidence/[a-z0-9]+/file")
