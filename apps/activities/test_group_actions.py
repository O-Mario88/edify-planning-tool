"""Reschedule or cancel several activities together (owner, 2026-10-05).

"add also group reschedule where the users use checkboxes to mark all the
clusters meetings or group training, or schools visits scheduled using
checkboxes and then select reschedule in the action buttons ... Make sure
group cancel also is there so that users can be able to cancel activities in
group."

What is pinned here: each ticked activity goes through the single door, one
refusal does not undo the rest, the two halves of an in-school Training stay
together, finished work is never swept up by a group cancel, and the two
drawers say what will happen before anyone confirms.
"""

from __future__ import annotations

import datetime

from django.contrib.messages import get_messages
from django.utils import timezone

from apps.activities import group_actions
from apps.activities.models import Activity
from apps.activities.test_activity_editing import EditingFixture, _weekday
from apps.activities.test_profile_activities import PASSWORD
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest

RESCHEDULE_URL = "/activity-selection/reschedule"
CANCEL_URL = "/activity-selection/cancel"


class GroupFixture(EditingFixture):
    def _pair(self, school=None, *, days=6):
        """An in-school Training and the School Visit it is done during."""
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.planning.services import schedule_in_school_training_pair

        course = ActivityCatalogueItem.objects.get(stable_code="SCHOOL_LEADERSHIP")
        with self.captureOnCommitCallbacks(execute=True):
            created = schedule_in_school_training_pair(
                {
                    "schoolId": (school or self.fresh).school_id,
                    "catalogueItemId": course.id,
                    "scheduledDate": _weekday(days).isoformat(),
                    "responsibleStaffId": str(self.cceo_staff.id),
                },
                self.cceo,
            )
        return (
            Activity.objects.get(id=created["id"]),
            Activity.objects.get(id=created["pairedSchoolVisitId"]),
        )

    def _move(self, ids, day, *, user=None, reason="Schools asked for another day"):
        with self.captureOnCommitCallbacks(execute=True):
            return group_actions.reschedule(
                ids, day.isoformat(), reason, user or self.cceo
            )

    def _call_off(self, ids, *, user=None, reason="Term closed early"):
        with self.captureOnCommitCallbacks(execute=True):
            return group_actions.cancel(ids, reason, user or self.cceo)


class GroupReschedule(GroupFixture):
    def test_the_ticked_visits_move_to_one_date(self):
        first, second = self._visit(self.fresh), self._visit(self.fresh_two)
        new_day = _weekday(15)

        outcome = self._move([first.id, second.id], new_day)

        self.assertEqual({p.id for p in outcome.done}, {first.id, second.id})
        self.assertEqual(outcome.refused, [])
        for visit in (first, second):
            visit.refresh_from_db()
            self.assertEqual(visit.planned_date, new_day)
            self.assertEqual(visit.reschedule_count, 1)
            self.assertEqual(visit.last_reason, "Schools asked for another day")

    def test_one_refusal_does_not_undo_the_rest(self):
        visit = self._visit(self.fresh)
        new_day = _weekday(15)

        outcome = self._move([visit.id, self.delivered.id], new_day)

        self.assertEqual([p.id for p in outcome.done], [visit.id])
        self.assertEqual([p.id for p in outcome.refused], [self.delivered.id])
        self.assertIn("carried out", outcome.refused[0].refusal)
        visit.refresh_from_db()
        self.delivered.refresh_from_db()
        self.assertEqual(visit.planned_date, new_day)
        self.assertEqual(self.delivered.status, "submitted_to_pl")
        self.assertNotEqual(self.delivered.planned_date, new_day)

    def test_work_started_and_never_submitted_moves_with_the_rest(self):
        """Opening Complete and leaving it is not delivering (owner,
        2026-10-07): the activity is still a plan, and moves like one."""
        begun = self._visit(self.fresh)
        Activity.objects.filter(id=begun.id).update(status="completion_started")
        new_day = _weekday(15)

        outcome = self._move([begun.id], new_day)

        self.assertEqual([p.id for p in outcome.done], [begun.id])
        self.assertEqual(outcome.refused, [])
        begun.refresh_from_db()
        self.assertEqual(begun.planned_date, new_day)
        self.assertEqual(begun.status, "rescheduled")

    def test_a_date_the_single_door_refuses_is_reported_per_activity(self):
        """Every date rule is the single reschedule's own: a day that has
        passed is refused for each activity, in its words."""
        visit = self._visit(self.fresh)
        day = visit.planned_date
        yesterday = timezone.localdate() - datetime.timedelta(days=1)

        outcome = self._move([visit.id], yesterday)

        self.assertEqual(outcome.done, [])
        self.assertIn("has passed", outcome.refused[0].refusal)
        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, day)
        self.assertEqual(visit.reschedule_count, 0)

    def test_an_in_school_training_brings_its_visit(self):
        """One mission on one day (owner, 2026-09-28): ticking either half
        moves both, so a group move cannot split them."""
        training, visit = self._pair(self.fresh)
        new_day = _weekday(15)

        outcome = self._move([visit.id], new_day)

        self.assertEqual({p.id for p in outcome.done}, {training.id, visit.id})
        joined = {p.id for p in outcome.done if p.joined}
        self.assertEqual(joined, {training.id})
        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.planned_date, new_day)
        self.assertEqual(visit.planned_date, new_day)

    def test_a_supervisor_moves_nothing(self):
        """§1B: a Programme Lead reads a CCEO's work and does not run it."""
        visit = self._visit(self.fresh)
        day = visit.planned_date

        outcome = self._move([visit.id], _weekday(15), user=self.pl)

        self.assertEqual(outcome.done, [])
        self.assertEqual([p.id for p in outcome.refused], [visit.id])
        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, day)

    def test_a_partners_work_keeps_the_date_the_partner_set(self):
        picks = group_actions.selection(
            [self.partner_work.id], self.cceo, action=group_actions.RESCHEDULE
        )

        self.assertEqual(len(picks), 1)
        self.assertIn("partner", picks[0].refusal.lower())

    def test_an_activity_already_on_the_date_is_left(self):
        visit = self._visit(self.fresh)

        outcome = self._move([visit.id], visit.planned_date)

        self.assertEqual(outcome.done, [])
        self.assertEqual(outcome.refused[0].refusal, "Already on this date.")
        visit.refresh_from_db()
        self.assertEqual(visit.reschedule_count, 0)

    def test_the_date_and_the_reason_are_asked_for(self):
        visit = self._visit(self.fresh)

        with self.assertRaises(BadRequest):
            group_actions.reschedule([visit.id], "", "Why", self.cceo)
        with self.assertRaises(BadRequest):
            group_actions.reschedule(
                [visit.id], _weekday(15).isoformat(), "  ", self.cceo
            )
        visit.refresh_from_db()
        self.assertEqual(visit.reschedule_count, 0)

    def test_nothing_and_too_many_are_refused(self):
        with self.assertRaises(BadRequest):
            group_actions.clean_ids([])
        too_many = [f"id-{n}" for n in range(group_actions.MAX_SELECTION + 1)]
        with self.assertRaises(BadRequest):
            group_actions.clean_ids(too_many)
        self.assertEqual(group_actions.clean_ids(["a", "b", "a", " "]), ["a", "b"])


