"""Edit changes a planned activity's project, and its intervention with it
(owner, 2026-10-02).

"Project should be edited including the interventions they are attached to.
For example if a user wants to change a project to another they should be
able to select an intervention the new project is linked to. For example
changing from CC-SEL secondary to Alumni should be able to change the
intervention from Christlike behaviour to General which is linked to Alumni."

The Edit drawer listed all eight SSA interventions and no project: work filed
under the wrong project could not be refiled, and General could not be
chosen. What is pinned here: which projects Edit offers, which interventions
each brings, and that the change is made by the scheduling rules of the
project the work ends up under.
"""

from __future__ import annotations

import json

from apps.activities import editing
from apps.activities.models import Activity
from apps.activities.test_activity_editing import EditingFixture, _weekday
from apps.activities.test_profile_activities import PASSWORD
from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import BadRequest
from apps.planning.services import schedule_school_visit
from apps.planning.visit_gate import visit_gate
from apps.projects.models import (
    GENERAL_INTERVENTION,
    Project,
    ProjectSchoolAssignment,
)


class ProjectEditFixture(EditingFixture):
    def setUp(self):
        super().setUp()
        coordinator = User.objects.create(
            email="edit-pc@edify.org",
            name="Edit Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
        )
        self.coordinator_staff = StaffProfile.objects.create(
            user=coordinator, staff_number="ST-EDIT-PC", country="Uganda"
        )
        self.ccsel = self._project("CC-SEL Secondary", ["christlike_behaviour"])
        self.alumni = self._project("Alumni", [GENERAL_INTERVENTION])
        self.edtech = self._project("EdTech", ["learning_environment", "leadership"])
        for project in (self.ccsel, self.alumni):
            ProjectSchoolAssignment.objects.create(project=project, school=self.fresh)

    def _project(self, name, targets, **fields):
        return Project.objects.create(
            name=name,
            status="active",
            target_interventions=targets,
            intervention=next((t for t in targets if t != GENERAL_INTERVENTION), None),
            manager_staff_id=self.coordinator_staff.id,
            **fields,
        )

    def _project_visit(self, project=None, school=None, **payload) -> Activity:
        with self.captureOnCommitCallbacks(execute=True):
            created = schedule_school_visit(
                {
                    "schoolId": (school or self.fresh).school_id,
                    "activityType": "school_visit",
                    "catalogueItemId": "STANDARD_SCHOOL_VISIT",
                    "scheduledDate": _weekday(6).isoformat(),
                    "responsibleStaffId": str(self.cceo_staff.id),
                    "projectId": (project or self.ccsel).id,
                    **payload,
                },
                self.cceo,
            )
        return Activity.objects.get(id=created["id"])

    def _change(self, activity, project, **data):
        with self.captureOnCommitCallbacks(execute=True):
            result = editing.edit(
                activity.id,
                {"projectId": project.id, "reason": "Filed under the wrong project"}
                | data,
                self.cceo,
            )
        return Activity.objects.get(id=result["id"])


class WhatAProjectIsLinkedTo(ProjectEditFixture):
    def test_a_project_offers_the_interventions_it_names(self):
        self.assertEqual(
            editing.project_interventions(self.ccsel),
            [("christlike_behaviour", "Christlike Behaviour")],
        )
        self.assertEqual(
            editing.project_interventions(self.alumni),
            [(GENERAL_INTERVENTION, "General")],
        )
        self.assertEqual(
            [code for code, _label in editing.project_interventions(self.edtech)],
            ["learning_environment", "leadership"],
        )

    def test_a_project_naming_none_measures_against_any(self):
        open_ended = self._project("Open Ended", [])
        self.assertEqual(len(editing.project_interventions(open_ended)), 8)


class WhichProjectsEditOffers(ProjectEditFixture):
    def test_its_own_first_then_the_school_s_others_then_those_it_can_join(self):
        visit = self._project_visit()
        offered = editing.changeable_projects(visit, self.cceo)
        self.assertEqual(
            [project.name for project in offered],
            ["CC-SEL Secondary", "Alumni", "EdTech"],
        )

    def test_a_closed_project_is_not_offered(self):
        visit = self._project_visit()
        Project.objects.filter(id=self.alumni.id).update(status="closed")
        names = [p.name for p in editing.changeable_projects(visit, self.cceo)]
        self.assertNotIn("Alumni", names)

    def test_work_under_no_project_is_offered_none(self):
        self.assertEqual(editing.changeable_projects(self._visit(), self.cceo), [])


