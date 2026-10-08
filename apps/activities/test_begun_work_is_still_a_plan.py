"""Work that was started and never submitted is still a plan (owner,
2026-10-07).

"When you click complete … or the activity was just clicked complete but it
was canceled before completing. It blocks it from editing. Can you lift it so
that there is no restriction."

The Complete drawer marks an activity started the moment it opens. An officer
who opened it and pressed Cancel was left holding a plan with Edit greyed out
and Reschedule gone: "Already carried out". Nothing had been carried out.

What is pinned here: opening Complete and leaving it does not close Edit or
Reschedule; a new day puts the activity back among the scheduled work, ready
to be started again; and work that was really delivered is as locked as it
was.
"""

from __future__ import annotations

from apps.activities import editing, services
from apps.activities.calendar_scope import planning_events
from apps.activities.models import Activity
from apps.activities.test_activity_editing import EditingFixture, _weekday
from apps.activities.test_profile_activities import PASSWORD
from apps.core.exceptions import BadRequest


class OpeningCompleteDoesNotCloseThePlan(EditingFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))
        self.visit = self._visit()

    def _open_complete_and_leave(self) -> Activity:
        """What the officer did: Complete Activity, then Cancel."""
        opened = self.client.get(
            f"/my-plan/{self.visit.id}/complete-drawer", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(opened.status_code, 200, opened.content[:300])
        self.visit.refresh_from_db()
        # The drawer started the activity by opening; nothing was submitted.
        self.assertEqual(self.visit.status, "completion_started")
        self.assertIsNotNone(self.visit.execution_started_at)
        return self.visit

    def test_the_activity_is_still_a_plan(self):
        visit = self._open_complete_and_leave()

        self.assertTrue(editing.is_begun(visit))
        self.assertFalse(editing.is_executed(visit))
        self.assertTrue(editing.is_editable(visit))
        self.assertEqual(editing.edit_state(visit, self.cceo), "open")

    def test_the_edit_button_and_its_drawer_stay_open(self):
        visit = self._open_complete_and_leave()

        detail = self.client.get(
            f"/my-plan/{visit.id}", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn(f'hx-get="/my-plan/{visit.id}/edit-drawer"', detail)
        self.assertIn(f"/my-plan/{visit.id}/reschedule-drawer", detail)
        self.assertNotIn("data-edit-locked", detail)

        drawer = self.client.get(f"/my-plan/{visit.id}/edit-drawer")
        self.assertEqual(drawer.status_code, 200)
        self.assertIn(f'hx-post="/my-plan/{visit.id}/edit"', drawer.content.decode())

        reschedule = self.client.get(f"/my-plan/{visit.id}/reschedule-drawer")
        self.assertEqual(reschedule.status_code, 200)

    def test_what_it_is_for_can_be_rewritten(self):
        visit = self._open_complete_and_leave()

        response = self.client.post(
            f"/my-plan/{visit.id}/edit",
            {
                "scheduled_date": visit.planned_date.isoformat(),
                "activity_purpose_text": "Review the improvement plan",
                "reason": "",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.activity_purpose_text, "Review the improvement plan")
        # Only the words changed: it is where the officer left it.
        self.assertEqual(visit.status, "completion_started")

    def test_a_new_day_puts_it_back_among_the_scheduled_work(self):
        visit = self._open_complete_and_leave()
        day = _weekday(9)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                visit.id,
                {"scheduledDate": day.isoformat(), "reason": "The head is away"},
                self.cceo,
            )

        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, day)
        self.assertEqual(visit.status, "rescheduled")
        # The start was made on the old day and nothing came of it.
        self.assertIsNone(visit.execution_started_at)
        # And it can be begun again on the new one.
        self.assertIn(visit.status, services.STARTABLE_STATUSES)

    def test_reschedule_moves_it_too(self):
        visit = self._open_complete_and_leave()
        day = _weekday(11)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{visit.id}/reschedule",
                {"scheduled_date": day.isoformat(), "reason": "School sports day"},
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, day)
        self.assertEqual(visit.status, "rescheduled")

    def test_the_calendar_opens_reschedule_on_it(self):
        visit = self._open_complete_and_leave()

        events = {event["id"]: event for event in planning_events(self.cceo, visit.fy)}

        self.assertTrue(events[visit.id]["extendedProps"]["reschedule"])

    def test_it_can_move_to_another_school(self):
        visit = self._open_complete_and_leave()

        with self.captureOnCommitCallbacks(execute=True):
            moved = editing.edit(
                visit.id,
                {"schoolId": self.fresh_two.school_id, "reason": "Wrong school"},
                self.cceo,
            )

        visit.refresh_from_db()
        self.assertEqual(visit.status, "cancelled")
        again = Activity.objects.get(id=moved["id"])
        self.assertEqual(again.school_id, self.fresh_two.id)
        self.assertEqual(again.status, "scheduled")


class DeliveredWorkStaysARecord(EditingFixture):
    """The line moved to delivery; it did not go away."""

    def test_submitted_and_verified_work_is_still_locked(self):
        day = _weekday(12).isoformat()
        for done in (self.delivered, self.verified):
            with self.subTest(status=done.status):
                self.assertEqual(editing.edit_state(done, self.cceo), "locked")
                with self.assertRaises(BadRequest):
                    editing.edit(done.id, {"activityPurposeText": "x"}, self.cceo)
                with self.assertRaises(BadRequest):
                    services.reschedule(
                        done.id, {"scheduledDate": day, "reason": "moved"}, self.cceo
                    )

    def test_a_partner_s_begun_delivery_is_still_the_partner_s(self):
        self.partner_work.status = "completion_started"
        self.partner_work.save(update_fields=["status"])

        self.assertFalse(editing.is_editable(self.partner_work))
        self.assertEqual(editing.edit_state(self.partner_work, self.cceo), "")