class GroupCancel(GroupFixture):
    def test_the_ticked_activities_are_cancelled_with_the_one_reason(self):
        visit = self._visit(self.fresh)

        outcome = self._call_off([visit.id, self.session.id])

        self.assertEqual({p.id for p in outcome.done}, {visit.id, self.session.id})
        for activity in (visit, self.session):
            activity.refresh_from_db()
            self.assertEqual(activity.status, "cancelled")
            self.assertEqual(activity.last_reason, "Term closed early")

    def test_finished_and_cancelled_work_is_never_swept_up(self):
        outcome = self._call_off([self.planned.id, self.verified.id, self.cancelled.id])

        self.assertEqual([p.id for p in outcome.done], [self.planned.id])
        reasons = {p.id: p.refusal for p in outcome.refused}
        self.assertIn("completed", reasons[self.verified.id])
        self.assertIn("cancelled", reasons[self.cancelled.id])
        self.verified.refresh_from_db()
        self.assertEqual(self.verified.status, "ia_verified")

    def test_a_pair_is_cancelled_as_one(self):
        training, visit = self._pair(self.fresh)

        outcome = self._call_off([training.id])

        self.assertEqual({p.id for p in outcome.done}, {training.id, visit.id})
        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual((training.status, visit.status), ("cancelled", "cancelled"))

    def test_a_supervisor_cancels_nothing(self):
        outcome = self._call_off([self.planned.id], user=self.pl)

        self.assertEqual(outcome.done, [])
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.status, "scheduled")

    def test_the_reason_is_asked_for(self):
        with self.assertRaises(BadRequest):
            group_actions.cancel([self.planned.id], "", self.cceo)
        self.planned.refresh_from_db()
        self.assertEqual(self.planned.status, "scheduled")

    def test_an_activity_the_reader_cannot_see_is_dropped_without_a_word(self):
        from apps.accounts.models import StaffProfile, User

        stranger = User.objects.create_user(
            email="group-stranger@edify.org",
            name="Group Stranger",
            roles=["CCEO"],
            active_role="CCEO",
            password=PASSWORD,
            is_active=True,
        )
        StaffProfile.objects.create(
            user=stranger, staff_number="ST-GROUP-STRANGER", country="Uganda"
        )

        picks = group_actions.selection(
            [self.planned.id], stranger, action=group_actions.CANCEL
        )

        self.assertEqual(picks, [])