class ChangingTheProject(ProjectEditFixture):
    def test_it_asks_for_the_reason(self):
        visit = self._project_visit()
        with self.assertRaises(BadRequest) as refused:
            editing.edit(visit.id, {"projectId": self.alumni.id}, self.cceo)
        self.assertIn("another project", str(refused.exception))
        visit.refresh_from_db()
        self.assertEqual((visit.status, visit.project_id), ("scheduled", self.ccsel.id))

    def test_cc_sel_to_alumni_takes_general(self):
        """The owner's example: Christlike Behaviour becomes General."""
        visit = self._project_visit()
        self.assertEqual(visit.focus_intervention, "christlike_behaviour")
        day = visit.planned_date

        moved = self._change(visit, self.alumni, focusIntervention="")

        visit.refresh_from_db()
        self.assertEqual(visit.status, "cancelled")
        self.assertIn("Changed to Alumni", visit.last_reason)
        self.assertIn("Filed under the wrong project", visit.last_reason)
        self.assertEqual(moved.project_id, self.alumni.id)
        self.assertEqual(moved.school_id, self.fresh.id)
        self.assertEqual(moved.planned_date, day)
        self.assertEqual(moved.status, "scheduled")
        # General is no SSA focus, never the old project's left behind.
        self.assertIsNone(moved.focus_intervention)
        # The purpose a project activity is given is its project's name.
        self.assertEqual(visit.activity_purpose_text, "CC-SEL Secondary")
        self.assertEqual(moved.activity_purpose_text, "Alumni")

    def test_general_posted_by_name_is_no_focus_too(self):
        visit = self._project_visit()
        moved = self._change(visit, self.alumni, focusIntervention="general")
        self.assertIsNone(moved.focus_intervention)

    def test_alumni_to_cc_sel_takes_the_intervention_it_is_linked_to(self):
        visit = self._project_visit(self.alumni)
        self.assertIsNone(visit.focus_intervention)

        moved = self._change(visit, self.ccsel)

        self.assertEqual(moved.project_id, self.ccsel.id)
        self.assertEqual(moved.focus_intervention, "christlike_behaviour")

    def test_the_planner_chooses_among_the_new_project_s_interventions(self):
        ProjectSchoolAssignment.objects.create(project=self.edtech, school=self.fresh)
        visit = self._project_visit()
        moved = self._change(visit, self.edtech, focusIntervention="leadership")
        self.assertEqual(moved.focus_intervention, "leadership")

    def test_an_intervention_the_new_project_is_not_linked_to_is_refused(self):
        visit = self._project_visit()
        with self.assertRaises(BadRequest) as refused:
            self._change(visit, self.alumni, focusIntervention="christlike_behaviour")
        self.assertIn(
            "'Alumni' is not linked to that intervention", str(refused.exception)
        )
        visit.refresh_from_db()
        self.assertEqual((visit.status, visit.project_id), ("scheduled", self.ccsel.id))
        self.assertEqual(Activity.objects.filter(project_id=self.alumni.id).count(), 0)

    def test_the_school_joins_a_project_it_was_not_in(self):
        visit = self._project_visit()
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(
                project=self.edtech, school=self.fresh
            ).exists()
        )
        moved = self._change(visit, self.edtech)
        self.assertEqual(moved.project_id, self.edtech.id)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.edtech, school=self.fresh
            ).exists()
        )
        # It stays in the project it left: withdrawing is its coordinator's.
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.ccsel, school=self.fresh
            ).exists()
        )

    def test_a_project_the_school_cannot_join_is_refused(self):
        core_only = self._project("Core Only", ["leadership"], school_focus="core")
        visit = self._project_visit()
        with self.assertRaises(BadRequest):
            self._change(visit, core_only)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")

    def test_a_project_and_a_school_change_together(self):
        visit = self._project_visit()
        moved = self._change(
            visit, self.alumni, schoolId=self.fresh_two.school_id, focusIntervention=""
        )
        self.assertEqual(
            (moved.school_id, moved.project_id), (self.fresh_two.id, self.alumni.id)
        )
        visit.refresh_from_db()
        self.assertIn(
            f"Moved to {self.fresh_two.name}, Changed to Alumni", visit.last_reason
        )
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=self.alumni, school=self.fresh_two
            ).exists()
        )

    def test_the_allowance_follows_the_project_the_work_ends_up_under(self):
        """Alumni work is outside the client school's one support visit; the
        same visit under CC-SEL uses it."""
        visit = self._project_visit()
        self.assertEqual(visit_gate(self.fresh, visit.fy).staff_visits, 1)

        moved = self._change(visit, self.alumni, focusIntervention="")
        self.assertEqual(visit_gate(self.fresh, moved.fy).staff_visits, 0)

        back = self._change(moved, self.ccsel)
        self.assertEqual(visit_gate(self.fresh, back.fy).staff_visits, 1)

    def test_the_same_project_is_no_change(self):
        visit = self._project_visit()
        result = editing.edit(visit.id, {"projectId": self.ccsel.id}, self.cceo)
        self.assertEqual(result["id"], visit.id)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")

    def test_a_focus_under_the_same_project_is_one_it_is_linked_to(self):
        ProjectSchoolAssignment.objects.create(project=self.edtech, school=self.fresh)
        visit = self._project_visit(self.edtech)
        editing.edit(visit.id, {"focusIntervention": "leadership"}, self.cceo)
        visit.refresh_from_db()
        self.assertEqual(visit.focus_intervention, "leadership")
        with self.assertRaises(BadRequest):
            editing.edit(visit.id, {"focusIntervention": "enrolment"}, self.cceo)

    def test_a_focus_its_project_no_longer_names_survives_a_new_date(self):
        visit = self._project_visit()
        Activity.objects.filter(id=visit.id).update(focus_intervention="leadership")
        new_day = _weekday(14)
        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                visit.id,
                {
                    "scheduledDate": new_day.isoformat(),
                    "reason": "Head is away",
                    "focusIntervention": "leadership",
                    "projectId": self.ccsel.id,
                },
                self.cceo,
            )
        visit.refresh_from_db()
        self.assertEqual(
            (visit.planned_date, visit.focus_intervention), (new_day, "leadership")
        )


