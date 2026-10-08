"""Editing a planned activity (owner, 2026-10-02).

"Make sure the activities planned are editable from the activity profile. The
users should be able to edit and change the activities, add or remove schools,
change dates which should ask them for reason to reschedule. When one opens
view activities, they should be able to click edit button … but only planned
activities that are still at scheduled mode should be editable. Activities
that are already [executed and completed] should have the greyed out disabled
button."

What is pinned here: where the line between a plan and a record is, that Edit
and Reschedule both keep to it, what Edit changes and what it asks for, and
the button on each screen.

The line is delivery (owner, 2026-10-07): work that was started and never
submitted is still a plan. Its own tests are in
``test_begun_work_is_still_a_plan``.
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from apps.activities import editing
from apps.activities import profile_activities as profile_acts
from apps.activities import services
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.accounts.models import StaffSchoolAssignment
from apps.activities.test_profile_activities import PASSWORD, ProfileActivitiesFixture
from apps.core.exceptions import BadRequest, Forbidden
from apps.planning.services import schedule_school_visit
from apps.schools.models import School


def _weekday(days: int) -> datetime.date:
    """A day ``days`` ahead that the calendar policy accepts (not a Sunday)."""
    day = timezone.localdate() + datetime.timedelta(days=days)
    while day.weekday() == 6:
        day += datetime.timedelta(days=1)
    return day


class EditingFixture(ProfileActivitiesFixture):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        self.started = self._activity(
            school=self.school,
            status="completion_started",
            day=today - datetime.timedelta(1),
        )
        self.member = School.objects.create(
            school_id="PROFILE-003",
            name="Profile Member",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=self.cceo_staff.id,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
        )
        # Two schools with nothing planned: the fixture's own school has had
        # its staff visit for the year, so a real visit is scheduled here.
        self.fresh, self.fresh_two = (
            School.objects.create(
                school_id=code,
                name=name,
                region=self.region,
                district=self.district,
                school_type="client",
                account_owner_id=self.cceo_staff.id,
            )
            for code, name in (
                ("PROFILE-004", "Profile Fresh"),
                ("PROFILE-005", "Profile Fresh Two"),
            )
        )
        for school in (self.fresh, self.fresh_two):
            StaffSchoolAssignment.objects.create(
                staff=self.cceo_staff, school_id=school.id
            )

    def _visit(self, school=None, *, days=6) -> Activity:
        """A visit scheduled the way a drawer schedules one: catalogue item,
        cost lines and all."""
        day = _weekday(days)
        with self.captureOnCommitCallbacks(execute=True):
            created = schedule_school_visit(
                {
                    "schoolId": (school or self.fresh).school_id,
                    "activityType": "school_visit",
                    "catalogueItemId": "STANDARD_SCHOOL_VISIT",
                    "scheduledDate": day.isoformat(),
                    "focusIntervention": "leadership",
                    "activityPurposeText": "Coach the head teacher",
                    "responsibleStaffId": str(self.cceo_staff.id),
                },
                self.cceo,
            )
        return Activity.objects.get(id=created["id"])


class WhatIsStillAPlan(EditingFixture):
    def test_scheduled_staff_work_is_editable_and_executed_work_is_not(self):
        self.assertTrue(editing.is_editable(self.planned))
        self.assertFalse(editing.is_executed(self.planned))
        for done in (self.delivered, self.verified):
            with self.subTest(status=done.status):
                self.assertFalse(editing.is_editable(done))
                self.assertTrue(editing.is_executed(done))

    def test_the_button_is_open_locked_or_absent(self):
        self.assertEqual(editing.edit_state(self.planned, self.cceo), "open")
        # Carried out: the button stays, greyed.
        self.assertEqual(editing.edit_state(self.delivered, self.cceo), "locked")
        self.assertEqual(editing.edit_state(self.verified, self.cceo), "locked")
        # Not theirs to run, or not a plan edited here: no button at all.
        self.assertEqual(editing.edit_state(self.planned, self.pl), "")
        self.assertEqual(editing.edit_state(self.partner_work, self.cceo), "")
        self.assertEqual(editing.edit_state(self.cancelled, self.cceo), "")

    def test_profile_rows_carry_the_same_answer(self):
        acts = self._read(self.cceo, profile_acts.for_school(self.school))
        rows = {
            row.id: row
            for row in list(acts.planned["rows"]) + list(acts.completed["rows"])
        }

        self.assertTrue(rows[self.planned.id].may_edit)
        self.assertFalse(rows[self.planned.id].edit_locked)
        self.assertTrue(rows[self.verified.id].edit_locked)
        self.assertFalse(rows[self.verified.id].may_edit)
        self.assertTrue(rows[self.delivered.id].edit_locked)
        self.assertFalse(rows[self.delivered.id].may_edit)
        # Started and never submitted is still a plan (owner, 2026-10-07):
        # Reschedule goes with Edit.
        self.assertTrue(rows[self.started.id].may_edit)
        self.assertFalse(rows[self.started.id].edit_locked)
        self.assertTrue(rows[self.started.id].may_reschedule)

        supervisor = self._read(self.pl, profile_acts.for_school(self.school))
        for row in list(supervisor.planned["rows"]) + list(
            supervisor.completed["rows"]
        ):
            self.assertFalse(row.may_edit or row.edit_locked)


class RescheduleKeepsToTheSameLine(EditingFixture):
    def test_work_already_carried_out_is_not_rescheduled(self):
        """`reschedule` accepted a completed visit and turned it back into
        "rescheduled", under its evidence and its verification."""
        day = _weekday(12).isoformat()
        for done in (self.delivered, self.verified):
            with self.subTest(status=done.status):
                with self.assertRaises(BadRequest) as refused:
                    services.reschedule(
                        done.id, {"scheduledDate": day, "reason": "moved"}, self.cceo
                    )
                self.assertIn("already been carried out", str(refused.exception))
                done.refresh_from_db()
                self.assertNotEqual(done.status, "rescheduled")


class EditingAPlan(EditingFixture):
    def test_a_new_date_asks_for_the_reason(self):
        visit = self._visit()
        new_day = _weekday(13)

        with self.assertRaises(BadRequest) as refused:
            editing.edit(visit.id, {"scheduledDate": new_day.isoformat()}, self.cceo)

        self.assertIn("reason", str(refused.exception).lower())
        visit.refresh_from_db()
        self.assertNotEqual(visit.planned_date, new_day)

    def test_a_new_date_with_its_reason_reschedules(self):
        visit = self._visit()
        new_day = _weekday(13)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                visit.id,
                {
                    "scheduledDate": new_day.isoformat(),
                    "reason": "The school asked for another day",
                },
                self.cceo,
            )

        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, new_day)
        self.assertEqual(timezone.localtime(visit.scheduled_date).date(), new_day)
        self.assertEqual(visit.status, "rescheduled")
        self.assertEqual(visit.reschedule_count, 1)
        self.assertEqual(visit.last_reason, "The school asked for another day")
        # A rescheduled plan is still a plan: it can be edited again.
        self.assertEqual(editing.edit_state(visit, self.cceo), "open")

    def test_what_it_is_for_changes_without_a_reason(self):
        visit = self._visit()

        editing.edit(
            visit.id,
            {
                "scheduledDate": visit.planned_date.isoformat(),
                "activityPurposeText": "Review the improvement plan",
                "expectedOutcome": "A dated plan agreed with the head",
                "focusIntervention": "enrolment",
            },
            self.cceo,
        )

        visit.refresh_from_db()
        self.assertEqual(visit.activity_purpose_text, "Review the improvement plan")
        self.assertEqual(visit.expected_outcome, "A dated plan agreed with the head")
        self.assertEqual(visit.focus_intervention, "enrolment")
        self.assertEqual(visit.status, "scheduled")
        self.assertEqual(visit.reschedule_count, 0)

    def test_work_already_carried_out_is_not_edited(self):
        for done in (self.delivered, self.verified):
            with self.subTest(status=done.status):
                with self.assertRaises(BadRequest) as refused:
                    editing.edit(
                        done.id, {"activityPurposeText": "Rewritten"}, self.cceo
                    )
                self.assertIn("already been carried out", str(refused.exception))

    def test_a_supervisor_does_not_edit_the_team_s_work(self):
        with self.assertRaises(Forbidden):
            editing.edit(self.planned.id, {"activityPurposeText": "Rewritten"}, self.pl)

    def test_a_partner_s_delivery_is_not_edited_here(self):
        with self.assertRaises((BadRequest, Forbidden)):
            editing.edit(
                self.partner_work.id, {"activityPurposeText": "Rewritten"}, self.cceo
            )

    # -- schools -------------------------------------------------------------

    def _invited(self) -> set[str]:
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=self.session, invited=True
            ).values_list("school_id", flat=True)
        )

    def test_a_school_is_added_to_and_removed_from_a_cluster_session(self):
        self.assertEqual(self._invited(), {self.school.id})

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                self.session.id,
                {"invitedSchoolIds": [self.school.id, self.member.id]},
                self.cceo,
            )
        self.assertEqual(self._invited(), {self.school.id, self.member.id})
        self.session.refresh_from_db()
        self.assertEqual(self.session.schools_invited, 2)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                self.session.id, {"invitedSchoolIds": [self.member.id]}, self.cceo
            )
        self.assertEqual(self._invited(), {self.member.id})
        self.session.refresh_from_db()
        self.assertEqual(self.session.schools_invited, 1)

    def test_a_session_keeps_at_least_one_school(self):
        with self.assertRaises(BadRequest):
            editing.edit(self.session.id, {"invitedSchoolIds": []}, self.cceo)
        self.assertEqual(self._invited(), {self.school.id})

    def test_a_school_outside_the_cluster_is_not_invited(self):
        with self.assertRaises(BadRequest):
            editing.edit(
                self.session.id,
                {"invitedSchoolIds": [self.school.id, self.other.id]},
                self.cceo,
            )

    def test_moving_a_visit_to_another_school_asks_for_the_reason(self):
        visit = self._visit()

        with self.assertRaises(BadRequest) as refused:
            editing.edit(visit.id, {"schoolId": self.fresh_two.school_id}, self.cceo)

        self.assertIn("reason", str(refused.exception).lower())
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")

    def test_a_visit_moves_to_another_school(self):
        visit = self._visit()
        day = visit.planned_date

        with self.captureOnCommitCallbacks(execute=True):
            result = editing.edit(
                visit.id,
                {
                    "schoolId": self.fresh_two.school_id,
                    "reason": "Planned at the wrong school",
                },
                self.cceo,
            )

        visit.refresh_from_db()
        self.assertEqual(visit.status, "cancelled")
        self.assertIn(self.fresh_two.name, visit.last_reason)
        self.assertIn("Planned at the wrong school", visit.last_reason)
        moved = Activity.objects.get(id=result["id"])
        self.assertNotEqual(moved.id, visit.id)
        self.assertEqual(moved.school_id, self.fresh_two.id)
        self.assertEqual(moved.planned_date, day)
        self.assertEqual(moved.activity_type, "school_visit")
        self.assertEqual(moved.catalogue_item_id, visit.catalogue_item_id)
        self.assertEqual(moved.activity_purpose_text, "Coach the head teacher")
        self.assertEqual(moved.focus_intervention, "leadership")
        self.assertEqual(moved.status, "scheduled")

    def test_an_in_school_training_and_its_visit_move_together(self):
        """One mission on one day (owner, 2026-09-28): a new date from either
        record moves both."""
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.planning.services import schedule_in_school_training_pair

        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        with self.captureOnCommitCallbacks(execute=True):
            created = schedule_in_school_training_pair(
                {
                    "schoolId": self.fresh.school_id,
                    "catalogueItemId": course.id,
                    "scheduledDate": _weekday(6).isoformat(),
                    "responsibleStaffId": str(self.cceo_staff.id),
                },
                self.cceo,
            )
        training = Activity.objects.get(id=created["id"])
        visit = Activity.objects.get(id=created["pairedSchoolVisitId"])
        new_day = _weekday(14)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                training.id,
                {"scheduledDate": new_day.isoformat(), "reason": "Head is away"},
                self.cceo,
            )

        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.planned_date, new_day)
        self.assertEqual(visit.planned_date, new_day)

    def test_a_refused_move_leaves_the_plan_where_it_was(self):
        visit = self._visit()
        elsewhere = School.objects.create(
            school_id="PROFILE-FAR",
            name="Somebody Else's School",
            region=self.region,
            district=self.district,
            school_type="client",
        )

        with self.assertRaises(BadRequest):
            editing.edit(
                visit.id,
                {"schoolId": elsewhere.school_id, "reason": "Wrong school"},
                self.cceo,
            )

        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")
        self.assertFalse(Activity.objects.filter(school=elsewhere).exists())


class TheEditScreens(EditingFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))

    def test_the_profile_row_offers_edit_and_greys_it_once_carried_out(self):
        body = self.client.get(
            f"/schools/{self.school.school_id}?school_acts_tab=planned"
        ).content.decode()

        self.assertIn(f'hx-get="/my-plan/{self.planned.id}/edit-drawer"', body)

        done = self.client.get(
            f"/schools/{self.school.school_id}?school_acts_tab=completed"
        ).content.decode()
        self.assertNotIn(f'hx-get="/my-plan/{self.delivered.id}/edit-drawer"', done)
        self.assertIn("data-edit-locked", done)
        self.assertIn("Already carried out, so it can no longer be edited.", done)
        self.assertNotIn(f"/my-plan/{self.delivered.id}/reschedule-drawer", done)

    def test_view_activity_has_the_edit_button(self):
        opened = self.client.get(f"/my-plan/{self.planned.id}", HTTP_HX_REQUEST="true")
        body = opened.content.decode()
        self.assertEqual(opened.status_code, 200)
        self.assertIn(f'hx-get="/my-plan/{self.planned.id}/edit-drawer"', body)
        self.assertIn(f"/my-plan/{self.planned.id}/reschedule-drawer", body)

        locked = self.client.get(
            f"/my-plan/{self.delivered.id}", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn("data-edit-locked", locked)
        self.assertIn("disabled", locked)
        self.assertNotIn(f"/my-plan/{self.delivered.id}/edit-drawer", locked)
        self.assertNotIn(f"/my-plan/{self.delivered.id}/reschedule-drawer", locked)

    def test_the_activity_page_has_the_edit_action(self):
        body = self.client.get(f"/my-plan/{self.planned.id}").content.decode()
        self.assertIn(f'hx-get="/my-plan/{self.planned.id}/edit-drawer"', body)

        locked = self.client.get(f"/my-plan/{self.delivered.id}").content.decode()
        self.assertIn("data-edit-locked", locked)
        self.assertNotIn(f"/my-plan/{self.delivered.id}/edit-drawer", locked)

    def test_the_drawer_opens_for_a_plan_and_not_for_work_carried_out(self):
        opened = self.client.get(f"/my-plan/{self.planned.id}/edit-drawer")
        self.assertEqual(opened.status_code, 200)
        body = opened.content.decode()
        self.assertIn(f'hx-post="/my-plan/{self.planned.id}/edit"', body)
        self.assertIn('name="scheduled_date"', body)
        self.assertIn("data-edit-school", body)
        self.assertIn(self.other.name, body)

        refused = self.client.get(f"/my-plan/{self.delivered.id}/edit-drawer")
        self.assertEqual(refused.status_code, 400)
        self.assertIn(editing.LOCKED_REASON, refused.content.decode())

    def test_a_cluster_session_s_drawer_lists_its_member_schools(self):
        body = self.client.get(
            f"/my-plan/{self.session.id}/edit-drawer"
        ).content.decode()

        self.assertIn("data-edit-invited-schools", body)
        self.assertIn(
            f'name="invited_school_ids" value="{self.school.id}"\n'
            "               checked",
            body,
        )
        self.assertIn(f'name="invited_school_ids" value="{self.member.id}"', body)
        # A cluster meeting takes a facilitator (owner, 2026-10-02).
        self.assertIn('name="facilitating_partner_id"', body)

    def test_the_drawer_saves_through_the_edit_service(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{self.session.id}/edit",
                {
                    "scheduled_date": self.session.planned_date.isoformat(),
                    "invited_schools_shown": "1",
                    "invited_school_ids": [self.school.id, self.member.id],
                    "activity_purpose_text": "Agree the term's enrolment drive",
                    "expected_outcome": "",
                    "focus_intervention": "",
                    "reason": "",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        self.session.refresh_from_db()
        self.assertEqual(
            self.session.activity_purpose_text, "Agree the term's enrolment drive"
        )
        self.assertEqual(
            set(
                ClusterActivityAttendance.objects.filter(
                    activity=self.session, invited=True
                ).values_list("school_id", flat=True)
            ),
            {self.school.id, self.member.id},
        )

    def test_a_refused_save_says_why_in_the_drawer(self):
        response = self.client.post(
            f"/my-plan/{self.delivered.id}/edit",
            {"activity_purpose_text": "Rewritten"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already been carried out", response.content)

    def test_the_reschedule_drawer_does_not_open_for_work_carried_out(self):
        opened = self.client.get(f"/my-plan/{self.planned.id}/reschedule-drawer")
        self.assertEqual(opened.status_code, 200)

        refused = self.client.get(f"/my-plan/{self.delivered.id}/reschedule-drawer")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("already been carried out", refused.content.decode())

    def test_a_supervisor_has_no_edit_button_and_no_drawer(self):
        self.client.logout()
        self.assertTrue(self.client.login(email=self.pl.email, password=PASSWORD))

        body = self.client.get(f"/staff/{self.cceo.id}").content.decode()
        self.assertNotIn(f"/my-plan/{self.planned.id}/edit-drawer", body)
        self.assertNotIn("data-edit-locked", body)

        drawer = self.client.get(f"/my-plan/{self.planned.id}/edit-drawer")
        self.assertEqual(drawer.status_code, 400)
