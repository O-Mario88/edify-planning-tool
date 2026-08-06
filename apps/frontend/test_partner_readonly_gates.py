"""Partner-owned activities must be read-only for staff monitors — staff can
view/track them but never mutate them (that's the partner's own job via
/partner/my-plan). apps/frontend/views/my_plan_views.py:_forbid_staff_on_partner_activity
is the gate; this is a regression test for three mutation endpoints that were
missing it (attendance upload, accountability submission, complete/evidence
submission) while their sibling endpoints (start/evidence-upload/SF-id/submit)
already had it.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

User = get_user_model()


class PartnerActivityReadOnlyForStaffTest(TestCase):
    def setUp(self):
        self.cceo = User.objects.create_user(
            email="cceo-partner-gate@test.org",
            name="Gate CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        region = Region.objects.create(name="Gate Region")
        district = District.objects.create(name="Gate District", region=region)
        self.school = School.objects.create(
            school_id="GATE-SCH",
            name="Gate School",
            region=region,
            district=district,
        )
        StaffSchoolAssignment.objects.create(staff=cceo_staff, school_id=self.school.id)

        self.partner = Partner.objects.create(name="Gate Partner Org")
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            responsible_staff_id=None,
            status="completion_started",
            scheduled_date=timezone.now(),
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.activity,
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
            responsible_user_id=self.cceo.id,
            fy="2026",
            quarter="Q1",
            amount=50_000,
            status=AdvanceRequestStatus.DISBURSED,
            advance_type="advance",
        )
        self.client.force_login(self.cceo)

    def test_staff_cannot_upload_attendance_on_partner_activity(self):
        resp = self.client.post(
            f"/activities/{self.activity.id}/attendance/action",
            {"teachers_attended": "5", "leaders_attended": "1"},
        )
        self.assertEqual(resp.status_code, 403)
        self.activity.refresh_from_db()
        self.assertNotEqual(self.activity.status, "completed")

    def test_staff_cannot_submit_accountability_on_partner_activity(self):
        resp = self.client.post(
            f"/my-plan/{self.activity.id}/accountability",
            {
                "netsuite_id": "EXP-2026-GATE",
                "amount_spent": "50000",
                "amount_returned": "0",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.adv.refresh_from_db()
        self.assertEqual(self.adv.status, AdvanceRequestStatus.DISBURSED)

    def test_staff_cannot_complete_partner_activity(self):
        resp = self.client.post(
            f"/my-plan/{self.activity.id}/complete",
            {
                "salesforce_id": "SV-GATE001",
                "netsuite_id": "EXP-2026-GATE2",
                "amount_spent": "50000",
                "amount_returned": "0",
            },
        )
        self.assertEqual(resp.status_code, 403)
        self.activity.refresh_from_db()
        self.assertNotEqual(self.activity.status, "completed")

    def test_partner_user_can_still_use_partner_my_plan_endpoints(self):
        """The gate must not block the assigned partner's own user — only
        staff monitors outside the partner scope."""
        partner_user = User.objects.create_user(
            email="partner-gate-user@test.org",
            name="Gate Partner User",
            roles=[EdifyRole.PARTNER_ADMIN.value],
            active_role=EdifyRole.PARTNER_ADMIN.value,
            password="password",
            is_active=True,
        )
        self.partner.user_id = partner_user.id
        self.partner.save(update_fields=["user_id"])
        self.client.force_login(partner_user)

        resp = self.client.post(
            f"/activities/{self.activity.id}/attendance/action",
            {"teachers_attended": "5", "leaders_attended": "1"},
        )
        self.assertNotEqual(resp.status_code, 403)
