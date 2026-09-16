"""Correcting and withdrawing a Special Project (owner, 2026-09-16).

Projects could be created and decided upon, never corrected and never removed.
A coordinator who mistyped a cohort had to leave it standing, so the pickers
filled with corrections nobody could clear; and a budget ceiling agreed after
the fact meant a second project.

Deleting is refused the moment work has been filed against the project. At
that point the honest move is to close it, which keeps the history — the
activities are the record that the project happened.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.services import delete_project, update_project
from apps.schools.models import School


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Lifecycle Region")
        cls.district = District.objects.create(
            name="Lifecycle District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="LIFE-1",
            name="Lifecycle School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.coordinator = User.objects.create(
            id="life-pc",
            email="life-pc@edify.org",
            name="Owning Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        cls.coordinator_profile = StaffProfile.objects.create(
            id="life-pc-staff", user=cls.coordinator, staff_number="PC-LIFE"
        )
        cls.peer = User.objects.create(
            id="life-peer",
            email="life-peer@edify.org",
            name="Other Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        cls.peer_profile = StaffProfile.objects.create(
            id="life-peer-staff", user=cls.peer, staff_number="PC-PEER"
        )
        cls.project = Project.objects.create(
            name="Lifecycle Project",
            code="SP-LIFE-1",
            category="intervention_specific",
            status="active",
            manager_staff_id=cls.coordinator_profile.id,
            target_interventions=["learning_environment"],
        )


class TheOwnerCorrectsTheProjectTest(_Fixture):
    def test_the_coordinator_edits_their_own_project(self):
        update_project(
            self.project.id,
            {"name": "Numeracy Boost", "budgetCeilingUgx": "25000000"},
            self.coordinator,
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Numeracy Boost")
        self.assertEqual(self.project.budget_ceiling_ugx, 25_000_000)

    def test_only_the_keys_sent_are_touched(self):
        """A drawer showing three fields must not blank the other five."""
        update_project(self.project.id, {"name": "Renamed"}, self.coordinator)
        self.project.refresh_from_db()
        self.assertEqual(self.project.code, "SP-LIFE-1")
        self.assertEqual(
            self.project.target_intervention_list(), ["learning_environment"]
        )

    def test_a_peers_project_is_refused(self):
        with self.assertRaises(Forbidden) as caught:
            update_project(self.project.id, {"name": "Mine now"}, self.peer)
        self.assertIn("run by someone else", str(caught.exception))

    def test_the_status_is_not_editable_here(self):
        """The lifecycle moves through the RVP's decision, not this drawer."""
        update_project(
            self.project.id,
            {"name": "Still active", "status": "closed"},
            self.coordinator,
        )
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "active")

    def test_an_empty_target_list_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            update_project(
                self.project.id, {"targetInterventions": []}, self.coordinator
            )
        self.assertIn("target SSA intervention", str(caught.exception))


class TheOwnerWithdrawsAnUnusedProjectTest(_Fixture):
    def test_a_project_with_no_activities_is_deleted(self):
        ProjectSchoolAssignment.objects.create(project=self.project, school=self.school)
        result = delete_project(self.project.id, self.coordinator, reason="Mistyped")
        self.assertEqual(result["schoolsReleased"], 1)
        self.project.refresh_from_db()
        self.assertIsNotNone(self.project.deleted_at)
        # The schools go back to their own portfolio rather than pointing at a
        # project that no longer exists.
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(project=self.project).exists()
        )

    def test_a_project_with_activities_is_refused(self):
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=get_operational_fy(),
            quarter="Q1",
            status="planned",
        )
        with self.assertRaises(BadRequest) as caught:
            delete_project(self.project.id, self.coordinator)
        message = str(caught.exception)
        self.assertIn("cannot be deleted", message)
        self.assertIn("close it instead", message)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.deleted_at)

    def test_a_cancelled_activity_still_counts(self):
        """Cancelled work is still the record that the project was delivered
        against, and its audit trail has to keep pointing somewhere real."""
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=get_operational_fy(),
            quarter="Q1",
            status="cancelled",
        )
        with self.assertRaises(BadRequest):
            delete_project(self.project.id, self.coordinator)

    def test_a_peers_project_is_refused(self):
        with self.assertRaises(Forbidden):
            delete_project(self.project.id, self.peer)
        self.project.refresh_from_db()
        self.assertIsNone(self.project.deleted_at)


class TheProjectProfileOffersThemTest(_Fixture):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.coordinator)

    def test_the_owner_sees_edit_and_delete(self):
        response = self.client.get(f"/projects/{self.project.id}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_edit_project"])
        self.assertEqual(response.context["delete_block"], "")
        self.assertContains(response, "Edit Project")
        self.assertContains(response, f"/projects/{self.project.id}/delete")

    def test_the_delete_control_says_why_it_is_blocked(self):
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=get_operational_fy(),
            quarter="Q1",
            status="planned",
        )
        response = self.client.get(f"/projects/{self.project.id}")
        self.assertIn("cannot be deleted", response.context["delete_block"])
        self.assertNotContains(response, f"/projects/{self.project.id}/delete")

    def test_the_edit_drawer_is_prefilled(self):
        response = self.client.get(
            f"/projects/{self.project.id}/edit", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SP-LIFE-1")
        self.assertEqual(response.context["project"].id, self.project.id)

    def test_deleting_lands_on_the_projects_list(self):
        response = self.client.post(f"/projects/{self.project.id}/delete")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/projects")