class WhichRowsCarryATickBox(GroupFixture):
    def test_live_work_ticks_and_finished_work_does_not(self):
        for status in ("scheduled", "rescheduled", "planned", "in_progress"):
            self.assertTrue(group_actions.may_tick(status), status)
        for status in ("completed", "ia_verified", "closed", "cancelled"):
            self.assertFalse(group_actions.may_tick(status), status)

    def test_a_calendar_ticks_only_what_the_reader_holds_and_may_run(self):
        mine = [self.planned, self.overdue, self.session, self.verified]

        self.assertEqual(
            group_actions.tickable_ids(mine, self.cceo),
            {self.planned.id, self.overdue.id, self.session.id},
        )
        # The lead reads the same month and is offered no box.
        self.assertEqual(group_actions.tickable_ids(mine, self.pl), set())

    def test_profile_rows_tick_where_they_offer_reschedule_or_cancel(self):
        from apps.activities import profile_activities as profile_acts

        acts = self._read(self.cceo, profile_acts.for_school(self.school))
        rows = {row.id: row for row in acts.planned["rows"]}
        self.assertTrue(rows[self.planned.id].can_pick)

        supervisor = self._read(self.pl, profile_acts.for_school(self.school))
        self.assertFalse(any(row.can_pick for row in supervisor.planned["rows"]))


class GroupDrawers(GroupFixture):
    def setUp(self):
        super().setUp()
        self.client.login(email=self.cceo.email, password=PASSWORD)

    def _ids(self, *activities) -> str:
        return ",".join(a.id for a in activities)

    def test_the_reschedule_drawer_says_what_moves_and_what_stays(self):
        visit = self._visit(self.fresh)

        response = self.client.get(
            RESCHEDULE_URL, {"ids": self._ids(visit, self.delivered)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.id for p in response.context["ready"]], [visit.id])
        self.assertEqual([p.id for p in response.context["left"]], [self.delivered.id])
        html = response.content.decode()
        self.assertIn(f'name="activity_ids" value="{visit.id}"', html)
        self.assertNotIn(f'name="activity_ids" value="{self.delivered.id}"', html)
        self.assertIn('name="scheduled_date"', html)
        self.assertIn("Reschedule 1 activity", html)

    def test_a_drawer_with_nothing_ticked_says_so(self):
        response = self.client.get(RESCHEDULE_URL, {"ids": ""})

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Tick at least one activity", status_code=400)

    def test_posting_moves_them_and_reloads_with_the_summary(self):
        first, second = self._visit(self.fresh), self._visit(self.fresh_two)
        new_day = _weekday(15)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                RESCHEDULE_URL,
                {
                    "activity_ids": [first.id, second.id],
                    "scheduled_date": new_day.isoformat(),
                    "reason": "Holiday week",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        flashed = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("2 activities moved" in m for m in flashed), flashed)
        first.refresh_from_db()
        self.assertEqual(first.planned_date, new_day)
        logged = AuditLog.objects.filter(
            action="reschedule_activity", subject_id__in=[first.id, second.id]
        )
        self.assertEqual(logged.count(), 2)

    def test_a_move_that_changes_nothing_keeps_the_drawer_open(self):
        response = self.client.post(
            RESCHEDULE_URL,
            {
                "activity_ids": [self.delivered.id],
                "scheduled_date": _weekday(15).isoformat(),
                "reason": "Holiday week",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-drawer-stay-open", html)
        self.assertIn("Nothing was moved", html)
        self.assertIn("carried out", html)

    def test_the_cancel_drawer_and_its_post(self):
        visit = self._visit(self.fresh)

        drawer = self.client.get(CANCEL_URL, {"ids": self._ids(visit, self.verified)})
        self.assertEqual(drawer.status_code, 200)
        self.assertEqual([p.id for p in drawer.context["ready"]], [visit.id])
        self.assertContains(drawer, "Cancel 1 activity")

        refused = self.client.post(
            CANCEL_URL,
            {"activity_ids": [visit.id], "reason": ""},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(refused.status_code, 400)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                CANCEL_URL,
                {"activity_ids": [visit.id], "reason": "School closed"},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 204)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "cancelled")
        self.assertEqual(visit.last_reason, "School closed")

    def test_a_reader_without_my_plan_has_no_door(self):
        from apps.accounts.models import User

        outsider = User.objects.create_user(
            email="group-rvp@edify.org",
            name="Group RVP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password=PASSWORD,
            is_active=True,
        )
        self.client.login(email=outsider.email, password=PASSWORD)

        response = self.client.get(RESCHEDULE_URL, {"ids": self.planned.id})

        self.assertIn(response.status_code, (302, 403))


class DatesKeepTheirSpacing(GroupFixture):
    def test_a_day_of_visits_lands_on_the_new_day_together(self):
        """The case the bar is for: a day's visits, ticked, moved as a day."""
        day = _weekday(6)
        first, second = self._visit(self.fresh), self._visit(self.fresh_two)
        self.assertEqual((first.planned_date, second.planned_date), (day, day))
        new_day = day + datetime.timedelta(days=7)

        self._move([first.id, second.id], new_day)

        days = set(
            Activity.objects.filter(id__in=[first.id, second.id]).values_list(
                "planned_date", flat=True
            )
        )
        self.assertEqual(days, {new_day})
