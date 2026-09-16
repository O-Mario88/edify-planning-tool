"""Enrolling a school into a Special Project (owner, 2026-09-16).

The Project Coordinator creates the cohort; the CCEO or Programme Lead who
holds the school puts it in. Before this the coordinator's own scope was
derived from the schools already enrolled, so no first enrolment was possible
from any surface, and the school-side drawer offered a CCEO only the projects
they themselves managed — an empty dropdown.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.exceptions import Forbidden
from apps.geography.models import District, Region
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.scoping import assignable_projects, scoped_projects
from apps.projects.services import assign_school
from apps.schools.models import School


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Enrol Region")
        cls.district = District.objects.create(name="Enrol District", region=cls.region)
        cls.school = School.objects.create(
            school_id="ENR-1",
            name="Enrol School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.other_school = School.objects.create(
            school_id="ENR-2",
            name="Someone Else's School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

        cls.coordinator = User.objects.create(
            id="enrol-pc",
            email="enrol-pc@edify.org",
            name="Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        cls.coordinator_profile = StaffProfile.objects.create(
            id="enrol-pc-staff", user=cls.coordinator, staff_number="PC-ENR"
        )
        cls.cceo = User.objects.create(
            id="enrol-cceo",
            email="enrol-cceo@edify.org",
            name="Field CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.cceo_profile = StaffProfile.objects.create(
            id="enrol-cceo-staff", user=cls.cceo, staff_number="CCEO-ENR"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_profile, school_id=cls.school.id
        )

        # The coordinator's brand new cohort: no schools yet.
        cls.project = Project.objects.create(
            name="Enrol Project",
            code="SP-ENR-1",
            category="intervention_specific",
            status="active",
            manager_staff_id=cls.coordinator_profile.id,
        )
        cls.paused = Project.objects.create(
            name="Paused Project",
            code="SP-ENR-2",
            category="intervention_specific",
            status="paused",
            manager_staff_id=cls.coordinator_profile.id,
        )


class TheSchoolOwnerEnrolsItTest(_Fixture):
    def test_the_cceo_is_offered_the_coordinators_project(self):
        offered = {p.id for p in assignable_projects(self.cceo)}
        self.assertIn(self.project.id, offered)
        # A paused project accepts no new work, so it is never offered.
        self.assertNotIn(self.paused.id, offered)

    def test_the_cceo_may_enrol_their_own_school(self):
        result = assign_school(
            self.project.id,
            {"schoolId": self.school.school_id, "reason": "Pilot cohort"},
            self.cceo,
        )
        self.assertEqual(result["schoolId"], self.school.school_id)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).exists()
        )

    def test_a_school_outside_the_portfolio_is_still_refused(self):
        with self.assertRaises(Forbidden) as caught:
            assign_school(
                self.project.id,
                {"schoolId": self.other_school.school_id, "reason": "x"},
                self.cceo,
            )
        self.assertIn("not in your portfolio", str(caught.exception))

    def test_the_first_enrolment_unblocks_the_coordinators_scope(self):
        """The deadlock: the coordinator's portfolio comes from the schools
        already enrolled, so it stays empty until somebody else enrols one."""
        self.assertEqual(
            list(scoped_projects(self.coordinator)), [self.project, self.paused]
        )
        assign_school(
            self.project.id,
            {"schoolId": self.school.school_id, "reason": "Pilot cohort"},
            self.cceo,
        )
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(self.coordinator)
        self.assertIn(self.school.id, scope.school_ids)


class TheDrawerOffersThemTest(_Fixture):
    def test_the_drawer_lists_the_coordinators_project_for_a_cceo(self):
        client = Client()
        client.force_login(self.cceo)
        response = client.get(
            f"/schools/{self.school.id}/assign-to-project",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        offered = {p.id for p in response.context["projects"]}
        self.assertIn(self.project.id, offered)
        self.assertNotIn(self.paused.id, offered)
        # Whose cohort it is, so a country-wide list stays readable.
        self.assertContains(response, "Coordinator")


class TheBulkDrawerAddsAWholeCohortTest(_Fixture):
    """The Cluster side had a searchable checklist; the Project side had a
    one-at-a-time `<select>`, so a thirty-school cohort took thirty round
    trips (owner, 2026-09-16)."""

    def setUp(self):
        super().setUp()
        self.second = School.objects.create(
            school_id="ENR-3",
            name="Second Enrol School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=self.second.id
        )
        # One school already in, so the project is inside the CCEO's read
        # scope and its detail page is reachable.
        assign_school(
            self.project.id,
            {"schoolId": self.school.school_id, "reason": "Pilot cohort"},
            self.cceo,
        )
        self.client = Client()
        self.client.force_login(self.cceo)

    def test_the_drawer_offers_the_portfolio_minus_the_cohort(self):
        response = self.client.get(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        offered = {s.id for s in response.context["schools"]}
        self.assertEqual(offered, {self.second.id})
        # Never another owner's school, and never one already enrolled.
        self.assertNotIn(self.other_school.id, offered)

    def test_ticking_schools_enrols_them_all(self):
        response = self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [self.second.id], "reason": "Pilot cohort"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.second
            ).exists()
        )
        self.assertIn(
            f"project-schools-updated-{self.project.id}",
            response.headers["HX-Trigger"],
        )

    def test_a_school_outside_the_portfolio_is_dropped(self):
        self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [self.other_school.id], "reason": "x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.other_school
            ).exists()
        )

    def test_a_school_already_in_the_cohort_is_reported_not_duplicated(self):
        response = self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [self.school.id, self.second.id], "reason": "Pilot"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "1 already in the cohort")
        self.assertEqual(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).count(),
            1,
        )


class TheCoordinatorSeesTheirCohortTest(_Fixture):
    """Owner, 2026-09-16: "all the schools assigned to the project coordinator
    projects should show up on the project coordinator planning page and
    school page (for his portfolio)". Both read the same derived scope, so the
    thing to pin is that an enrolment reaches them."""

    def setUp(self):
        super().setUp()
        assign_school(
            self.project.id,
            {"schoolId": self.school.school_id, "reason": "Pilot cohort"},
            self.cceo,
        )
        self.client = Client()
        self.client.force_login(self.coordinator)

    def test_the_school_is_in_the_coordinators_directory(self):
        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.school.name)
        # Still only their own cohort — the directory is not widened.
        self.assertNotContains(response, self.other_school.name)

    def test_the_planning_queue_groups_the_cohort_by_project(self):
        response = self.client.get("/projects/planning")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.school.name)
        groups = response.context["row_groups"]
        self.assertEqual([group["project_name"] for group in groups], ["Enrol Project"])


class APausedProjectTakesNothingInBulkTest(_Fixture):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.cceo)

    def test_the_batch_is_refused_once_not_once_per_school(self):
        # Reachable because the paused project already holds a school: the
        # CCEO can read it, and the drawer has to say no rather than half-do
        # the batch.
        ProjectSchoolAssignment.objects.create(project=self.paused, school=self.school)
        second = School.objects.create(
            school_id="ENR-4",
            name="Late Arrival",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_profile, school_id=second.id
        )
        response = self.client.post(
            f"/projects/{self.paused.id}/schools/bulk-assign-drawer",
            {"school_ids": [second.id], "reason": "x"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "no new schools can be added")
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(
                project=self.paused, school=second
            ).exists()
        )
