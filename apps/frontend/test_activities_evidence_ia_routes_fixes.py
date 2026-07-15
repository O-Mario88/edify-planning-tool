"""Regression tests for the activities_evidence_ia_routes audit domain
punch-list fixes (2026-07 platform audit).

Covers:
  - closure_readiness_queue_view: checklist refresh window matches the
    categorization window (no silent vanish beyond row 20).
  - salesforce_id_action: format validation + IA-confirmation lock.
  - trainings_log_view: TRAINING_TYPES uses real ActivityType enum members.
  - evidence_gallery_view: legacy /evidence route redirects to the working
    Evidence Center instead of rendering an incompatible, empty context.
  - infer_kind_from_upload: evidence kind derived from file type, not
    hardcoded "photo".
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.evidence.services import infer_kind_from_upload
from apps.geography.models import Region, District
from apps.schools.models import School

User = get_user_model()


class DomainFixturesMixin:
    def _make_cceo(self):
        user = User.objects.create(
            id="cceo-fix-1",
            email="cceo-fix@edify.org",
            name="CCEO Fix User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        user.set_password("pass123")
        user.save()
        StaffProfile.objects.create(id="staff-cceo-fix-1", user=user, title="CCEO")
        return user

    def _make_school(self):
        region = Region.objects.create(name="Central Region")
        district = District.objects.create(name="Kampala", region=region)
        return School.objects.create(
            name="Test School", region=region, district=district
        )


class ClosureReadinessQueueRefreshWindowTest(DomainFixturesMixin, TestCase):
    """MEDIUM: checklist refresh must cover the full categorized queryset,
    not just the first 20 rows, or later rows bucket on stale/None
    checklists and silently vanish from every tab."""

    def setUp(self):
        self.user = self._make_cceo()
        self.school = self._make_school()
        # 25 executed activities with no closure_checklist yet -- more than
        # the old hardcoded 20-row refresh window.
        self.activities = []
        for i in range(25):
            a = Activity.objects.create(
                school=self.school,
                delivery_type="staff",
                activity_type="school_visit",
                status="completed",
                responsible_staff_id=self.user.id,
                planned_date=date(2026, 7, 1) + timedelta(days=i),
            )
            self.activities.append(a)

    def test_all_rows_get_a_checklist_and_a_bucket(self):
        self.client.force_login(self.user)
        response = self.client.get("/activities/closure/")
        self.assertEqual(response.status_code, 200)

        bucketed_ids = set()
        for key in (
            "ready",
            "finance_pending",
            "accountability_pending",
            "analytics_pending",
            "blocked",
            "closed",
        ):
            bucketed_ids.update(a.id for a in response.context[key])

        all_ids = {a.id for a in self.activities}
        # Every activity must land in exactly one tab -- none should vanish
        # for lack of a checklist.
        self.assertTrue(all_ids.issubset(bucketed_ids))

        # Confirm every activity now actually has a persisted checklist (the
        # bug this test targets: a stale/None checklist beyond row 20).
        for a in self.activities:
            a.refresh_from_db()
            self.assertTrue(
                hasattr(a, "closure_checklist") and a.closure_checklist is not None
            )


class SalesforceIdActionValidationTest(DomainFixturesMixin, TestCase):
    """MEDIUM: salesforce_id_action must enforce the same format validation
    and IA-confirmation lock that services.complete() enforces elsewhere."""

    def setUp(self):
        self.user = self._make_cceo()
        self.school = self._make_school()
        self.activity = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="awaiting_ia_verification",
            responsible_staff_id=self.user.id,
            planned_date=date(2026, 7, 2),
        )

    def test_rejects_malformed_salesforce_id(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/activities/{self.activity.id}/salesforce-id/action",
            {"salesforce_id": "not-a-real-id"},
        )
        self.assertEqual(response.status_code, 400)
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.salesforce_activity_id)

    def test_accepts_well_formed_salesforce_id(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/activities/{self.activity.id}/salesforce-id/action",
            {"salesforce_id": "SVE-12345"},
        )
        self.assertIn(response.status_code, (200, 302))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.salesforce_activity_id, "SVE-12345")

    def test_locked_after_ia_confirmation(self):
        self.activity.ia_verification_status = "confirmed"
        self.activity.salesforce_activity_id = "SV-11111"
        self.activity.save(
            update_fields=["ia_verification_status", "salesforce_activity_id"]
        )
        self.client.force_login(self.user)
        response = self.client.post(
            f"/activities/{self.activity.id}/salesforce-id/action",
            {"salesforce_id": "SV-99999"},
        )
        self.assertEqual(response.status_code, 400)
        self.activity.refresh_from_db()
        # Original SF ID must remain untouched.
        self.assertEqual(self.activity.salesforce_activity_id, "SV-11111")


class TrainingsLogRealEnumValuesTest(DomainFixturesMixin, TestCase):
    """MEDIUM: TRAINING_TYPES must use real ActivityType enum members, not
    the fictitious "group_training"/"teachers_training"."""

    def setUp(self):
        self.user = self._make_cceo()
        self.school = self._make_school()
        self.cluster_training = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="cluster_training",
            status="completed",
            responsible_staff_id=self.user.id,
            planned_date=date(2026, 7, 2),
        )
        self.school_improvement_training = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_improvement_training",
            status="completed",
            responsible_staff_id=self.user.id,
            planned_date=date(2026, 7, 3),
        )
        self.core_training = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="core_training",
            status="completed",
            responsible_staff_id=self.user.id,
            planned_date=date(2026, 7, 4),
        )
        # Not a training at all -- must never appear.
        self.visit = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="completed",
            responsible_staff_id=self.user.id,
            planned_date=date(2026, 7, 5),
        )

    def test_real_training_types_are_included(self):
        self.client.force_login(self.user)
        response = self.client.get("/trainings")
        self.assertEqual(response.status_code, 200)
        ids = {a.id for a in response.context["trainings"]}
        self.assertIn(self.cluster_training.id, ids)
        self.assertIn(self.school_improvement_training.id, ids)
        self.assertIn(self.core_training.id, ids)
        self.assertNotIn(self.visit.id, ids)


class EvidenceGalleryRedirectTest(DomainFixturesMixin, TestCase):
    """MEDIUM: the broken /evidence (no trailing slash) duplicate must
    redirect to the working Evidence Center rather than render an
    incompatible, always-empty context."""

    def setUp(self):
        self.user = self._make_cceo()

    def test_legacy_evidence_route_redirects_to_evidence_center(self):
        self.client.force_login(self.user)
        response = self.client.get("/evidence", follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/evidence/")


class InferKindFromUploadTest(TestCase):
    """LOW-MEDIUM: evidence kind should be derived from the uploaded file's
    type instead of being hardcoded to "photo"."""

    def test_pdf_extension_infers_pdf(self):
        f = SimpleUploadedFile(
            "report.pdf", b"%PDF-1.4", content_type="application/pdf"
        )
        self.assertEqual(infer_kind_from_upload(f), "pdf")

    def test_docx_infers_pdf_bucket(self):
        f = SimpleUploadedFile(
            "report.docx",
            b"PK\x03\x04",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(infer_kind_from_upload(f), "pdf")

    def test_image_falls_back_to_photo(self):
        f = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff", content_type="image/jpeg")
        self.assertEqual(infer_kind_from_upload(f), "photo")
