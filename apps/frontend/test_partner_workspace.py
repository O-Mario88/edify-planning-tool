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
        """The rule itself, at its canonical definition.

        This used to POST /planning/assign-partner-action as an Admin. Admin
        cannot assign work to a partner any more -- the Platform Operations
        doctrine names it -- and reproducing a Program Lead's school scope here
        would test the fixture rather than the rule. `normalise_visit_purpose`
        is where the rule lives and where every caller reaches it.
        """
        from apps.core.exceptions import BadRequest
        from apps.partners.purposes import normalise_visit_purpose

        with self.assertRaises(BadRequest) as refused:
            normalise_visit_purpose("donor_visit", for_partner=True)
        self.assertIn(
            "cannot be assigned to a delivery partner", str(refused.exception)
        )

        # A partner-safe purpose passes unchanged.
        self.assertEqual(
            normalise_visit_purpose("ssa_support", for_partner=True),
            "ssa_support",
        )

    def test_admin_cannot_assign_work_to_a_partner_at_all(self):
        """The doctrine, at the boundary the browser would hit."""
        self.client.force_login(self.user)  # Admin
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
                "purpose": "Support visit.",
            },
        )
        self.assertEqual(response.status_code, 403)
