"""The day work was done is recorded, and early work frees its planned day.

Owner, 2026-10-16: "add the date filed when the activity (school was visited
or the group training or cluster meeting) was completed on the completion
drawer so that the actual completion date is captured. if an activity is
completed earlier the system should record the actual completion date then
free the planned date for another activity to be rescheduled or planned."
Asked, the owner chose that the date may be today or any earlier day ("some
users complete activities the day after or days after") but never a future
one, and then: "move the money to the completed date as well".

Pinned here:

  1. A visit booked for a later day and completed today moves to today: its
     planned day is recorded as the plan, its cost lines follow it.
  2. The planned day it left takes another visit, priced as its own day.
  3. A future completion date is refused and nothing moves.
  4. The completion drawer asks for the date (today unless changed) and
     refuses a future one.
  5. Completed work leaves the week's workload count.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.services import complete, start_completion
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.daily_visit_batches.models import DailyVisitBatch

# The day-batch suite's fixture (a priced card, a CCEO and their schools),
# borrowed rather than inherited: a subclass would run all its tests again.
from apps.daily_visit_batches import tests as batch_tests
from apps.planning.test_standard_support_scheduling import _schedulable_date


def _monday(day):
    return day - timedelta(days=day.weekday())


class CompletedDayFixture(TestCase):
    _schedule = batch_tests.DailyVisitBatchTestCase._schedule

    def setUp(self):
        # The plain fixture, not the class's frozen setUp: borrowing that
        # starts a freeze nothing here stops, and every later test in the
        # worker then runs on 27 July 2026.
        batch_tests.DailyVisitBatchTestCase._build_fixture(self)
        self.today = timezone.localdate()
        # A planned day well ahead of today, in today's financial year.
        self.plan_day = _schedulable_date(room=30) + timedelta(days=7)
        while self.plan_day.weekday() == 6:
            self.plan_day += timedelta(days=1)
        if get_operational_fy(self.plan_day) != get_operational_fy(self.today):
            self.skipTest("the planned day falls in the next financial year")

    def _visit(self, school="BATCH-P-1", day=None):
        self._schedule([school], day or self.plan_day, reason="visit")
        return Activity.objects.get(
            school__school_id=school, planned_date=day or self.plan_day
        )

    def _complete(self, activity, day, sf="SVE-11223344"):
        start_completion(activity.id, principal=self.principal)
        return complete(
            activity.id,
            {"salesforceId": sf, "actualDeliveryDate": day.isoformat()},
            self.principal,
        )


class TheClockIsNotFrozenTest(CompletedDayFixture):
    def test_the_borrowed_fixture_leaves_no_freeze_running(self):
        from freezegun import api

        self.assertEqual(api.freeze_factories, [])


class EarlyWorkMovesToItsDayTest(CompletedDayFixture):
    def test_the_visit_and_its_money_move_to_the_day_it_was_done(self):
        visit = self._visit()
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(activity=visit).exists(),
            "the fixture must price the visit",
        )

        self._complete(visit, self.today)

        visit.refresh_from_db()
        self.assertEqual(visit.actual_delivery_date, self.today)
        self.assertEqual(visit.planned_date, self.today)
        self.assertEqual(visit.planned_date_before_completion, self.plan_day)
        self.assertEqual(visit.daily_visit_batch.visit_date, self.today)
        weeks = set(
            ActivityScheduleCostLine.objects.filter(activity=visit).values_list(
                "week_start_date", flat=True
            )
        )
        self.assertEqual(weeks, {_monday(self.today)})

    def test_the_planned_day_takes_another_visit_on_its_own(self):
        first = self._visit()
        self._complete(first, self.today)

        second = self._visit("BATCH-P-2")

        batch = DailyVisitBatch.objects.get(
            responsible_user=self.principal.user_id, visit_date=self.plan_day
        )
        members = set(
            batch.activities.filter(deleted_at__isnull=True).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(members, {second.id})

    def test_a_future_completion_date_is_refused_and_nothing_moves(self):
        visit = self._visit()
        with self.assertRaises(BadRequest) as caught:
            self._complete(visit, self.today + timedelta(days=1))
        self.assertIn("future", str(caught.exception.detail).lower())

        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, self.plan_day)
        self.assertIsNone(visit.actual_delivery_date)
        self.assertIsNone(visit.planned_date_before_completion)


class TheDrawerAsksForTheDayTest(CompletedDayFixture):
    def _post(self, activity, **fields):
        client = Client()
        client.force_login(self.staff_user)
        return client.post(
            f"/my-plan/{activity.id}/complete",
            {"salesforce_id": "SVE-55667788", **fields},
            headers={"HX-Request": "true"},
        )

    def test_the_drawer_shows_the_date_field(self):
        visit = self._visit()
        client = Client()
        client.force_login(self.staff_user)
        page = client.get(f"/my-plan/{visit.id}/complete-drawer").content.decode()
        self.assertIn('name="actual_delivery_date"', page)
        self.assertIn(f'max="{self.today.isoformat()}"', page)

    def test_a_post_without_a_date_records_today(self):
        # The drawer always sends one (today unless changed); another client
        # that sends none records today.
        visit = self._visit()
        self._post(visit)
        visit.refresh_from_db()
        self.assertEqual(visit.actual_delivery_date, self.today)

    def test_a_future_date_is_refused(self):
        visit = self._visit()
        self._post(
            visit, actual_delivery_date=(self.today + timedelta(days=2)).isoformat()
        )
        visit.refresh_from_db()
        self.assertIsNone(visit.actual_delivery_date)

    def test_the_day_entered_is_recorded(self):
        visit = self._visit()
        yesterday = self.today - timedelta(days=1)
        self._post(visit, actual_delivery_date=yesterday.isoformat())
        visit.refresh_from_db()
        self.assertEqual(visit.actual_delivery_date, yesterday)


class CompletedWorkLeavesTheWorkloadTest(CompletedDayFixture):
    def test_the_week_count_leaves_out_completed_work(self):
        from apps.core.calendar_policy import SchedulingPolicyService

        # One a day across the planned week: the fixture's card allows three
        # visits a day.
        monday = _monday(self.plan_day)
        visits = [
            self._visit(f"BATCH-P-{n}", day=monday + timedelta(days=n - 1))
            for n in range(1, 6)
        ]
        busy = SchedulingPolicyService.check(self.staff_user, self.plan_day)
        self.assertTrue(any("workload" in w.lower() for w in busy["warnings"]))

        Activity.objects.filter(id__in=[v.id for v in visits]).update(
            status="submitted_to_pl"
        )
        free = SchedulingPolicyService.check(self.staff_user, self.plan_day)
        self.assertFalse(any("workload" in w.lower() for w in free["warnings"]))
