"""Projects and partners without the SSA restriction (owner, 2026-09-30).

"can you lift the ssa restriction on schools assigned to partners and
projects. Also can you add intervention "General" to the Project SSA
intervention list. Allow the Users to edit and change the project
intervention. Also lift the restriction on how many time a school is
assigned to project for example a school can be added to CC-SEL project and
other projects."

The multi-project half lives in test_staff_priorities; the enrolment half in
apps.core.tests.test_ecosystem_handoffs. This file covers General, changing a
project's intervention, and the project and partner work a school without an
SSA may now receive.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.projects.models import GENERAL_INTERVENTION, Project
from apps.projects.services import create_project, update_project
from apps.schools.models import School


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Lift Region")
        cls.district = District.objects.create(
            name="Lift District", region=cls.region, district_type="primary"
        )
        cls.sub_county = SubCounty.objects.create(
            name="Lift Sub", district=cls.district
        )
        cls.school = School.objects.create(
            school_id="LIFT-1",
            name="Lift Primary",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
        )
        cls.coordinator = User.objects.create(
            id="lift-pc",
            email="lift-pc@edify.org",
            name="Lift Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        cls.coordinator_profile = StaffProfile.objects.create(
            id="lift-pc-staff",
            user=cls.coordinator,
            staff_number="PC-LIFT",
            country="Uganda",
        )

    def _item(self, workflow_kind="school_visit"):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        return resolve_item_for_workflow_kind(workflow_kind)

    def _create(self, targets):
        return create_project(
            {
                "name": f"Lift {'-'.join(targets) or 'none'}",
                "category": "intervention_specific",
                "targetInterventions": targets,
                "catalogueItemIds": [self._item().id],
            },
            self.coordinator,
        )


class GeneralInterventionTest(_Fixture):
    def test_a_project_may_target_general(self):
        created = self._create([GENERAL_INTERVENTION])
        project = Project.objects.get(id=created["id"])
        self.assertEqual(project.target_intervention_list(), ["general"])
        self.assertIsNone(project.intervention)

    def test_general_is_never_an_activity_focus(self):
        """An Activity's focus must be one of the eight SSA interventions."""
        project = Project.objects.get(id=self._create([GENERAL_INTERVENTION])["id"])
        self.assertEqual(project.intervention_plan(), (None, []))

        both = Project.objects.get(
            id=self._create([GENERAL_INTERVENTION, "leadership"])["id"]
        )
        self.assertEqual(both.intervention_plan(), ("leadership", []))

    def test_an_unknown_intervention_is_still_refused(self):
        with self.assertRaisesMessage(BadRequest, "Unknown target intervention"):
            self._create(["general_knowledge"])

    def test_the_drawers_offer_general(self):
        self.client.force_login(self.coordinator)
        create = self.client.get("/projects/create")
        self.assertContains(create, 'value="general"')
        self.assertContains(create, "General")


