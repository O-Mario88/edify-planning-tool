"""Schools assigned to a project, of the person's project ceilings.

Owner, 2026-10-06, on the Planned and remaining table: "fix the summary above
especially the schools assigned to project. it should calculate all the schools
the user added to the project against the project general ceiling (all project
ceilings put together). Right now it is showing remaining all the schools
remaining. Remaining column should show the remaining balance to hit the
ceiling for all the target for the project."

The line was every school held against those in a project: 45 planned of
1,147, 1,102 remaining, for somebody whose ceilings asked for a few dozen.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.fy import get_operational_fy
from apps.planning import planning_monitor, readiness
from apps.planning.test_planning_readiness import officer, school
from apps.projects import capacity, services
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.test_project_school_enrolment import _Fixture
from apps.schools.models import School


class TheArithmeticTest(SimpleTestCase):
    def _figures(self, *, ceiling, added, schools=()):
        person = officer(schools or [school(1, in_project=True)])
        person.project_ceiling = ceiling
        person.project_added = added
        return readiness.person_readiness(person)

    def test_planned_is_what_the_person_added_and_target_their_ceilings(self):
        line = self._figures(ceiling=40, added=25).project_assignment

        self.assertEqual((line.planned, line.target, line.remaining), (25, 40, 15))
        self.assertEqual(line.percent, 62)

    def test_remaining_is_not_every_school_held_that_is_in_no_project(self):
        held = [school(n) for n in range(200)]
        figures = self._figures(ceiling=10, added=4, schools=held)

        self.assertEqual(figures.project_assignment.remaining, 6)
        self.assertEqual(figures.schools_total, 200)

    def test_a_ceiling_reached_asks_nothing_more(self):
        line = self._figures(ceiling=12, added=12).project_assignment

        self.assertEqual((line.remaining, line.percent, line.over), (0, 100, 0))

    def test_nobody_with_no_ceiling_is_asked_for_project_schools(self):
        line = self._figures(ceiling=0, added=3).project_assignment

        self.assertFalse(line.required)
        self.assertEqual((line.planned, line.remaining, line.percent), (3, 0, 100))

    def test_one_person_s_extra_does_not_close_another_s_gap(self):
        full = self._figures(ceiling=5, added=5)
        short = self._figures(ceiling=10, added=2)

        line = (full + short).project_assignment

        self.assertEqual((line.planned, line.target, line.remaining), (7, 15, 8))

    def test_the_inventory_still_says_how_many_schools_held_are_in_a_project(self):
        held = [school(1, in_project=True), school(2), school(3)]
        figures = self._figures(ceiling=10, added=1, schools=held)

        self.assertEqual((figures.project_assigned, figures.project_total), (1, 3))
        self.assertEqual(figures.as_dict()["project_assignment"]["schools_held"], 3)
        self.assertEqual(readiness.problems(figures), [])


class CountedFromTheDatabaseTest(_Fixture):
    """The ceilings are ProjectStaffCapacity rows and a place is used by an
    enrolment the person made: the Project Capacity page's own figures."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fy = str(get_operational_fy())
        cls.second = Project.objects.create(
            name="Second Project",
            code="SP-ENR-3",
            category="intervention_specific",
            status="active",
            manager_staff_id=cls.coordinator_profile.id,
        )
        cls.extra = [
            School.objects.create(
                school_id=f"ENR-X{n}",
                name=f"Extra School {n}",
                region=cls.region,
                district=cls.district,
                school_type="client",
                account_owner_id=cls.cceo_profile.id,
            )
            for n in range(3)
        ]
        for extra in cls.extra:
            StaffSchoolAssignment.objects.create(
                staff=cls.cceo_profile, school_id=extra.id
            )
        School.objects.filter(id=cls.school.id).update(
            account_owner_id=cls.cceo_profile.id
        )

    def _own(self):
        person = planning_monitor.own_monitor(self.cceo, self.fy)
        return person, readiness.person_readiness(person).project_assignment

    def _ceiling(self, project, maximum):
        return capacity.set_capacity(
            project.id, self.cceo_profile.id, maximum, self.coordinator, create=True
        )

    def _add(self, project, school):
        services.assign_school(project.id, {"schoolId": school.school_id}, self.cceo)

    def test_the_target_is_every_ceiling_put_together(self):
        self._ceiling(self.project, 10)
        self._ceiling(self.second, 6)

        person, line = self._own()

        self.assertEqual(person.project_ceiling, 16)
        self.assertEqual((line.planned, line.target, line.remaining), (0, 16, 16))

    def test_planned_is_the_schools_the_person_added(self):
        self._ceiling(self.project, 10)
        self._ceiling(self.second, 6)
        self._add(self.project, self.school)
        self._add(self.project, self.extra[0])
        self._add(self.second, self.extra[1])

        person, line = self._own()

        self.assertEqual(person.project_added, 3)
        self.assertEqual((line.planned, line.target, line.remaining), (3, 16, 13))

    def test_it_is_the_allocation_table_added_up(self):
        self._ceiling(self.project, 10)
        self._ceiling(self.second, 6)
        self._add(self.project, self.school)
        self._add(self.second, self.extra[1])

        _person, line = self._own()
        table = capacity.allocations_for_staff(self.cceo_profile.id)

        self.assertEqual(line.target, sum(a.maximum for a in table))
        self.assertEqual(line.planned, sum(a.assigned for a in table))
        self.assertEqual(line.remaining, sum(a.remaining for a in table))

    def test_a_school_somebody_else_added_is_not_the_person_s(self):
        self._ceiling(self.project, 10)
        ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=self.extra[2],
            assigned_by=self.coordinator.id,
        )

        person, line = self._own()

        self.assertEqual(line.planned, 0)
        # It is still one of the person's schools that is in a project.
        self.assertEqual(sum(1 for s in person.schools if s.in_project), 1)

    def test_a_withdrawn_school_gives_its_place_back(self):
        self._ceiling(self.project, 10)
        self._add(self.project, self.school)
        self._add(self.project, self.extra[0])
        self.assertEqual(self._own()[1].remaining, 8)

        services.remove_school(
            self.project.id,
            self.school.id,
            self.cceo,
            reason="Added to the wrong project.",
        )

        person, line = self._own()
        self.assertEqual((line.planned, line.remaining), (1, 9))
        self.assertEqual(
            [s.name for s in person.schools if s.project_places], ["Extra School 0"]
        )

    def test_the_list_behind_planned_is_the_schools_the_person_added(self):
        self._ceiling(self.project, 10)
        self._add(self.project, self.school)
        ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=self.extra[2],
            assigned_by=self.coordinator.id,
        )

        person, line = self._own()
        listed = planning_monitor.list_schools([person], "project_added")

        self.assertEqual([s.name for s in listed], ["Enrol School"])
        self.assertEqual(len(listed), line.planned)

    def test_the_planning_monitor_reads_the_same_two_numbers(self):
        self._ceiling(self.project, 10)
        self._add(self.project, self.school)
        director = User.objects.create(
            id="enrol-cd",
            email="enrol-cd@edify.org",
            name="Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
            status="active",
        )
        StaffProfile.objects.create(id="enrol-cd-staff", user=director)

        monitor = planning_monitor.planning_monitor(director, fy=self.fy)
        rows = {row.name: row for lead in monitor["leads"] for row in lead.officers}

        self.assertEqual(rows["Field CCEO"].project_ceiling, 10)
        self.assertEqual(rows["Field CCEO"].project_added, 1)


class OnMyPlanTest(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        School.objects.filter(id=cls.school.id).update(
            account_owner_id=cls.cceo_profile.id
        )

    def test_the_row_shows_added_of_ceiling_and_what_remains(self):
        capacity.set_capacity(
            self.project.id, self.cceo_profile.id, 10, self.coordinator, create=True
        )
        services.assign_school(
            self.project.id, {"schoolId": self.school.school_id}, self.cceo
        )
        self.client.force_login(self.cceo)

        payload = self.client.get("/my-plan?format=readiness-json").json()
        line = payload["readiness"]["project_assignment"]

        self.assertEqual(
            (line["planned"], line["target"], line["remaining"]), (1, 10, 9)
        )

        page = self.client.get("/my-plan")
        self.assertContains(page, "Schools assigned to a project")
        self.assertContains(page, "Your project ceilings add up to 10 schools")
        self.assertContains(page, 'data-plan-count="project_added"')
        self.assertContains(page, "/projects/monitoring#my-allocations-title")
