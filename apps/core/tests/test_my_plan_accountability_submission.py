"""The staff-facing Complete Activity drawer must SUBMIT accountability for
review, not self-close it. Regression test for a bug where POSTing a
netsuite_id let the responsible user flip their own AdvanceRequest straight
to ACCOUNTED — bypassing the Accountant's approve_accountability() review
entirely and skipping amount capture."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class CompleteActivityAccountabilitySubmissionTest(TestCase):
    def setUp(self):
        self.cceo = User.objects.create_user(
            email="cceo-accountability@test.org",
            name="Field CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        region = Region.objects.create(name="Accountability Region")
        district = District.objects.create(
            name="Accountability District", region=region
        )
        school = School.objects.create(
            school_id="ACC-SCH",
            name="Accountability School",
            region=region,
            district=district,
        )
        StaffSchoolAssignment.objects.create(staff=cceo_staff, school_id=school.id)

        self.activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy="2026",
            quarter="Q1",
            responsible_staff_id=self.cceo.id,
            status="completion_started",
            scheduled_date=timezone.now(),
            delivery_type="staff",
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            responsible_user=self.cceo.user_id,
            line_item_type="transport",
            label="Transport",
            quantity=1,
            unit_cost=50_000,
            amount=50_000,
            currency="UGX",
        )
        self.adv = AdvanceRequest.objects.create(
            activity=self.activity,
            budget_line=self.cost_line,
            responsible_user_id=self.cceo.user_id,
            fy="2026",
            quarter="Q1",
            amount=50_000,
            status=AdvanceRequestStatus.DISBURSED,
            advance_type="advance",
        )
        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="photo",
            uri="test-evidence.jpg",
            uploaded_by=self.cceo.user_id,
        )
        self.client.force_login(self.cceo)

    def test_submitting_netsuite_id_lands_in_accountability_pending_not_accounted(self):
        resp = self.client.post(
            f"/my-plan/{self.activity.id}/complete",
            {
                "salesforce_id": "SVE-99001100",
                "netsuite_id": "EXP-2026-00889",
                "amount_spent": "48000",
                "amount_returned": "2000",
            },
        )
        self.assertIn(resp.status_code, (200, 302))

        self.adv.refresh_from_db()
        # The responsible user's submission must NOT self-close accountability —
        # it must wait for the Accountant's approve_accountability() review.
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)
        self.assertNotEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)
        self.assertEqual(self.adv.accountability_netsuite_id, "EXP-2026-00889")
        self.assertEqual(self.adv.accounted_amount, 48000)
        self.assertEqual(self.adv.returned_amount, 2000)

    def test_accountant_approval_is_required_to_reach_accounted(self):
        self.client.post(
            f"/my-plan/{self.activity.id}/complete",
            {
                "salesforce_id": "SVE-99001101",
                "netsuite_id": "EXP-2026-00890",
                "amount_spent": "50000",
                "amount_returned": "0",
            },
        )
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTABILITY_PENDING)

        from apps.fund_requests.advance_service import approve_accountability

        # Final clearance is IA-gated — verify the activity first.
        self.activity.ia_verification_status = "confirmed"
        self.activity.save(update_fields=["ia_verification_status"])

        accountant = User.objects.create_user(
            email="accountant-accountability@test.org",
            name="Accountability Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="password",
            is_active=True,
        )
        approve_accountability(self.adv.id, accountant)
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.ACCOUNTED)
