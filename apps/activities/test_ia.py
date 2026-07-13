from django.test import TestCase
from django.utils import timezone
from apps.activities.models import Activity, IAVerification, VerificationHistory
from apps.schools.models import School
from apps.geography.models import District, Region
from apps.core.enums import ActivityStatus, VerificationStatus
from apps.core.exceptions import BadRequest
from apps.activities.ia_services import (
    IAVerificationService,
    DuplicateDetectionService,
    ActivityCertificationService,
    ActivityReturnService,
)


class IAWorkflowTests(TestCase):
    def setUp(self):
        # Create geographical boundaries
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # Create test school
        self.school = School.objects.create(
            name="Greenhill Academy",
            school_type="core",
            district=self.district,
            region=self.region,
            account_owner_id="staff-cceo",
        )

        # Create a test activity
        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            responsible_staff_id="staff-cceo",
            planned_date=timezone.now().date(),
            scheduled_date=timezone.now(),
            status="awaiting_ia_verification",
            salesforce_activity_id="SV-99999",
        )

        # Create actor
        self.actor_id = "test-ia-user"

    def test_verification_checks_missing_evidence(self):
        """Checks recommend missing evidence when no evidence is uploaded."""
        checks = IAVerificationService.get_verification_checks(self.activity)
        self.assertFalse(checks["evidence_exists"])
        self.assertIn("No evidence", checks["evidence_desc"])

    def test_certify_activity_updates_status(self):
        """Certifying an activity changes status to ia_verified and logs history."""
        checklist_data = {
            "evidence_exists": True,
            "attendance_valid": True,
            "ssa_uploaded": True,
            "correct_school": True,
            "correct_cluster": True,
            "correct_intervention": True,
            "sf_id_entered": True,
            "duplicate_check_passed": True,
            "analytics_ready": True,
        }

        ActivityCertificationService.certify_activity(
            self.activity, checklist_data, self.actor_id
        )

        # Refresh from DB
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.IA_VERIFIED)
        self.assertEqual(
            self.activity.ia_verification_status, VerificationStatus.CONFIRMED
        )

        # History log check
        history = VerificationHistory.objects.filter(activity=self.activity).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.verified_by, self.actor_id)

    def test_return_activity_updates_status(self):
        """Returning an activity changes status to returned_by_ia and saves return reasons."""
        reasons = ["Evidence missing", "Wrong School"]
        comment = "Evidence file is empty."

        ActivityReturnService.return_activity(
            self.activity, reasons, comment, self.actor_id
        )

        # Refresh from DB
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.RETURNED_BY_IA)
        self.assertEqual(
            self.activity.ia_verification_status, VerificationStatus.RETURNED
        )

        # Verify reasons are stored
        verification = IAVerification.objects.filter(activity=self.activity).first()
        self.assertIsNotNone(verification)
        saved_reasons = [r.reason for r in verification.returned_reasons.all()]
        self.assertIn("Evidence missing", saved_reasons)
        self.assertIn("Wrong School", saved_reasons)

    def test_certify_activity_rejects_activity_not_awaiting_ia_verification(self):
        """A stale tab, replay, or racing second IA staffer must not be able
        to certify an activity that is already closed/cancelled/otherwise
        not in the awaiting_ia_verification state."""
        self.activity.status = ActivityStatus.CLOSED
        self.activity.save(update_fields=["status"])

        checklist_data = {"evidence_exists": True}
        with self.assertRaises(BadRequest):
            ActivityCertificationService.certify_activity(
                self.activity, checklist_data, self.actor_id
            )

        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.CLOSED)
        self.assertEqual(self.activity.ia_verification_status, VerificationStatus.PENDING)
        self.assertFalse(
            VerificationHistory.objects.filter(activity=self.activity).exists()
        )

    def test_return_activity_rejects_activity_not_awaiting_ia_verification(self):
        """Same race/replay guard for the return path — a cancelled activity
        must not be knocked back to returned_by_ia."""
        self.activity.status = ActivityStatus.CANCELLED
        self.activity.save(update_fields=["status"])

        with self.assertRaises(BadRequest):
            ActivityReturnService.return_activity(
                self.activity, ["Evidence missing"], "note", self.actor_id
            )

        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, ActivityStatus.CANCELLED)
        self.assertEqual(self.activity.ia_verification_status, VerificationStatus.PENDING)
        self.assertFalse(
            IAVerification.objects.filter(activity=self.activity).exists()
        )

    def test_detect_duplicates(self):
        """Detects duplicate activities that have the same Salesforce ID."""
        dup_activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            responsible_staff_id="staff-cceo",
            planned_date=timezone.now().date(),
            scheduled_date=timezone.now(),
            status="completed",
            salesforce_activity_id="SV-99999",  # Same SF ID
        )

        dups = DuplicateDetectionService.detect_duplicates(self.activity)
        self.assertTrue(len(dups) > 0)
        self.assertTrue(any(d["activity"].id == dup_activity.id for d in dups))
        self.assertTrue(any("Salesforce" in d["reason"] for d in dups))
