"""Both field roles enrol a school into a coordinator's project.

Owner, 2026-09-16: "the cceo and PL should be able to assign schools to
projects created by the project coordinator either using the add to project
button on the each school or bulk assign like the way schools are bulk
assigned to cluster schools."

Two roles, two routes, so four paths — and the Programme Lead's are the ones
worth pinning. A PL's own `StaffSchoolAssignment` rows are usually empty: the
schools they answer for belong to the CCEOs they supervise, which
`apps.core.scoping` deliberately keeps in a separate team lens. Every
enrolment gate reads the direct portfolio, so a PL who holds no school
directly could see the project in the dropdown and still be refused on save.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.geography.models import District, Region
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School


class _Roles(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Roles Region")
        cls.district = District.objects.create(name="Roles District", region=cls.region)

        def _school(school_id, name):
            return School.objects.create(
                school_id=school_id,
                name=name,
                region=cls.region,
                district=cls.district,
                school_type="client",
            )

        # The CCEO's own two schools, and one held by nobody in this story.
        cls.cceo_school = _school("ROLE-1", "CCEO Held School")
        cls.cceo_second = _school("ROLE-2", "CCEO Second School")
        cls.outsider = _school("ROLE-9", "Another Portfolio School")

        cls.coordinator = User.objects.create(
            id="roles-pc",
            email="roles-pc@edify.org",
            name="Roles Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        cls.coordinator_profile = StaffProfile.objects.create(
            id="roles-pc-staff", user=cls.coordinator, staff_number="PC-ROLES"
        )
        cls.cceo = User.objects.create(
            id="roles-cceo",
            email="roles-cceo@edify.org",
            name="Roles CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.cceo_profile = StaffProfile.objects.create(
            id="roles-cceo-staff", user=cls.cceo, staff_number="CCEO-ROLES"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_profile, school_id=cls.cceo_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_profile, school_id=cls.cceo_second.id
        )

        # The Programme Lead supervising that CCEO, holding no school of their
        # own — the ordinary shape of the role.
        cls.pl = User.objects.create(
            id="roles-pl",
            email="roles-pl@edify.org",
            name="Roles Programme Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
            status="active",
        )
        cls.pl_profile = StaffProfile.objects.create(
            id="roles-pl-staff", user=cls.pl, staff_number="PL-ROLES"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_profile, supervisee=cls.cceo_profile
        )

        # Somebody else's school, so "everything is allowed" cannot pass.
        cls.other_cceo = User.objects.create(
            id="roles-other",
            email="roles-other@edify.org",
            name="Other CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.other_profile = StaffProfile.objects.create(
            id="roles-other-staff", user=cls.other_cceo, staff_number="CCEO-OTHER"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.other_profile, school_id=cls.outsider.id
        )

        cls.project = Project.objects.create(
            name="Roles Project",
            code="SP-ROLES-1",
            category="intervention_specific",
            status="active",
            manager_staff_id=cls.coordinator_profile.id,
        )

    def _enrolled(self, school):
        return ProjectSchoolAssignment.objects.filter(
            project=self.project, school=school
        ).exists()


class TheCceoEnrolsBothWaysTest(_Roles):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.cceo)

    def test_the_per_school_drawer_enrols(self):
        response = self.client.post(
            f"/schools/{self.cceo_school.id}/assign-to-project",
            {"project_id": self.project.id, "notes": "Pilot cohort"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._enrolled(self.cceo_school))

    def test_the_directory_bulk_assign_enrols(self):
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "school_ids": f"{self.cceo_school.id},{self.cceo_second.id}",
                "project_id": self.project.id,
                "override_reason": "Pilot cohort",
            },
        )
        self.assertTrue(self._enrolled(self.cceo_school))
        self.assertTrue(self._enrolled(self.cceo_second))


class TheProgrammeLeadEnrolsBothWaysTest(_Roles):
    """The PL holds no school directly; the schools are their CCEO's."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.pl)

    def test_the_project_is_offered_to_the_lead(self):
        from apps.projects.scoping import assignable_projects

        self.assertIn(self.project.id, {p.id for p in assignable_projects(self.pl)})

    def test_the_per_school_drawer_enrols_a_team_school(self):
        response = self.client.post(
            f"/schools/{self.cceo_school.id}/assign-to-project",
            {"project_id": self.project.id, "notes": "Lead enrolled it"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._enrolled(self.cceo_school))

    def test_the_directory_bulk_assign_enrols_team_schools(self):
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "school_ids": f"{self.cceo_school.id},{self.cceo_second.id}",
                "project_id": self.project.id,
                "override_reason": "Lead enrolled them",
            },
        )
        self.assertTrue(self._enrolled(self.cceo_school))
        self.assertTrue(self._enrolled(self.cceo_second))

    def test_a_school_outside_the_team_is_still_refused(self):
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "school_ids": str(self.outsider.id),
                "project_id": self.project.id,
                "override_reason": "Not mine",
            },
        )
        self.assertFalse(self._enrolled(self.outsider))


class TheCoordinatorWorksFromTheProjectCardTest(_Roles):
    """Owner, 2026-09-16: "the projects created should all be in their own
    cards so that it is easy for the project coordinator to look at which
    schools belong to which project and to be able to either schedule
    activities or assign to partner"."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.coordinator)
        ProjectSchoolAssignment.objects.get_or_create(
            project=self.project,
            school=self.cceo_school,
            defaults={"assigned_by": self.coordinator.id},
        )

    def test_every_project_gets_a_card_that_opens_on_its_schools(self):
        html = self.client.get("/projects").content.decode()
        self.assertIn(f'data-project-card="{self.project.id}"', html)
        self.assertIn("Roles Project", html)
        # The roster is fetched when the card opens, not with the page: the
        # card ships the request, not the rows.
        self.assertIn(f'hx-get="/partials/projects/{self.project.id}/schools"', html)
        self.assertIn("Loading the schools in this project", html)

    def test_the_card_lists_the_schools_with_both_actions(self):
        response = self.client.get(
            f"/partials/projects/{self.project.id}/schools",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(self.cceo_school.name, html)
        # Both actions stamp the project on the work (2026-09-24): scheduling
        # carries the project, and the partner handover is the project's own
        # rather than the generic school-support drawer, which files none.
        enrolment = ProjectSchoolAssignment.objects.get(
            project=self.project, school=self.cceo_school
        )
        self.assertIn(
            f"/planning/schedule-modal?school_id={self.cceo_school.id}"
            f"&amp;project_id={self.project.id}",
            html,
        )
        self.assertIn(
            f"/projects/planning/bulk-partner?assignments={enrolment.id}", html
        )
        self.assertNotIn("/planning/assign-partner-modal", html)
        # A school in nobody's project is not listed by it.
        self.assertNotIn(self.outsider.name, html)

    def test_the_coordinator_may_assign_a_school_to_a_partner(self):
        from apps.core.permissions import RolePermissionService

        self.assertTrue(RolePermissionService.can_assign_to_partner(self.coordinator))
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={self.cceo_school.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access Denied", response.content.decode())
