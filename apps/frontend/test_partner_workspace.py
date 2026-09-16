from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.clusters.models import Cluster
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
        ssa_item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
        )
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.profile.id,
            monitoring_staff_id=self.profile.id,
            catalogue_item=ssa_item,
            catalogue_snapshot=ssa_item.snapshot(),
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
        self.assertEqual(response.status_code, 200)
        assignment = PartnerAssignment.objects.filter(
            school=self.school,
            partner=self.partner,
            purpose_of_visit="ssa_support",
        ).latest("created_at")
        self.assertEqual(
            assignment.catalogue_item.stable_code,
            "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
        )
        self.assertEqual(assignment.monitoring_staff_id, self.profile.id)

    def test_school_assignment_drawer_has_only_the_three_support_reasons(self):
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={self.school.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for label in ("In-school Training", "Training Follow Up", "SSA Support"):
            self.assertIn(label, html)
        self.assertNotIn("Content Gathering", html)
        self.assertNotIn('name="project_id"', html)
        self.assertNotIn('name="expected_date"', html)
        self.assertIn("Partner Workspace Admin", html)
        self.assertIn("trainingActivities", html)
        self.assertIn("followUpActivities", html)

    def _partner_user(self):
        user = User.objects.create_user(
            email="partner-scheduler@example.org",
            name="Grace Visitor",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="test-password",
        )
        self.partner.user = user
        self.partner.save(update_fields=["user"])
        return user

    def test_partner_schedule_drawer_asks_only_for_date_and_visitor(self):
        assignment = PartnerAssignment.objects.filter(
            school=self.school,
            status="pending_scheduling",
        ).first()
        self.client.force_login(self._partner_user())
        response = self.client.get(
            f"/partner/assignments/{assignment.id}/schedule-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="scheduled_date"', html)
        self.assertIn('name="delivery_contact_name"', html)
        self.assertIn("Grace Visitor", html)
        self.assertIn(">Submit</button>", html)
        self.assertNotIn('name="catalogue_item_id"', html)
        self.assertNotIn('name="project_id"', html)
        self.assertNotIn("Cost calculation happens", html)

    def test_partner_scheduling_stamps_ssa_support_as_score_collection(self):
        school = School.objects.create(
            school_id="PARTNER-SSA-SCHEDULE-004",
            name="Partner SSA Schedule School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
        )
        assignment = PartnerAssignment.objects.create(
            school=school,
            partner=self.partner,
            assigning_staff_id=self.profile.id,
            monitoring_staff_id=self.profile.id,
            catalogue_item=item,
            catalogue_snapshot=item.snapshot(),
            purpose="SSA Support",
            purpose_of_visit="ssa_support",
            expected_activity_type="school_visit_ssa_collection",
            status="pending_scheduling",
        )
        self.client.force_login(self._partner_user())

        with patch("apps.activities.services._apply_schedule_cost_snapshot"):
            response = self.client.post(
                f"/partner/assignments/{assignment.id}/schedule-action",
                {
                    "scheduled_date": "2026-08-26",
                    "delivery_contact_name": "SSA Field Officer",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        assignment.refresh_from_db()
        activity = assignment.scheduled_activity
        self.assertEqual(activity.purpose_type, "ssa_support")
        self.assertTrue(activity.ssa_collection_expected)

    def test_partner_scheduling_creates_the_school_training_and_visitor_snapshot(self):
        school = School.objects.create(
            school_id="PARTNER-TRAINING-002",
            name="Partner Training School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_IN_SCHOOL_TRAINING"
        )
        assignment = PartnerAssignment.objects.create(
            school=school,
            partner=self.partner,
            assigning_staff_id=self.profile.id,
            monitoring_staff_id=self.profile.id,
            catalogue_item=item,
            catalogue_snapshot=item.snapshot(),
            purpose="In-School Training",
            purpose_of_visit="in_school_training",
            focus_intervention="leadership",
            expected_activity_type="in_school_training",
            status="pending_scheduling",
        )
        self.client.force_login(self._partner_user())
        with patch("apps.activities.services._apply_schedule_cost_snapshot"):
            response = self.client.post(
                f"/partner/assignments/{assignment.id}/schedule-action",
                {
                    "scheduled_date": "2026-08-25",
                    "delivery_contact_name": "Sarah Field Officer",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200, response.content)
        assignment.refresh_from_db()
        activity = assignment.scheduled_activity
        self.assertEqual(activity.activity_type, "in_school_training")
        self.assertEqual(activity.school_id, school.id)
        self.assertEqual(activity.salesforce_activity_type, "training")
        self.assertEqual(activity.delivery_contact_name, "Sarah Field Officer")

    def test_training_follow_up_assignment_uses_an_attended_current_fy_session(self):
        follow_up_school = School.objects.create(
            school_id="PARTNER-FOLLOW-UP-003",
            name="Partner Follow-up School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        cluster = Cluster.objects.create(
            name="Partner Follow-up Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        source = Activity.objects.create(
            activity_type="cluster_training",
            activity_name_snapshot="TAM I",
            cluster=cluster,
            fy=get_operational_fy(),
            quarter="Q4",
            planned_date=timezone.localdate() - timedelta(days=10),
            status="completed",
            attended_school_ids=[follow_up_school.id],
            focus_intervention="teaching_environment",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": follow_up_school.school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "training_follow_up",
                "source_activity_id": source.id,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        assignment = PartnerAssignment.objects.filter(
            purpose_of_visit="training_follow_up"
        ).latest("created_at")
        self.assertEqual(assignment.source_activity_id, source.id)
        self.assertEqual(assignment.focus_intervention, "teaching_environment")
        self.assertEqual(assignment.monitoring_staff_id, self.profile.id)
        self.client.force_login(self._partner_user())
        partner_page = self.client.get("/partner/assigned-schools")
        self.assertEqual(partner_page.status_code, 200)
        self.assertContains(partner_page, follow_up_school.name)
        self.assertContains(partner_page, "Training Follow Up")