class ChangeTheProjectInterventionTest(_Fixture):
    """The seeded projects hold only the legacy `intervention` field."""

    def setUp(self):
        self.project = Project.objects.create(
            name="CCSEL",
            code="SP-LIFT-CCSEL",
            category="intervention_specific",
            status="active",
            manager_staff_id=self.coordinator_profile.id,
            intervention="christlike_behaviour",
            target_interventions=[],
        )

    def _update(self, targets):
        update_project(
            self.project.id, {"targetInterventions": targets}, self.coordinator
        )
        self.project.refresh_from_db()

    def test_the_legacy_intervention_can_be_replaced(self):
        self._update(["leadership"])
        self.assertEqual(self.project.target_intervention_list(), ["leadership"])
        self.assertEqual(self.project.intervention, "leadership")
        self.assertEqual(self.project.intervention_plan(), ("leadership", []))

    def test_the_legacy_intervention_stays_primary_while_chosen(self):
        self._update(["leadership", "christlike_behaviour"])
        self.assertEqual(self.project.intervention, "christlike_behaviour")
        self.assertEqual(
            self.project.intervention_plan(), ("christlike_behaviour", ["leadership"])
        )

    def test_changing_to_general_clears_the_ssa_intervention(self):
        self._update([GENERAL_INTERVENTION])
        self.assertEqual(self.project.target_intervention_list(), ["general"])
        self.assertIsNone(self.project.intervention)

    def test_the_edit_drawer_saves_the_change(self):
        self.client.force_login(self.coordinator)
        drawer = self.client.get(f"/projects/{self.project.id}/edit")
        self.assertContains(drawer, 'value="general"')
        response = self.client.post(
            f"/projects/{self.project.id}/edit",
            {
                "name": self.project.name,
                "category": self.project.category,
                "schoolFocus": self.project.school_focus,
                "targetInterventions": [GENERAL_INTERVENTION, "financial_health"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertEqual(
            self.project.target_intervention_list(), ["general", "financial_health"]
        )
        self.assertEqual(self.project.intervention, "financial_health")


class ProjectWorkWithoutAnSsaTest(_Fixture):
    def test_the_projects_activities_are_offered_without_an_ssa(self):
        from apps.activity_catalogue.services import recommend_activities

        project = Project.objects.get(id=self._create(["leadership"])["id"])
        item = self._item()
        for executor_type in ("staff", "partner"):
            with self.subTest(executor_type=executor_type):
                result = recommend_activities(
                    school=self.school,
                    project=project,
                    executor_type=executor_type,
                    limit=100,
                )
                self.assertFalse(result["hasApplicableSsa"])
                offered = {
                    row["catalogueItemId"]: row
                    for row in [*result["primary"], *result["otherEligible"]]
                }
                self.assertIn(item.id, offered)
                self.assertEqual(offered[item.id]["targetIntervention"], "leadership")

    def test_outside_a_project_the_ssa_collection_is_still_what_is_offered(self):
        from apps.activity_catalogue.services import recommend_activities

        result = recommend_activities(school=self.school, limit=100)
        self.assertNotIn(
            self._item().id,
            {row["catalogueItemId"] for row in result["primary"]},
        )

    def test_the_planning_row_keeps_schedule_while_the_ssa_visit_is_booked(self):
        from apps.projects.planning_service import _row_state

        booked_ssa = SimpleNamespace(
            ssa_collection_expected=True,
            status="scheduled",
            delivery_type="staff",
            get_status_display=lambda: "Scheduled",
        )
        self.assertEqual(_row_state(None, [booked_ssa])["action_kind"], "schedule")
        self.assertEqual(_row_state(None, [])["action_kind"], "schedule")


class PartnerHandoverWithoutAnSsaTest(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cceo = User.objects.create(
            id="lift-cceo",
            email="lift-cceo@edify.org",
            name="Lift CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.cceo_profile = StaffProfile.objects.create(
            user=cls.cceo, staff_number="LIFT-CCEO", country="Uganda", title="CCEO"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_profile, school_id=cls.school.id
        )
        partner_user = User.objects.create(
            id="lift-partner",
            email="lift-partner@edify.org",
            name="Lift Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="Lift Partner Org", user_id=partner_user.id, active_status=True
        )

    def test_an_in_school_training_is_handed_over_without_an_ssa(self):
        """This purpose used to be refused: "Complete the School SSA first"."""
        from apps.activity_catalogue.availability import (
            SCHOOL,
            training_activity_options,
        )
        from apps.activity_catalogue.models import ActivityCatalogueItem

        options = training_activity_options(planning_context=SCHOOL)
        course = next(
            option
            for option in options
            if ActivityCatalogueItem.objects.get(id=option["id"]).requires_current_ssa
        )
        self.assertFalse(self.school.ssa_records.exists())

        self.client.force_login(self.cceo)
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "in_school_training",
                "catalogue_item_id": course["id"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertNotContains(
            response, "Complete the School SSA first", status_code=response.status_code
        )
        handover = PartnerAssignment.objects.get(
            partner=self.partner, school=self.school
        )
        self.assertEqual(handover.purpose_of_visit, "in_school_training")
        self.assertIsNone(handover.source_ssa_id)
