"""The upload evidence drawer saves with one Submit (owner, 2026-09-26).

"Partner evidence upload should only have upload, not the Salesforce field.
The staff can complete the Salesforce side, and the Salesforce drawer should
only be for completing partner work ... the Done button on the upload drawer
should be Submit, which would allow them to save the evidence and populate
the respective Evidence and SF columns."

So: one form, one Submit. On staff work it saves each form's pages and the
Salesforce ID together (or the ID alone); on partner work it saves the
upload only, and staff complete that work in the Salesforce ID drawer, which
opens the upload drawer for staff work instead.
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


def photo(name="page.jpg"):
    buffer = io.BytesIO()
    Image.new("RGB", (600, 800), color=(210, 210, 210)).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


@override_settings(STORAGES=IN_MEMORY_STORAGES, CLAMAV_HOST=None)
class EvidenceDrawerSubmitTest(TestCase):
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

    def _drawer(self, user, activity, path="evidence"):
        self.client.force_login(user)
        response = self.client.get(f"/activities/{activity.id}/{path}")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _submit(self, user, activity, data):
        self.client.force_login(user)
        return self.client.post(
            f"/activities/{activity.id}/evidence/action", data, HTTP_HX_REQUEST="true"
        )

    # -- the drawer --------------------------------------------------------

    def test_staff_work_has_one_form_the_salesforce_id_and_submit(self):
        html = self._drawer(self.cceo, self.visit)
        self.assertEqual(html.count("<form "), 1)
        self.assertEqual(html.count('name="salesforce_id"'), 1)
        self.assertIn('name="evidence_file_visit_form"', html)
        self.assertIn(">Submit</button>", html)
        self.assertNotIn(">Done</button>", html)
        main = html.split('name="evidence_file_visit_form"', 1)[1].split(">", 1)[0]
        self.assertIn("multiple", main)

    def test_partner_work_has_the_upload_only(self):
        for viewer in (self.partner_user, self.cceo):
            with self.subTest(viewer=viewer.email):
                html = self._drawer(viewer, self.partner_visit)
                self.assertNotIn('name="salesforce_id"', html)
                self.assertIn('name="evidence_file_visit_form"', html)
                self.assertIn(">Submit</button>", html)

    def test_the_salesforce_drawer_on_staff_work_opens_the_upload_drawer(self):
        html = self._drawer(self.cceo, self.visit, path="salesforce-id")
        self.assertIn('name="evidence_file_visit_form"', html)
        self.assertIn(">Submit</button>", html)

    # -- Submit --------------------------------------------------------------

    def test_submit_saves_the_pages_and_the_salesforce_id_together(self):
        response = self._submit(
            self.cceo,
            self.visit,
            {
                "evidence_file_visit_form": [photo("p1.jpg"), photo("p2.jpg")],
                "salesforce_id": "SVE-EDS-0001",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.salesforce_activity_id, "SVE-EDS-0001")
        record = EvidenceRecord.objects.get(activity=self.visit)
        self.assertEqual(record.original_name, "Visit Form (2 pages).pdf")
        # The two columns every planned-activities table reads.
        columns = completion_columns([(self.visit.id, "school_visit")])[self.visit.id]
        self.assertEqual(columns["salesforce_id"], "SVE-EDS-0001")
        self.assertEqual(columns["evidence_label"], "Visit Form")
        self.assertTrue(columns["salesforce_ok"] and columns["evidence_ok"])

    def test_submit_saves_the_salesforce_id_on_its_own(self):
        response = self._submit(
            self.cceo, self.visit, {"salesforce_id": "SVE-EDS-0002"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.salesforce_activity_id, "SVE-EDS-0002")
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.visit).exists())

    def test_submit_with_nothing_says_what_to_add(self):
        response = self._submit(self.cceo, self.visit, {"salesforce_id": ""})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"then Submit", response.content)

    def test_a_staff_form_still_needs_its_salesforce_id(self):
        response = self._submit(
            self.cceo, self.visit, {"evidence_file_visit_form": [photo()]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter the Salesforce ID", response.content)
        self.assertFalse(EvidenceRecord.objects.filter(activity=self.visit).exists())

    def test_the_salesforce_id_is_locked_after_ia_confirmation(self):
        self.visit.salesforce_activity_id = "SVE-EDS-0003"
        self.visit.ia_verification_status = "confirmed"
        self.visit.save(
            update_fields=["salesforce_activity_id", "ia_verification_status"]
        )
        response = self._submit(
            self.cceo, self.visit, {"salesforce_id": "SVE-EDS-9999"}
        )
        self.assertEqual(response.status_code, 400)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.salesforce_activity_id, "SVE-EDS-0003")

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

    def test_a_request_saved_offline_before_this_change_still_uploads(self):
        """The field outbox replays the form as it was saved: the one-form
        field (evidence_file + evidence_kind), with every page in it."""
        self.visit.salesforce_activity_id = "SVE-EDS-0005"
        self.visit.save(update_fields=["salesforce_activity_id"])
        response = self._submit(
            self.cceo,
            self.visit,
            {"evidence_kind": "visit_form", "evidence_file": [photo(), photo()]},
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = EvidenceRecord.objects.get(activity=self.visit)
        self.assertEqual(record.original_name, "Visit Form (2 pages).pdf")
