"""A partner handover made from a project surface belongs to that project.

Project Planning's row Partner button, and the project card's, opened the
generic school-support drawer, which files the handover with no project
(``planning_views.assign_partner_action_view``: "School support handoffs are
not Project planning"). The coordinator's handover then reached none of the
project's reads — Project Planning kept the school "Ready for support",
Project Monitoring kept it "Not planned", and the impact engine never counted
its delivery. Both controls now open the project handover
(``/projects/planning/bulk-partner``), which stamps the project.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.planning_service import get_planning
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class ProjectPartnerHandoverTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        cls.fy = get_operational_fy()
        cls.coord_user = User.objects.create_user(
            email="pph-coord@edify.org",
            name="PPH Coordinator",
            roles=[EdifyRole.PROJECT_COORDINATOR.value],
            active_role=EdifyRole.PROJECT_COORDINATOR.value,
            password="x",
            is_active=True,
        )
        cls.coord = StaffProfile.objects.create(
            user=cls.coord_user, title="Coordinator", country="Uganda"
        )
        region = Region.objects.create(name="PPH Region")
        district = District.objects.create(name="PPH District", region=region)
        cls.school = School.objects.create(
            school_id="PPH-1",
            name="Handover Primary",
            region=region,
            district=district,
            school_type="client",
            current_fy_ssa_status="done",
            planning_readiness="ready_for_support_planning",
        )
        cls.project = Project.objects.create(
            name="PPH Learning Project",
            category="pilot",
            status="active",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
            target_interventions=[SsaIntervention.LEARNING_ENVIRONMENT],
            manager_staff_id=cls.coord.id,
        )
        cls.enrolment = ProjectSchoolAssignment.objects.create(
            project=cls.project, school=cls.school
        )
        record = SsaRecord.objects.create(
            school=cls.school,
            date_of_ssa=timezone.now() - timedelta(days=10),
            fy=cls.fy,
            quarter=get_quarter_for_date(),
            average_score=4.0,
            uploaded_by=cls.coord_user.id,
            verification_status="confirmed",
        )
        for code, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=code,
                score=3.5 if code == SsaIntervention.LEARNING_ENVIRONMENT else 6.5,
            )
        cls.partner = Partner.objects.create(name="PPH Partner", active_status=True)
        # The project allows the catalogue's partner-deliverable school work,
        # as a coordinator configures it on the project.
        from apps.activity_catalogue.models import (
            ActivityCatalogueItem,
            ActivityProjectMapping,
        )

        for item in ActivityCatalogueItem.objects.filter(
            partner_delivery_allowed=True, individual_school_allowed=True
        ):
            ActivityProjectMapping.objects.create(
                project=cls.project, catalogue_item=item
            )

    def _row(self):
        rows = get_planning(self.coord_user, {"fy": self.fy})["rows"]
        return next(row for row in rows if row["assignment_id"] == self.enrolment.id)

    def test_the_row_control_opens_the_project_handover(self):
        row = self._row()
        self.assertEqual(row["bucket"], "ready")
        self.assertEqual(
            row["partner_url"],
            f"/projects/planning/bulk-partner?assignments={self.enrolment.id}",
        )

    def test_the_row_offers_schedule_and_assign_in_one_actions_menu(self):
        """Owner, 2026-09-26: the row's Schedule and Partner buttons wrapped
        on a tablet; "switch to Action button with options to schedule and
        assign"."""
        self.client.force_login(self.coord_user)
        response = self.client.get("/projects/planning", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('aria-label="Actions for Handover Primary"', html)
        self.assertIn(
            'role="menuitem" hx-get="/projects/planning/bulk-partner?assignments='
            f'{self.enrolment.id}"',
            html,
        )
        self.assertIn(">Schedule</button>", html)
        self.assertIn(">Assign</button>", html)
        self.assertNotIn('class="spp-row-actions"', html)

    def test_a_handover_from_the_row_carries_the_project_and_moves_the_row(self):
        self.client.force_login(self.coord_user)
        drawer = self.client.get(self._row()["partner_url"])
        self.assertEqual(drawer.status_code, 200)
        items = drawer.context["catalogue_items"]
        self.assertTrue(items, "the seeded catalogue offers partner work here")

        response = self.client.post(
            "/projects/planning/bulk-partner",
            {
                "assignments": self.enrolment.id,
                "partner_id": self.partner.id,
                "scheduled_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
                "catalogue_item_id": items[0]["catalogueItemId"],
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:400])

        handover = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(handover.project_id, self.project.id)

        row = self._row()
        self.assertEqual(row["bucket"], "partner")
        self.assertEqual(row["readiness"], "Awaiting partner schedule")
        self.assertEqual(row["partner"], "PPH Partner")

    def test_the_partner_tab_holds_a_school_awaiting_its_partner(self):
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            project=self.project,
            assigning_staff_id=self.coord.id,
            monitoring_staff_id=self.coord.id,
            expected_activity_type="school_visit",
            status="pending_scheduling",
        )
        planning = get_planning(self.coord_user, {"fy": self.fy, "tab": "partner"})
        self.assertEqual(
            [row["assignment_id"] for row in planning["rows"]], [self.enrolment.id]
        )
        self.assertEqual(planning["tab_counts"]["partner"], 1)
        self.assertEqual(planning["tab_counts"]["ready"], 0)

    def test_a_school_support_handover_elsewhere_is_not_this_project_s(self):
        """Only the project's own handovers move its row."""
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            project=None,
            assigning_staff_id=self.coord.id,
            monitoring_staff_id=self.coord.id,
            expected_activity_type="school_visit",
            status="pending_scheduling",
        )
        self.assertEqual(self._row()["bucket"], "ready")

    def test_the_project_card_controls_stamp_the_project(self):
        self.client.force_login(self.coord_user)
        response = self.client.get(f"/partials/projects/{self.project.id}/schools")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(
            f"/projects/planning/bulk-partner?assignments={self.enrolment.id}", html
        )
        self.assertIn(
            f"/planning/schedule-modal?school_id={self.school.id}"
            f"&amp;project_id={self.project.id}",
            html,
        )
        self.assertNotIn("/planning/assign-partner-modal", html)

    def test_handing_the_school_to_the_same_partner_again_adds_nothing(self):
        """Owner, 2026-09-24: a school is assigned to the partner once. The
        drawer used to skip only an exact catalogue-item repeat, so choosing
        a different activity handed the same school over again."""
        self.client.force_login(self.coord_user)
        items = self.client.get(self._row()["partner_url"]).context["catalogue_items"]
        self.assertGreater(len(items), 1, "two activities to choose between")

        def hand_over(item):
            return self.client.post(
                "/projects/planning/bulk-partner",
                {
                    "assignments": self.enrolment.id,
                    "partner_id": self.partner.id,
                    "scheduled_date": (
                        timezone.localdate() + timedelta(days=7)
                    ).isoformat(),
                    "catalogue_item_id": item["catalogueItemId"],
                },
            )

        self.assertEqual(hand_over(items[0]).status_code, 200)
        again = hand_over(items[1])
        self.assertEqual(again.status_code, 200, again.content[:400])
        self.assertContains(again, "already assigned to PPH Partner")
        self.assertEqual(
            PartnerAssignment.objects.filter(
                school=self.school, partner=self.partner
            ).count(),
            1,
        )
