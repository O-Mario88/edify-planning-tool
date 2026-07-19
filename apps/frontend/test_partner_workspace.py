from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


class PartnerWorkspaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="partner-workspace-admin@example.org",
            name="Partner Workspace Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="test-password",
        )
        self.profile = StaffProfile.objects.create(
            user=self.user,
            title="Program Lead",
        )
        self.region = Region.objects.create(name="Partner Workspace Region")
        self.district = District.objects.create(
            name="Partner Workspace District",
            region=self.region,
        )
        self.school = School.objects.create(
            school_id="PARTNER-WORKSPACE-001",
            name="Partner Workspace School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.partner = Partner.objects.create(
            name="Partner Workspace Organisation",
            region_name=self.region.name,
            contact_person="Grace Example",
            phone="+256 700 000 001",
            active_status=True,
        )
        self.fy = get_operational_fy(date(2026, 7, 19))
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy=self.fy,
            quarter=get_quarter_for_date(date(2026, 7, 19)),
            planned_date=date(2026, 7, 22),
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            purpose_type="in_school_training",
            focus_intervention="leadership",
            status="scheduled",
            est_cost_cents=120000,
        )
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.profile.id,
            purpose_of_visit="ssa_support",
            expected_activity_type="school_visit_ssa_collection",
            status="pending_scheduling",
        )
        self.client.force_login(self.user)

    def test_partner_workspace_uses_live_activity_and_assignment_data(self):
        response = self.client.get(f"/partners?fy={self.fy}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner Activities")
        self.assertContains(response, "Partner Workspace Organisation")
        self.assertContains(response, "In-school Training")
        self.assertContains(response, "SSA Support")
        self.assertContains(response, "Scheduling Status Breakdown")
        self.assertContains(response, "UGX 120,000")

    def test_partner_assignment_only_accepts_partner_safe_purposes(self):
        unsafe = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "donor_visit",
                "purpose": "Introduce a donor to the school.",
            },
        )
        self.assertEqual(unsafe.status_code, 400)
        self.assertIn(b"cannot be assigned to a delivery partner", unsafe.content)

        safe = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "training_follow_up",
                "purpose": "Support follow-up after staff training.",
            },
        )
        self.assertEqual(safe.status_code, 200, safe.content)
        assignment = PartnerAssignment.objects.filter(
            school=self.school,
            partner=self.partner,
            purpose_of_visit="training_follow_up",
        ).first()
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.expected_activity_type, "training_follow_up_visit")