class TheProjectFieldInTheDrawer(ProjectEditFixture):
    def setUp(self):
        super().setUp()
        self.client.login(email=self.cceo.email, password=PASSWORD)

    def _drawer(self, activity) -> str:
        response = self.client.get(f"/my-plan/{activity.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_project_work_names_its_project_and_the_others(self):
        visit = self._project_visit()
        body = self._drawer(visit)
        self.assertIn("data-edit-project", body)
        self.assertIn('name="project_id"', body)
        self.assertIn(
            f'<option value="{self.ccsel.id}" selected>CC-SEL Secondary</option>', body
        )
        self.assertIn(f'<option value="{self.alumni.id}">Alumni</option>', body)
        # One the school is not in yet says what choosing it does.
        self.assertIn(
            f'<option value="{self.edtech.id}">EdTech (adds this school to it)</option>',
            body,
        )

    def test_each_project_brings_the_interventions_it_is_linked_to(self):
        visit = self._project_visit()
        context = self.client.get(f"/my-plan/{visit.id}/edit-drawer").context
        links = json.loads(context["project_links_json"])
        self.assertEqual(
            links[self.ccsel.id],
            [
                {"code": "", "label": "None"},
                {"code": "christlike_behaviour", "label": "Christlike Behaviour"},
            ],
        )
        # General is the one choice, and posts as no SSA focus.
        self.assertEqual(links[self.alumni.id], [{"code": "", "label": "General"}])
        self.assertEqual(
            [option["code"] for option in links[self.edtech.id]],
            ["", "learning_environment", "leadership"],
        )

    def test_work_under_no_project_keeps_all_eight_and_has_no_project_field(self):
        body = self._drawer(self._visit())
        self.assertNotIn("data-edit-project", body)
        self.assertNotIn('name="project_id"', body)
        self.assertIn('<option value="enrolment"', body)

    def test_a_school_with_one_project_and_none_to_join_reads_it(self):
        visit = self._project_visit()
        Project.objects.exclude(id=self.ccsel.id).update(status="closed")
        body = self._drawer(visit)
        self.assertIn("data-edit-project-fixed", body)
        self.assertNotIn('name="project_id"', body)

    def test_the_drawer_saves_the_new_project_and_its_intervention(self):
        visit = self._project_visit()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{visit.id}/edit",
                {
                    "scheduled_date": visit.planned_date.isoformat(),
                    "school_id": self.fresh.school_id,
                    "project_id": self.alumni.id,
                    "focus_intervention": "",
                    "activity_purpose_text": visit.activity_purpose_text,
                    "expected_outcome": "",
                    "reason": "This is the Alumni visit",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "cancelled")
        moved = Activity.objects.get(
            project_id=self.alumni.id, school=self.fresh, status="scheduled"
        )
        self.assertIsNone(moved.focus_intervention)
        self.assertEqual(moved.activity_purpose_text, "Alumni")

    def test_a_refused_change_says_why_in_the_drawer(self):
        visit = self._project_visit()
        response = self.client.post(
            f"/my-plan/{visit.id}/edit",
            {
                "scheduled_date": visit.planned_date.isoformat(),
                "project_id": self.alumni.id,
                "focus_intervention": "",
                "reason": "",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"moving to another project", response.content)
