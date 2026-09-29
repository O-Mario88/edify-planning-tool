"""Bulk withdraw from a project's profile (owner, 2026-09-29).

"Allow the staff to bulk withdraw schools from project or partner assignment.
They can go to the project profile ... and check all the schools they want to
withdraw and be able to withdraw."

Each school is the single Withdraw School repeated: only before its project
work begins, only by the staff member whose allocation it uses or the
coordinator, with one reason for all. One school that must stay does not
keep the others.
"""

from __future__ import annotations

from django.utils import timezone

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.projects import services as project_services
from apps.projects.models import ProjectSchoolAssignment, ProjectSchoolEnrollmentHistory
from apps.projects.test_project_capacity import FY, _Fixture


class ProjectBulkWithdrawTest(_Fixture):
    def _begin(self, school):
        Activity.objects.create(
            activity_type="school_visit",
            school=school,
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate(),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )

    def test_the_service_withdraws_each_and_leaves_the_one_that_must_stay(self):
        self.allow(3)
        for school in self.schools[:3]:
            self.add(school)
        self._begin(self.schools[2])

        outcomes = project_services.remove_schools(
            self.project.id,
            [s.id for s in self.schools[:3]],
            self.cceo_user,
            reason_code="duplicate",
        )

        self.assertEqual([o["ok"] for o in outcomes], [True, True, False])
        self.assertEqual(
            list(
                ProjectSchoolAssignment.objects.filter(
                    project=self.project
                ).values_list("school_id", flat=True)
            ),
            [self.schools[2].id],
        )
        self.assertEqual(
            ProjectSchoolEnrollmentHistory.objects.filter(project=self.project).count(),
            2,
        )
        self.assertEqual(self.held().assigned, 1)

    def test_a_reason_is_required_once(self):
        self.allow(1)
        self.add(self.schools[0])
        with self.assertRaises(BadRequest):
            project_services.remove_schools(
                self.project.id, [self.schools[0].id], self.cceo_user
            )
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(school=self.schools[0]).exists()
        )

    def test_another_officer_withdraws_none_of_them(self):
        self.allow(2)
        self.add(self.schools[0])
        self.add(self.schools[1])
        outcomes = project_services.remove_schools(
            self.project.id,
            [self.schools[0].id, self.schools[1].id],
            self.other_user,
            reason_code="duplicate",
        )
        self.assertFalse(any(o["ok"] for o in outcomes))
        self.assertEqual(
            ProjectSchoolAssignment.objects.filter(project=self.project).count(), 2
        )

    def test_the_profile_ticks_withdrawable_schools_and_the_drawer_withdraws(self):
        self.allow(3)
        for school in self.schools[:3]:
            self.add(school)
        self._begin(self.schools[2])
        self.client.force_login(self.cceo_user)

        page = self.client.get(f"/projects/{self.project.id}").content.decode()
        self.assertIn("data-project-bulk-withdraw", page)
        self.assertIn(f'value="{self.schools[0].id}" x-model="selected"', page)
        # Work has begun: no tick.
        self.assertNotIn(f'value="{self.schools[2].id}" x-model="selected"', page)

        ticked = [s.id for s in self.schools[:3]]
        drawer = self.client.get(
            f"/projects/{self.project.id}/schools/bulk-withdraw",
            {"school_ids": ticked},
        ).content.decode()
        self.assertIn("Withdraw 2 schools", drawer)
        self.assertIn("Will be withdrawn", drawer)

        done = self.client.post(
            f"/projects/{self.project.id}/schools/bulk-withdraw",
            {"school_ids": ticked, "reason_code": "duplicate"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(done.status_code, 204)
        self.assertEqual(
            list(
                ProjectSchoolAssignment.objects.filter(
                    project=self.project
                ).values_list("school_id", flat=True)
            ),
            [self.schools[2].id],
        )

    def test_another_officer_gets_no_tick(self):
        self.allow(1)
        self.add(self.schools[0])
        self.client.force_login(self.other_user)
        page = self.client.get(f"/projects/{self.project.id}")
        if page.status_code == 200:
            self.assertNotIn("data-project-leave-pick", page.content.decode())
