from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
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
        self.scheduled_activity = Activity.objects.create(
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
        # Partner Oversight prices work from agreed cost lines, never from an
        # estimate — its own rule, and the reason its Yet-to-Schedule list has
        # no cost column at all: an unscheduled handover has no price anybody
        # has agreed to, and printing one invites planning around a number
        # nobody set. So the scheduled activity gets a real line.
        ActivityScheduleCostLine.objects.create(
            activity=self.scheduled_activity,
            cost_setting_key="partner_training_day",
            label="Partner training day",
            unit_cost=120000,
            quantity=1,
            amount=120000,
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
        """Staff now land on Partner Oversight — /partners redirects them —
        so this follows the redirect and asserts the same facts survived it.

        The Partners directory and Partner Oversight answered one question
        from two sidebar entries and were merged. What this test has always
        been about is that the page reads live Activity and PartnerAssignment
        rows rather than a static fixture, and that is still the claim; only
        the page it lands on changed.

        "Scheduling Status Breakdown" is gone with the directory's donut. Its
        content is not: the oversight KPI strip carries scheduled, yet-to-
        schedule and at-risk as numbers, asserted below rather than assumed.
        """
        response = self.client.get(f"/partners?fy={self.fy}", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner Oversight")
        self.assertContains(response, "Partner Workspace Organisation")
        # The scheduled Activity. It reaches this page only because the merge
        # added partner-delivered activities with no PartnerAssignment row as a
        # second source — `activity_services.create` writes them, the old
        # directory listed them, and oversight alone would have lost them.
        self.assertContains(response, "In School Training")
        self.assertContains(response, "Scheduled &amp; Delivering (1)")
        # The handover, from the live PartnerAssignment row.
        self.assertContains(response, "School Visit Ssa Collection")
        self.assertContains(response, "Yet to Schedule (1)")
        self.assertContains(response, "120,000")

    def test_the_merge_kept_the_partners_contact_details(self):
        """The directory was the only place a supervisor could find who to
        call. A merge that dropped it would be a removal, not a consolidation."""
        response = self.client.get(f"/partners?fy={self.fy}", follow=True)

        self.assertContains(response, "Grace Example")
        self.assertContains(response, "+256 700 000 001")

    def test_a_partner_organisation_still_gets_the_workspace_itself(self):
        """The redirect is conditional: Partner Oversight does not admit
        Partner roles, so the directory stays their page."""
        partner_user = User.objects.create_user(
            email="workspace-officer@example.org",
            name="Workspace Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="test-password",
        )
        self.partner.user = partner_user
        self.partner.save(update_fields=["user"])
        self.client.force_login(partner_user)

        response = self.client.get(f"/partners?fy={self.fy}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner Activities")

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

    def test_admin_can_reach_partner_assignment_action(self):
        self.client.force_login(self.user)  # Admin
        with self.assertNoLogs("apps.core.htmx_errors", level="ERROR"):
            response = self.client.post(
                "/planning/assign-partner-action",
                {
                    "school_id": self.school.school_id,
                    "partner_id": self.partner.id,
                    "purpose_of_visit": "ssa_support",
                    "purpose": "Support visit.",
                },
            )
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Select an approved Activity Catalogue item.",
            status_code=400,
        )
