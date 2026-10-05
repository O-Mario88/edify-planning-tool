"""An in-school Training and its School Visit change together.

Owner, 2026-09-28: the training and the visit it rides on are one mission on
one day. The Edit drawer and the group actions kept the two records together;
the single Reschedule and Cancel doors changed whichever record was open and
left the other where it was: a training on Thursday with its visit still on
Tuesday, or a cancelled visit under a training still on the plan.

What is pinned here: either half takes the other with it, on the page and in
the API; a refusal part-way leaves both as they were and says which half; a
half that is already called off or already carried out is not touched; and
both drawers say so before anyone confirms.
"""

from __future__ import annotations

from unittest import mock

from apps.activities import pairs, services
from apps.activities.test_activity_editing import _weekday
from apps.activities.test_group_actions import GroupFixture
from apps.activities.test_profile_activities import PASSWORD
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest

REASON = "The head teacher asked for another day"


def _payload(day, **more):
    return {
        "scheduledDate": day.isoformat(),
        "reason": REASON,
        "plannedMonth": day.month,
        "plannedWeek": min(5, (day.day - 1) // 7 + 1),
        **more,
    }


class PairFixture(GroupFixture):
    def setUp(self):
        super().setUp()
        self.training, self.visit = self._pair()
        self.old_day = self.training.planned_date
        self.new_day = _weekday(15)

    def _move(self, activity, day=None, **more):
        with self.captureOnCommitCallbacks(execute=True):
            return pairs.reschedule(
                activity.id, _payload(day or self.new_day, **more), self.cceo
            )

    def _call_off(self, activity, reason="Term closed early"):
        with self.captureOnCommitCallbacks(execute=True):
            return pairs.cancel(activity.id, {"reason": reason}, self.cceo)

    def _reread(self):
        self.training.refresh_from_db()
        self.visit.refresh_from_db()


class WhichHalfJoins(PairFixture):
    def test_each_half_names_the_other(self):
        self.assertEqual(pairs.other_half(self.training).id, self.visit.id)
        self.assertEqual(pairs.other_half(self.visit).id, self.training.id)

    def test_an_ordinary_visit_has_no_other_half(self):
        alone = self._visit(self.fresh_two)

        self.assertIsNone(pairs.other_half(alone))
        self.assertIsNone(pairs.joins(alone, action=pairs.CANCEL))

    def test_a_half_already_called_off_does_not_join(self):
        services.cancel(self.visit.id, {"reason": "Split before the fix"}, self.cceo)

        self.assertIsNone(pairs.joins(self.training, action=pairs.RESCHEDULE))
        self.assertIsNone(pairs.joins(self.training, action=pairs.CANCEL))

    def test_a_half_already_carried_out_keeps_its_day_and_is_not_cancelled(self):
        type(self.visit).objects.filter(id=self.visit.id).update(status="completed")

        self.assertIsNone(pairs.joins(self.training, action=pairs.RESCHEDULE))
        self.assertIsNone(pairs.joins(self.training, action=pairs.CANCEL))


class Rescheduling(PairFixture):
    def test_moving_the_training_moves_its_visit(self):
        result = self._move(self.training)

        self._reread()
        self.assertEqual(result["id"], self.training.id)
        for half in (self.training, self.visit):
            self.assertEqual(half.planned_date, self.new_day)
            self.assertEqual(half.status, "rescheduled")
            self.assertEqual(half.reschedule_count, 1)
            self.assertEqual(half.last_reason, REASON)

    def test_moving_the_visit_moves_its_training(self):
        result = self._move(self.visit)

        self._reread()
        self.assertEqual(result["id"], self.visit.id)
        self.assertEqual(self.training.planned_date, self.new_day)
        self.assertEqual(self.visit.planned_date, self.new_day)

    def test_the_visit_still_carries_the_cost_and_the_training_none(self):
        """Whichever half is moved first."""
        for asked, day in ((self.training, self.new_day), (self.visit, _weekday(22))):
            with self.subTest(asked=asked.activity_type):
                self._move(asked, day)

                self._reread()
                self.assertEqual(self.training.planned_date, day)
                self.assertEqual(self.visit.planned_date, day)
                self.assertEqual(self.training.est_cost_cents or 0, 0)
                self.assertGreater(self.visit.est_cost_cents or 0, 0)

    def test_a_half_that_refuses_leaves_both_where_they_were(self):
        real = services.reschedule

        def refuse_the_visit(activity_id, data, principal):
            if activity_id == self.visit.id:
                raise BadRequest("Scheduling blocked: approved leave")
            return real(activity_id, data, principal)

        with mock.patch.object(services, "reschedule", side_effect=refuse_the_visit):
            with self.assertRaises(BadRequest) as refused:
                self._move(self.training)

        message = str(refused.exception.detail)
        self.assertIn("school visit on the same day could not be moved", message)
        self.assertIn("neither was changed", message)
        self.assertIn("Scheduling blocked: approved leave", message)
        self._reread()
        for half in (self.training, self.visit):
            self.assertEqual(half.planned_date, self.old_day)
            self.assertEqual(half.reschedule_count, 0)

    def test_a_refusal_of_the_other_half_keeps_its_kind(self):
        """Refused permission stays refused permission, with which half it
        was said of in front; it does not become a bad request."""
        from apps.core.exceptions import Forbidden

        real = services.reschedule

        def refuse_the_visit(activity_id, data, principal):
            if activity_id == self.visit.id:
                raise Forbidden("Only its owner may move this visit.")
            return real(activity_id, data, principal)

        with mock.patch.object(services, "reschedule", side_effect=refuse_the_visit):
            with self.assertRaises(Forbidden) as refused:
                self._move(self.training)

        message = str(refused.exception.detail)
        self.assertTrue(message.startswith("The school visit on the same day"))
        self.assertTrue(message.endswith("Only its owner may move this visit."))
        self._reread()
        self.assertEqual(self.training.planned_date, self.old_day)

    def test_a_refusal_that_is_not_a_sentence_is_replaced_by_ours(self):
        real = services.reschedule

        def refuse_the_visit(activity_id, data, principal):
            if activity_id == self.visit.id:
                raise BadRequest({"scheduledDate": ["not this day"]})
            return real(activity_id, data, principal)

        with mock.patch.object(services, "reschedule", side_effect=refuse_the_visit):
            with self.assertRaises(BadRequest) as refused:
                self._move(self.training)

        self.assertEqual(
            str(refused.exception.detail),
            "The school visit on the same day could not be moved, and the two "
            "go together, so neither was changed.",
        )

    def test_its_own_refusal_is_said_in_the_services_own_words(self):
        """A day that has passed is refused for the record that was asked
        for, as it always was, and neither half moves."""
        import datetime

        from django.utils import timezone

        yesterday = timezone.localdate() - datetime.timedelta(days=1)

        with self.assertRaises(BadRequest) as refused:
            self._move(self.visit, yesterday)

        self.assertIn("has passed", str(refused.exception.detail))
        self.assertNotIn("go together", str(refused.exception.detail))
        self._reread()
        self.assertEqual(self.training.planned_date, self.old_day)
        self.assertEqual(self.visit.planned_date, self.old_day)

    def test_a_cancelled_visit_is_not_brought_back(self):
        """Rescheduling a cancelled activity revives it: a visit called off
        on its own before this fix must not return with the training."""
        services.cancel(self.visit.id, {"reason": "Split before the fix"}, self.cceo)

        self._move(self.training)

        self._reread()
        self.assertEqual(self.training.planned_date, self.new_day)
        self.assertEqual(self.visit.status, "cancelled")
        self.assertEqual(self.visit.planned_date, self.old_day)

    def test_a_half_already_on_the_day_is_not_counted_a_second_move(self):
        """A pair split before this fix is brought back together by moving
        the half that stayed behind."""
        with self.captureOnCommitCallbacks(execute=True):
            services.reschedule(self.training.id, _payload(self.new_day), self.cceo)

        self._move(self.visit)

        self._reread()
        self.assertEqual(self.visit.planned_date, self.new_day)
        self.assertEqual(self.training.planned_date, self.new_day)
        self.assertEqual(self.training.reschedule_count, 1)

    def test_the_other_half_is_given_the_day_and_the_reason_only(self):
        before = self.visit.expected_participants

        self._move(self.training, expectedParticipants=33)

        self._reread()
        self.assertEqual(self.training.expected_participants, 33)
        self.assertEqual(self.visit.expected_participants, before)

    def test_an_ordinary_visit_goes_straight_through(self):
        alone = self._visit(self.fresh_two)

        self._move(alone)

        alone.refresh_from_db()
        self._reread()
        self.assertEqual(alone.planned_date, self.new_day)
        self.assertEqual(self.training.planned_date, self.old_day)


class Cancelling(PairFixture):
    def test_cancelling_the_training_cancels_its_visit(self):
        self._call_off(self.training)

        self._reread()
        for half in (self.training, self.visit):
            self.assertEqual(half.status, "cancelled")
            self.assertEqual(half.last_reason, "Term closed early")

    def test_cancelling_the_visit_cancels_its_training(self):
        self._call_off(self.visit)

        self._reread()
        self.assertEqual(self.training.status, "cancelled")
        self.assertEqual(self.visit.status, "cancelled")

    def test_a_reason_is_still_required_and_nothing_is_cancelled_without_one(self):
        with self.assertRaises(BadRequest):
            self._call_off(self.training, reason="  ")

        self._reread()
        self.assertNotEqual(self.training.status, "cancelled")
        self.assertNotEqual(self.visit.status, "cancelled")

    def test_a_finished_half_is_left_alone(self):
        type(self.visit).objects.filter(id=self.visit.id).update(status="completed")

        self._call_off(self.training)

        self._reread()
        self.assertEqual(self.training.status, "cancelled")
        self.assertEqual(self.visit.status, "completed")

    def test_a_half_that_refuses_leaves_both_on_the_plan(self):
        real = services.cancel

        def refuse_the_training(activity_id, data, principal, **kwargs):
            if activity_id == self.training.id:
                raise BadRequest("Its week has been submitted.")
            return real(activity_id, data, principal, **kwargs)

        with mock.patch.object(services, "cancel", side_effect=refuse_the_training):
            with self.assertRaises(BadRequest) as refused:
                self._call_off(self.visit)

        self.assertIn("could not be cancelled", str(refused.exception.detail))
        self.assertIn("Its week has been submitted.", str(refused.exception.detail))
        self._reread()
        self.assertNotEqual(self.training.status, "cancelled")
        self.assertNotEqual(self.visit.status, "cancelled")


class TheDoorsOnThePage(PairFixture):
    def setUp(self):
        super().setUp()
        self.client.login(email=self.cceo.email, password=PASSWORD)

    def _audited(self, action):
        return set(
            AuditLog.objects.filter(action=action, success=True).values_list(
                "subject_id", flat=True
            )
        )

    def test_the_reschedule_drawer_says_the_visit_moves_too(self):
        response = self.client.get(
            f"/my-plan/{self.training.id}/reschedule-drawer", HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-pair-joins")
        self.assertContains(response, "School Visit on the same day moves with it")

    def test_an_ordinary_visit_has_no_such_notice(self):
        alone = self._visit(self.fresh_two)

        response = self.client.get(
            f"/my-plan/{alone.id}/reschedule-drawer", HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-pair-joins")

    def test_saving_a_new_date_moves_both_and_audits_both(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{self.training.id}/reschedule",
                {"scheduled_date": self.new_day.isoformat(), "reason": REASON},
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self._reread()
        self.assertEqual(self.training.planned_date, self.new_day)
        self.assertEqual(self.visit.planned_date, self.new_day)
        self.assertLessEqual(
            {self.training.id, self.visit.id}, self._audited("reschedule_activity")
        )

    def test_the_cancel_drawer_says_the_training_is_cancelled_too(self):
        response = self.client.get(
            f"/my-plan/{self.visit.id}/cancel-drawer", HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-pair-joins")
        self.assertContains(response, "on the same day is cancelled with it")

    def test_cancelling_from_the_page_cancels_both_and_audits_both(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{self.visit.id}/cancel",
                {"reason": "Term closed early"},
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        self._reread()
        self.assertEqual(self.training.status, "cancelled")
        self.assertEqual(self.visit.status, "cancelled")
        self.assertLessEqual(
            {self.training.id, self.visit.id}, self._audited("cancel_activity")
        )


class TheDoorsInTheApi(PairFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cceo)

    def test_the_api_reschedule_moves_both(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/activities/{self.visit.id}/reschedule",
                _payload(self.new_day),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content[:200])
        self._reread()
        self.assertEqual(self.training.planned_date, self.new_day)
        self.assertEqual(self.visit.planned_date, self.new_day)

    def test_the_api_cancel_stops_both(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/activities/{self.training.id}/cancel",
                {"reason": "Term closed early"},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200, response.content[:200])
        self._reread()
        self.assertEqual(self.training.status, "cancelled")
        self.assertEqual(self.visit.status, "cancelled")
