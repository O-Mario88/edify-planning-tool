"""Who sees what on Project Monitoring, and what they may do with it.

Owner, 2026-09-21: CCEO, Programme Lead and Impact Assessment monitor the
coordinator's and the partners' project work, read only — and "the CCEO and PL
can only see the schools they added to the project but not schools added by
other cceos and pls".
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.monitoring import project_monitoring, sees_whole_project
from apps.schools.models import School


def _user(uid, role, name):
    user = User.objects.create_user(
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(
        id=f"{uid}-sp", user=user, title=role, country="Uganda"
    )


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(name="PM Region")
        cls.district = District.objects.create(name="PM District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="PM SC", district=cls.district)

        cls.mine_user, cls.mine = _user("pm-cceo", "CCEO", "PM CCEO")
        cls.other_user, cls.other = _user("pm-other", "CCEO", "PM Other CCEO")
        cls.lead_user, cls.lead = _user("pm-pl", "ProgramLead", "PM Lead")
        cls.ia_user, cls.ia = _user("pm-ia", "ImpactAssessment", "PM IA")
        cls.coordinator_user, cls.coordinator = _user(
            "pm-coord", "ProjectCoordinator", "PM Coordinator"
        )

        cls.project = Project.objects.create(
            name="PM Literacy Project",
            code="SP-PM",
            category="literacy",
            status="active",
            intervention="learning_environment",
            manager_staff_id=cls.coordinator.id,
        )
        cls.my_school = cls._school("PM-MINE", cls.mine)
        cls.their_school = cls._school("PM-THEIRS", cls.other)
        cls._enrol(cls.my_school, cls.mine_user)
        cls._enrol(cls.their_school, cls.other_user)
        cls._activity(cls.my_school, "in_school_training")
        cls._activity(cls.my_school, "school_visit", status="completed")
        cls._activity(cls.their_school, "in_school_training")
        cls._activity(cls.their_school, "in_school_training")

    @classmethod
    def _school(cls, code, owner):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
            account_owner_id=owner.id,
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    @classmethod
    def _enrol(cls, school, by_user):
        return ProjectSchoolAssignment.objects.create(
            project_id=cls.project.id, school=school, assigned_by=by_user.user_id
        )

    @classmethod
    def _activity(cls, school, activity_type, status="scheduled"):
        when = date.today() + timedelta(days=5)
        return Activity.objects.create(
            activity_type=activity_type,
            school=school,
            project_id=cls.project.id,
            fy=cls.fy,
            quarter="Q1",
            status=status,
            planned_date=when,
        )


class TheLensIsWhoAddedTheSchoolTest(_Fixture):
    def test_a_cceo_sees_only_the_schools_they_added(self):
        result = project_monitoring(self.mine_user, fy=self.fy)
        self.assertEqual(result.projects, 1)
        row = result.rows[0]
        self.assertEqual(row.my_schools, 1)
        self.assertEqual(row.trainings_scheduled, 1, "not the other officer's two")
        self.assertEqual(row.visits_scheduled, 1)
        self.assertEqual(row.visits_completed, 1)

    def test_another_officers_enrolments_are_not_borrowed(self):
        result = project_monitoring(self.other_user, fy=self.fy)
        row = result.rows[0]
        self.assertEqual(row.my_schools, 1)
        self.assertEqual(row.trainings_scheduled, 2)
        self.assertEqual(row.visits_scheduled, 0, "the visit is at the other school")

    def test_a_programme_lead_reads_their_own_contribution_too(self):
        self.assertFalse(sees_whole_project(self.lead_user))
        result = project_monitoring(self.lead_user, fy=self.fy)
        self.assertEqual(result.projects, 0, "the Lead has added no school yet")

    def test_impact_assessment_reads_the_project_whole(self):
        self.assertTrue(sees_whole_project(self.ia_user))
        result = project_monitoring(self.ia_user, fy=self.fy)
        row = result.rows[0]
        self.assertEqual(row.my_schools, 2)
        self.assertEqual(row.trainings_scheduled, 3)
        self.assertEqual(row.visits_scheduled, 1)

    def test_the_lens_note_says_which_question_the_numbers_answer(self):
        self.assertIn(
            "Only the schools you added",
            project_monitoring(self.mine_user, fy=self.fy).lens_note,
        )
        self.assertIn(
            "Every school",
            project_monitoring(self.ia_user, fy=self.fy).lens_note,
        )


class TheRowNamesWhoIsInControlTest(_Fixture):
    def test_the_coordinator_and_partners_are_named(self):
        row = project_monitoring(self.ia_user, fy=self.fy).rows[0]
        self.assertEqual(row.coordinator, "PM Coordinator")
        self.assertEqual(row.partners, [])

    def test_a_cancelled_activity_is_not_planned_work(self):
        self._activity(self.my_school, "in_school_training", status="cancelled")
        row = project_monitoring(self.mine_user, fy=self.fy).rows[0]
        self.assertEqual(row.trainings_scheduled, 1)

    def test_nothing_planned_says_so_rather_than_showing_a_rate(self):
        empty = Project.objects.create(
            name="PM Empty Project", category="literacy", status="active"
        )
        ProjectSchoolAssignment.objects.create(
            project=empty, school=self.my_school, assigned_by=self.mine_user.user_id
        )
        rows = {
            row.name: row for row in project_monitoring(self.mine_user, fy=self.fy).rows
        }
        self.assertEqual(
            rows["PM Empty Project"].completion_label, "Nothing planned yet"
        )


class ThePageIsReadOnlyTest(_Fixture):
    def test_oversight_offers_no_write_control(self):
        self.client.force_login(self.ia_user)
        response = self.client.get("/projects/monitoring")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Project Monitoring", html)
        self.assertIn("PM Literacy Project", html)
        self.assertIn("Read only", html)
        # No door to scheduling or partner assignment from this page.
        self.assertNotIn("/planning/schedule-modal", html)
        self.assertNotIn("assign-partner-modal", html)

    def test_a_cceo_reads_the_schools_they_added(self):
        """Owner, 2026-09-24: "Users want to see the schools they have
        assigned to the project so make sure the tables for each of the
        project they have assigned schools to is available to them." The CCEO
        had lost the page on 2026-09-23 while still adding schools."""
        self.client.force_login(self.mine_user)
        response = self.client.get("/projects/monitoring")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("PM Literacy Project", html)
        self.assertIn(f'data-project-school="{self.my_school.id}"', html)
        self.assertNotIn(f'data-project-school="{self.their_school.id}"', html)
        self.assertIn("Read only", html)
        for door in (
            "/planning/schedule-modal",
            "/projects/planning/bulk-partner",
            "/projects/monitoring/withdraw",
            "/projects/monitoring/resolve",
        ):
            with self.subTest(door=door):
                self.assertNotIn(door, html)

    def test_it_opens_for_impact_assessment(self):
        self.client.force_login(self.ia_user)
        response = self.client.get("/projects/monitoring")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PM Literacy Project", response.content.decode())

    def test_a_post_is_refused(self):
        self.client.force_login(self.lead_user)
        response = self.client.post("/projects/monitoring", {})
        self.assertIn(response.status_code, (403, 405))

    def test_a_partner_cannot_open_it(self):
        partner_user = User.objects.create_user(
            email="pm-partner@edify.org",
            name="PM Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            password="x",
            is_active=True,
        )
        self.client.force_login(partner_user)
        response = self.client.get("/projects/monitoring")
        self.assertIn(response.status_code, (302, 403))
