"""Add to Project, and the Project Coordinator's portfolio (2026-09-15 brief).

Adding a school to a project is a registry act on the SCHOOL: the officer who
owns it records that it takes part, and the Project Coordinator plans the
project's work for it. The school's own ownership, district and cluster do not
change, and the adder gains no authority over the project.

What was broken: the drawer and the service both required the person adding
the school to be assigned to the project, so the officer who owned the school
was offered no projects and refused if they tried.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.notifications.models import Notification
from apps.projects import services as project_services
from apps.projects.models import (
    Project,
    ProjectSchoolAssignment,
    ProjectSchoolEnrollmentHistory,
)
from apps.projects.portfolio import portfolio_rows
from apps.projects.portfolio_todos import project_school_planning_todos
from apps.schools.models import School

FY = get_operational_fy()


class ProjectFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Project Region")
        self.district = District.objects.create(
            name="Project District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Project SC", district=self.district
        )
        self.kenya = Region.objects.create(name="Kenya Region", country="Kenya")
        self.kenya_district = District.objects.create(
            name="Kenya District", region=self.kenya
        )

        self.coordinator_user = self._user("pj-pc@edify.org", "ProjectCoordinator")
        self.coordinator = StaffProfile.objects.create(
            user=self.coordinator_user, country="Uganda"
        )
        self.cceo_user = self._user("pj-cceo@edify.org", "CCEO")
        self.cceo = StaffProfile.objects.create(user=self.cceo_user, country="Uganda")
        self.other_cceo_user = self._user("pj-other@edify.org", "CCEO")
        self.other_cceo = StaffProfile.objects.create(
            user=self.other_cceo_user, country="Uganda"
        )
        self.ia_user = self._user("pj-ia@edify.org", "ImpactAssessment")
        StaffProfile.objects.create(user=self.ia_user, country="Uganda")

        self.cluster = Cluster.objects.create(
            name="Project Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
            responsible_staff_id=self.cceo.id,
        )
        self.school = self._school("PJ-1", "Project Primary", self.cceo)
        self.other_school = self._school("PJ-2", "Other Primary", self.other_cceo)

        self.project = Project.objects.create(
            name="EdTech Pilot",
            category="pilot",
            status="active",
            manager_staff_id=self.coordinator.id,
        )
        self.ungoverned = Project.objects.create(
            name="Ungoverned Project", category="pilot", status="active"
        )
        self.closed = Project.objects.create(
            name="Closed Project",
            category="pilot",
            status="closed",
            manager_staff_id=self.coordinator.id,
        )

    def _user(self, email, role):
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0].title(),
            roles=[role],
            active_role=role,
            password="x",
        )

    def _school(self, code, name, owner, region=None, district=None):
        school = School.objects.create(
            school_id=code,
            name=name,
            region=region or self.region,
            district=district or self.district,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_name_raw=owner.user.name,
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def _add(self, principal=None, project=None, school=None, **extra):
        return project_services.assign_school(
            (project or self.project).id,
            {
                "schoolId": (school or self.school).school_id,
                "reason": "Taking part in the pilot cohort.",
                **extra,
            },
            principal or self.cceo_user,
        )


class AddToProjectTest(ProjectFixture):
    def test_the_owning_officer_may_add_their_own_school(self):
        before = School.objects.values(
            "account_owner_id", "district_id", "cluster_id"
        ).get(id=self.school.id)
        self._add()
        assignment = ProjectSchoolAssignment.objects.get(
            project=self.project, school=self.school
        )
        self.assertEqual(assignment.assigned_by, self.cceo_user.id)
        # The school's own record is untouched: owner, district and cluster.
        after = School.objects.values(
            "account_owner_id", "district_id", "cluster_id"
        ).get(id=self.school.id)
        self.assertEqual(after, before)
        self.assertEqual(after["account_owner_id"], self.cceo.id)

    def test_a_school_outside_the_adders_portfolio_is_refused(self):
        with self.assertRaises(Forbidden):
            self._add(school=self.other_school)
        self.assertFalse(ProjectSchoolAssignment.objects.exists())

    def test_a_duplicate_enrolment_is_blocked(self):
        self._add()
        self._add()  # idempotent: get_or_create, not a second row
        self.assertEqual(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).count(),
            1,
        )

    def test_a_closed_project_and_one_without_a_coordinator_are_refused(self):
        with self.assertRaises(BadRequest):
            self._add(project=self.closed)
        with self.assertRaisesMessage(BadRequest, "nobody assigned to plan its work"):
            self._add(project=self.ungoverned)

    def test_a_closed_school_takes_no_project_work(self):
        School.objects.filter(id=self.school.id).update(
            operational_status="permanently_closed"
        )
        with self.assertRaises((BadRequest, Forbidden)):
            self._add()

    def test_a_project_in_another_country_is_refused(self):
        kenya_school = self._school(
            "PJ-K",
            "Kenya Primary",
            self.cceo,
            region=self.kenya,
            district=self.kenya_district,
        )
        with self.assertRaisesMessage(BadRequest, "runs in Uganda"):
            self._add(school=kenya_school)

    def test_the_eligible_list_offers_governed_open_projects_only(self):
        options = project_services.projects_open_for_enrolment(
            self.cceo_user, self.school
        )
        names = {p.name for p in options}
        self.assertIn("EdTech Pilot", names)
        self.assertNotIn("Closed Project", names)
        self.assertNotIn("Ungoverned Project", names)
        # Already enrolled: no longer offered.
        self._add()
        self.assertNotIn(
            "EdTech Pilot",
            {
                p.name
                for p in project_services.projects_open_for_enrolment(
                    self.cceo_user, self.school
                )
            },
        )

    def test_the_school_focus_rule_holds(self):
        core_only = Project.objects.create(
            name="Core Only Project",
            category="pilot",
            status="active",
            manager_staff_id=self.coordinator.id,
            school_focus="core",
        )
        self.assertNotIn(
            core_only.id,
            {
                p.id
                for p in project_services.projects_open_for_enrolment(
                    self.cceo_user, self.school
                )
            },
        )
        with self.assertRaisesMessage(BadRequest, "limited to Core Schools"):
            self._add(project=core_only)

    def test_the_drawer_offers_projects_and_adds_the_school(self):
        self.client.force_login(self.cceo_user)
        url = f"/schools/{self.school.id}/assign-to-project"
        drawer = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(drawer, "EdTech Pilot")
        self.assertNotContains(drawer, "Ungoverned Project")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                url,
                {
                    "project_id": self.project.id,
                    "participation_type": "cohort",
                    "notes": "Joins the pilot cohort.",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).exists()
        )
        # The coordinator is told, and the act is audited with previous/new.
        self.assertTrue(
            Notification.objects.filter(
                source_event_type="project_school_added",
                recipient_id=self.coordinator_user.id,
            ).exists()
        )
        row = AuditLog.objects.get(
            action="school.assign_project", subject_id=self.school.id
        )
        self.assertFalse(row.payload["previous"]["enrolled"])
        self.assertTrue(row.payload["new"]["enrolled"])
        self.assertEqual(row.payload["new"]["schoolOwnerId"], self.cceo.id)


class CoordinatorPortfolioTest(ProjectFixture):
    def test_the_portfolio_lists_the_school_with_its_derived_statuses(self):
        self._add()
        rows = portfolio_rows(self.project)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["school_name"], "Project Primary")
        self.assertEqual(row["school_owner"], self.cceo_user.name)
        self.assertEqual(row["added_by"], self.cceo_user.name)
        self.assertTrue(row["needs_planning"])
        self.assertEqual(row["visit_status"], "No Visit Planned")
        self.assertEqual(row["partner_status"], "Not assigned")

        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate() + datetime.timedelta(days=5),
            scheduled_date=timezone.now() + datetime.timedelta(days=5),
            status="scheduled",
            responsible_staff_id=self.coordinator.id,
            delivery_type="staff",
        )
        row = portfolio_rows(self.project)[0]
        self.assertFalse(row["needs_planning"])
        self.assertIn("1 planned", row["planning_status"])
        self.assertEqual(row["visit_status"], "Scheduled for Visit")

    def test_the_coordinator_gets_a_planning_todo_that_closes(self):
        self._add()
        today = timezone.localdate()
        rows = project_school_planning_todos(
            self.coordinator_user, "ProjectCoordinator", today
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("Plan Activities", rows[0]["title"])
        self.assertIn("Project Primary", rows[0]["description"])
        # Not the officer who added the school: planning is the coordinator's.
        self.assertEqual(
            project_school_planning_todos(self.cceo_user, "CCEO", today), []
        )
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=today + datetime.timedelta(days=5),
            status="scheduled",
            responsible_staff_id=self.coordinator.id,
            delivery_type="staff",
        )
        self.assertEqual(
            project_school_planning_todos(
                self.coordinator_user, "ProjectCoordinator", today
            ),
            [],
        )

    def test_the_project_page_shows_the_portfolio(self):
        self._add()
        self.client.force_login(self.coordinator_user)
        page = self.client.get(f"/projects/{self.project.id}")
        self.assertContains(page, "Project Primary")
        self.assertContains(page, "Added by")
        self.assertContains(page, "awaiting planning")

    def test_removing_a_school_keeps_the_history_and_the_work(self):
        self._add()
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate(),
            status="completed",
            responsible_staff_id=self.coordinator.id,
            delivery_type="staff",
        )
        project_services.remove_school(
            self.project.id,
            self.school.school_id,
            self.coordinator_user,
            reason="Left the cohort.",
        )
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).exists()
        )
        history = ProjectSchoolEnrollmentHistory.objects.get(
            project=self.project, school=self.school
        )
        self.assertEqual(history.removal_reason, "Left the cohort.")
        self.assertEqual(history.activities_delivered, 1)
        activity.refresh_from_db()
        self.assertEqual(activity.project_id, self.project.id)
        self.assertTrue(
            AuditLog.objects.filter(action="project.school_removed").exists()
        )
        # It can join again afterwards.
        self._add()
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.project, school=self.school
            ).exists()
        )
