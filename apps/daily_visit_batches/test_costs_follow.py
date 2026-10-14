"""A save answers first, and its costs end exactly where they did.

Owner, 2026-10-13, after production was read with the day priced in one pass
(a reschedule 2.0 to 2.6 seconds, a new visit 1.9 to 3.1): "reduced the load,
save and reschedule time further to 1 second or less", and of the way to do
it, the answer first and the costs after it: "yes build option 1".

Held here:

* Nothing a save writes has moved. Each plan is carried out twice on the same
  records, once priced inside the save and once answered first and then
  settled, and the whole database is compared between the two: every table,
  the cost snapshots, audit entries and events included. The entries are the
  same entries; only their place in the audit sequence differs, because the
  save's own entry is now written before its days are priced.
* What the pricing would have refused, the save still refuses, in the same
  words, with nothing written down.
* What was kept is written down in the save's transaction, done once, and
  settled for whoever needs the figures before they read them.
* The answer takes far fewer statements than the save did.
"""

from __future__ import annotations

import collections
from datetime import datetime, timedelta
from unittest import mock

from django.db import connection, transaction
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.activities import group_actions
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.services import cancel, reschedule
from apps.audit.models import AuditLog
from apps.budget.models import ActivityCostSnapshot, CostSetting
from apps.core import request_context
from apps.core.exceptions import BadRequest

from . import costs_follow
from .models import CostsToFollow, DailyVisitBatch
from .test_day_priced_once import (
    HISTORY,
    MON,
    THU,
    TUE,
    WED,
    _ADayOfVisits,
    _Compared,
    _everything,
    _nearest,
    _without_step_numbers,
)

REASON = "Head teacher asked for another day"


def _at_nine(day) -> datetime:
    return timezone.make_aware(datetime(day.year, day.month, day.day, 9, 0))


class _AnswerFirst(_ADayOfVisits):
    def setUp(self):
        super().setUp()
        # A save keeps its costs only where there is a request to answer.
        request_context.set_request_context(
            request_context.RequestContext(
                ip_address="10.1.2.3",
                user_agent="test-agent",
                correlation_id="the-request-that-saved",
            )
        )
        self.addCleanup(request_context._current.set, None)
        costs_follow._asked_here.set([])
        self.addCleanup(costs_follow._asked_here.set, None)

    def move(self, activity_id, day):
        return reschedule(
            activity_id,
            {"scheduledDate": _at_nine(day).isoformat(), "reason": REASON},
            self.user,
        )

    def both_ways(self, setup, act):
        """`setup()` then `act(made)`, once priced inside the save and once
        answered first and then settled. Returns (comparison, statements of
        the save each way, rows written down the second way)."""
        states, statements, written = [], [], []
        for first in (False, True):
            costs_follow._asked_here.set([])
            with transaction.atomic():
                made = setup()
                with override_settings(SAVES_ANSWER_FIRST=first):
                    with CaptureQueriesContext(connection) as queries:
                        act(made)
                statements.append(len(queries))
                written.append(CostsToFollow.objects.count())
                costs_follow.settle()
                self.assertFalse(CostsToFollow.objects.exists())
                states.append(_everything())
                transaction.set_rollback(True)
        self.assertEqual(written[0], 0)
        return _Compared(*states, started="2026-07-27"), statements, written[1]

    def assertNothingMoved(self, compared, *, steps_between_left_out=False):
        """Every table ends the same. In the history the entries are the same
        entries; where each sits in its sequence is set aside.

        `steps_between_left_out`: the history of the save that answered
        first is part of the other's, which also holds the pricings in
        between that the next one replaced."""
        for table in sorted(compared.tables):
            inside, after = compared.rows(table)
            if table in HISTORY:
                inside = collections.Counter(
                    _without_step_numbers(text) for text in inside.elements()
                )
                after = collections.Counter(
                    _without_step_numbers(text) for text in after.elements()
                )
                if steps_between_left_out and not (after - inside):
                    self.assertTrue(inside - after, table)
                    inside = after
            for text in (after - inside) or (inside - after):
                self.fail(
                    f"{table} ends differently when the save answers first: "
                    + _nearest(text, inside if text in after else after)
                )


class NothingMovedTest(_AnswerFirst):
    def test_a_visit_moves_between_two_full_days(self):
        """The case the owner timed: one visit from a day of five to a day
        of four re-prices nine visits."""

        def setup():
            first = self.plan(MON, self.near[:5])["created"]
            self.plan(TUE, self.near[5:9])
            return first

        compared, (inside, answer), written = self.both_ways(
            setup, lambda first: self.move(first[0], TUE)
        )
        self.assertNothingMoved(compared)
        self.assertEqual(written, 1)
        for table in (
            "activity",
            "activity_cost_snapshot",
            "activity_schedule_cost_line",
            "advance_request",
            "audit_log",
            "daily_visit_batch",
            "fund_request_item",
            "weekly_fund_request_line",
        ):
            self.assertIn(table, compared.tables)
        self.assertLess(answer, inside * 0.6)

    def test_a_visit_moves_to_an_empty_day(self):
        compared, _statements, _written = self.both_ways(
            lambda: self.plan(MON, self.near[:2])["created"],
            lambda created: self.move(created[0], WED),
        )
        self.assertNothingMoved(compared)

    def test_days_away_with_their_nights(self):
        """A day in a secondary district shares the night, and its
        neighbours are re-priced when it changes which of them is the day
        home: the day left is priced before the day joined, as it was."""

        def setup():
            self.plan(MON, self.far[:2] + self.near[:1])
            self.plan(TUE, self.far[2:4])
            return self.plan(WED, self.far[4:6])["created"]

        compared, _statements, _written = self.both_ways(
            setup, lambda created: self.move(created[0], THU)
        )
        self.assertNothingMoved(compared)

    def test_a_visit_moves_onto_the_day_beside_a_day_away(self):
        def setup():
            self.plan(MON, self.far[:2])
            return self.plan(WED, self.far[2:4])["created"]

        compared, _statements, _written = self.both_ways(
            setup, lambda created: self.move(created[0], TUE)
        )
        self.assertNothingMoved(compared)

    def test_a_visit_is_cancelled_off_a_day_of_four(self):
        compared, (inside, answer), written = self.both_ways(
            lambda: self.plan(MON, self.near[:4])["created"],
            lambda created: cancel(
                created[1], {"reason": "School closed for the day"}, self.user
            ),
        )
        self.assertNothingMoved(compared)
        self.assertEqual(written, 1)
        self.assertLess(answer, inside)

    def test_a_new_visit_joins_a_day_of_two(self):
        """Scheduled on its own, not as a cluster's day (which prices its
        day once, inside the save, and reads the result)."""

        def act(_made):
            with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=False):
                self.plan(MON, self.near[2:3])

        compared, (inside, answer), written = self.both_ways(
            lambda: self.plan(MON, self.near[:2]), act
        )
        self.assertNothingMoved(compared)
        self.assertEqual(written, 1)
        self.assertLess(answer, inside)

    def test_three_visits_scheduled_one_after_another_in_one_save(self):
        """Each writes down the day, and the day is priced once for the
        three, as a cluster's day is: the figures are the same, and what is
        not recorded is the pricing of one visit and of two that the third
        replaced (owner, 2026-10-06, of a day priced once)."""

        def act(_made):
            with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=False):
                self.plan(TUE, self.near[:3])

        compared, _statements, written = self.both_ways(lambda: None, act)
        self.assertNothingMoved(compared, steps_between_left_out=True)
        self.assertEqual(written, 3)
        _inside, after = compared.rows("activity_cost_snapshot")
        self.assertEqual(sum(after.values()), 3)

    def test_a_group_of_moves(self):
        def setup():
            return self.plan(MON, self.near[:5])["created"]

        def act(created):
            outcome = group_actions.reschedule(
                created[:3], TUE.isoformat(), REASON, self.user
            )
            self.assertEqual(len(outcome.done), 3)

        compared, (inside, answer), written = self.both_ways(setup, act)
        self.assertNothingMoved(compared)
        self.assertEqual(written, 1)
        self.assertLess(answer, inside)

    def test_a_group_of_cancellations(self):
        def act(created):
            outcome = group_actions.cancel(created[:2], "School closed", self.user)
            self.assertEqual(len(outcome.done), 2)

        compared, _statements, written = self.both_ways(
            lambda: self.plan(MON, self.near[:4])["created"], act
        )
        self.assertNothingMoved(compared)
        self.assertEqual(written, 1)


class WhatIsRefusedIsStillRefusedTest(_AnswerFirst):
    def _each_way(self, act):
        """The words `act` is refused in, priced inside and answered first,
        with nothing of it left either way."""
        said = []
        for first in (False, True):
            before = (
                ActivityCostSnapshot.objects.count(),
                sorted(Activity.objects.values_list("id", "planned_date", "status")),
            )
            with override_settings(SAVES_ANSWER_FIRST=first):
                with self.assertRaises(BadRequest) as refused:
                    act()
            said.append(str(refused.exception.detail))
            self.assertEqual(
                before,
                (
                    ActivityCostSnapshot.objects.count(),
                    sorted(
                        Activity.objects.values_list("id", "planned_date", "status")
                    ),
                ),
            )
            self.assertFalse(CostsToFollow.objects.exists())
        self.assertEqual(said[0], said[1])
        return said[0]

    def test_a_member_of_the_day_left_whose_advance_is_confirmed(self):
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        created = self.plan(MON, self.near[:4])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=created[2]).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )
        said = self._each_way(lambda: self.move(created[0], TUE))
        self.assertIn("accountant", said)

    def test_a_member_of_the_day_joined_whose_advance_was_paid(self):
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        created = self.plan(MON, self.near[:2])["created"]
        there = self.plan(TUE, self.near[2:4])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=there[1]).update(
            status=AdvanceRequestStatus.DISBURSED
        )
        said = self._each_way(lambda: self.move(created[0], TUE))
        self.assertIn("disbursed", said)

    def test_the_first_day_to_refuse_is_the_one_that_answers(self):
        """The day left is asked before the day joined, as it was priced
        before it."""
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        created = self.plan(MON, self.near[:2])["created"]
        there = self.plan(TUE, self.near[2:4])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=there[0]).update(
            status=AdvanceRequestStatus.DISBURSED
        )
        AdvanceRequest.objects.filter(budget_line__activity_id=created[1]).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )
        said = self._each_way(lambda: self.move(created[0], TUE))
        self.assertIn("accountant", said)

    def test_a_cancellation_that_would_re_price_paid_work(self):
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        created = self.plan(MON, self.near[:3])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=created[2]).update(
            status=AdvanceRequestStatus.DISBURSED
        )
        self._each_way(
            lambda: cancel(created[0], {"reason": "School closed"}, self.user)
        )

    def test_a_day_whose_rates_are_gone(self):
        """A day in a secondary district with no rate for the night."""
        created = self.plan(MON, self.near[:2])["created"]
        self.plan(TUE, self.far[:2])
        school = self.far[0]
        visit = Activity.objects.get(school=school, planned_date=TUE)
        CostSetting.objects.filter(
            catalogue=self.catalogue, key__icontains="accommodation"
        ).delete()
        CostSetting.objects.filter(
            catalogue=self.catalogue, key__icontains="secondary"
        ).delete()
        self.assertTrue(created)
        self._each_way(lambda: self.move(visit.id, WED))

    def test_a_day_whose_transport_has_been_paid(self):
        from apps.fund_requests.finance_models import TransportPayment
        from apps.fund_requests.vendor_channel import TRANSPORT_PAID

        # The only visit of a paid day: moved off it, the provider would be
        # owed nothing for a day already paid.
        created = self.plan(MON, self.near[:1])["created"]
        self.assertTrue(
            TransportPayment.objects.filter(batch__visit_date=MON).update(status="paid")
        )
        said = self._each_way(lambda: self.move(created[0], TUE))
        self.assertEqual(said, TRANSPORT_PAID)


class WhatIsKeptTest(_AnswerFirst):
    def _moved(self):
        created = self.plan(MON, self.near[:3])["created"]
        self.plan(TUE, self.near[3:5])
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.move(created[0], TUE)
        return created

    def test_the_answer_leaves_the_days_as_they_were_priced(self):
        created = self.plan(MON, self.near[:3])["created"]
        self.plan(TUE, self.near[3:5])
        snapshots = ActivityCostSnapshot.objects.count()
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.move(created[0], TUE)
        moved = Activity.objects.get(id=created[0])
        self.assertEqual(moved.planned_date, TUE)
        self.assertEqual(moved.daily_visit_batch.visit_date, TUE)
        self.assertEqual(ActivityCostSnapshot.objects.count(), snapshots)
        row = CostsToFollow.objects.get()
        self.assertEqual(row.owners, [self.user.id])
        self.assertEqual(row.asked_by, self.user.id)
        self.assertEqual(
            [
                DailyVisitBatch.objects.get(id=batch_id).visit_date
                for batch_id, _owner in row.steps["days"]
            ],
            [MON, TUE],
        )
        self.assertEqual(
            [note["kind"] for note in row.steps["notes"]], ["reschedule_note"]
        )

        self.assertEqual(costs_follow.settle(), 1)
        self.assertEqual(ActivityCostSnapshot.objects.count(), snapshots + 5)
        self.assertEqual(
            sorted(DailyVisitBatch.objects.values_list("visit_date", "school_count")),
            [(MON, 2), (TUE, 3)],
        )
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(
                activity=moved, description__contains="Rescheduled due to"
            ).exists()
        )
        self.assertEqual(costs_follow.settle(), 0)

    def test_the_pricing_is_recorded_as_the_request_that_saved(self):
        self._moved()
        request_context.set_request_context(
            request_context.RequestContext(
                ip_address="10.9.9.9", user_agent="another", correlation_id="another"
            )
        )
        costs_follow.settle()
        priced = AuditLog.objects.filter(action="activity.cost.calculated").order_by(
            "-seq"
        )[:5]
        self.assertEqual(
            {(entry.correlation_id, entry.ip_address) for entry in priced},
            {("the-request-that-saved", "10.1.2.3")},
        )
        # And the request doing the settling is put back as it was.
        self.assertEqual(
            request_context.get_request_context().correlation_id, "another"
        )

    def test_whoever_needs_the_figures_has_them_settled_first(self):
        self._moved()
        self.assertEqual(costs_follow.settled_first(owner="someone-else"), 0)
        self.assertEqual(costs_follow.settled_first(user="someone-else"), 0)
        self.assertTrue(CostsToFollow.objects.exists())
        self.assertEqual(costs_follow.settled_first(owner=self.user.id), 1)
        self.assertFalse(CostsToFollow.objects.exists())

    def test_the_next_save_in_the_same_request_starts_from_settled_figures(self):
        # Each save's transaction ends before the next begins, which a
        # test's own transaction hides: nothing is left "in hand".
        with mock.patch.object(
            costs_follow, "_when_the_save_commits", lambda row_id, asked_by="": None
        ):
            created = self._moved()
            with override_settings(SAVES_ANSWER_FIRST=True):
                self.move(created[1], TUE)
        row = CostsToFollow.objects.get()
        self.assertEqual(row.steps["notes"][0]["activity"], created[1])

    def test_two_records_of_one_save_are_both_kept(self):
        """An in-school training and its visit are written down one after
        the other inside one transaction; the second does not settle the
        first."""
        created = self.plan(MON, self.near[:3])["created"]
        with override_settings(SAVES_ANSWER_FIRST=True), transaction.atomic():
            self.move(created[0], TUE)
            self.move(created[1], TUE)
            self.assertEqual(CostsToFollow.objects.count(), 2)
        self.assertEqual(costs_follow.settle(), 2)

    def test_a_refusal_met_after_the_answer_holds_the_row(self):
        """Money that moved in the moment between the save and its pricing:
        the save stands, the row is held with the reason and not tried
        again, and the day is one `batch_needs_repricing` finds."""
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        from .services import batch_needs_repricing

        created = self._moved()
        AdvanceRequest.objects.filter(budget_line__activity_id=created[1]).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )
        with self.assertLogs("apps.daily_visit_batches.costs_follow", "ERROR"):
            self.assertEqual(costs_follow.settle(), 0)
        row = CostsToFollow.objects.get()
        self.assertIsNotNone(row.held_at)
        self.assertIn("accountant", row.held_reason)
        self.assertEqual(Activity.objects.get(id=created[0]).planned_date, TUE)
        self.assertEqual(costs_follow.settle(), 0)
        self.assertTrue(
            batch_needs_repricing(DailyVisitBatch.objects.get(visit_date=MON))
        )

    def test_a_failure_is_tried_again_and_then_held(self):
        self._moved()
        with mock.patch.object(costs_follow, "_do", side_effect=RuntimeError("lost")):
            for attempt in range(1, costs_follow.MAX_ATTEMPTS):
                with self.assertLogs("apps.daily_visit_batches.costs_follow", "ERROR"):
                    self.assertEqual(costs_follow.settle(), 0)
                row = CostsToFollow.objects.get()
                self.assertEqual(row.attempts, attempt)
                self.assertIsNone(row.held_at)
            with self.assertLogs("apps.daily_visit_batches.costs_follow", "ERROR"):
                costs_follow.settle()
        row = CostsToFollow.objects.get()
        self.assertIsNotNone(row.held_at)
        self.assertTrue(row.held_reason.startswith("Failed"))
        # The sweep tries a failure again; this time it goes through.
        self.assertEqual(costs_follow.sweep()["retried"], 1)
        self.assertFalse(CostsToFollow.objects.exists())

    def test_the_sweep_takes_what_a_lost_process_left(self):
        self._moved()
        self.assertEqual(costs_follow.sweep()["settled"], 0)  # too fresh
        CostsToFollow.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(costs_follow.sweep(), {"settled": 1, "retried": 0, "held": 0})


class WhenNothingIsKeptTest(_AnswerFirst):
    def test_the_switch_prices_inside_the_save_again(self):
        created = self.plan(MON, self.near[:3])["created"]
        snapshots = ActivityCostSnapshot.objects.count()
        with override_settings(SAVES_ANSWER_FIRST=False):
            self.move(created[0], TUE)
        self.assertFalse(CostsToFollow.objects.exists())
        self.assertGreater(ActivityCostSnapshot.objects.count(), snapshots)

    def test_outside_a_request_there_is_nobody_to_answer(self):
        created = self.plan(MON, self.near[:3])["created"]
        request_context._current.set(None)
        snapshots = ActivityCostSnapshot.objects.count()
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.move(created[0], TUE)
        self.assertFalse(CostsToFollow.objects.exists())
        self.assertGreater(ActivityCostSnapshot.objects.count(), snapshots)

    def test_a_clusters_day_is_priced_inside_its_save(self):
        """It prices its day once and reads the result before it ends."""
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.plan(MON, self.near[:3])
        self.assertFalse(CostsToFollow.objects.exists())
        self.assertEqual(DailyVisitBatch.objects.get(visit_date=MON).school_count, 3)

    def test_a_save_that_needs_its_figures_is_priced_inside_it(self):
        created = self.plan(MON, self.near[:3])["created"]
        snapshots = ActivityCostSnapshot.objects.count()
        from apps.fund_requests import plan_changes

        taken_back = plan_changes.take_back_for_plan_change

        def needs_them(activity, principal, *, days=()):
            costs_follow.priced_in_this_save()
            return taken_back(activity, principal, days=days)

        with (
            override_settings(SAVES_ANSWER_FIRST=True),
            mock.patch.object(plan_changes, "take_back_for_plan_change", needs_them),
        ):
            self.move(created[0], TUE)
        self.assertFalse(CostsToFollow.objects.exists())
        self.assertGreater(ActivityCostSnapshot.objects.count(), snapshots)

    def test_nothing_settled_is_kept_again(self):
        """Doing what was kept never writes more down."""
        created = self.plan(MON, self.near[:3])["created"]
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.move(created[0], TUE)
            self.assertEqual(costs_follow.settle(), 1)
            self.assertFalse(CostsToFollow.objects.exists())


class ThePersonWhoSavedWaitsForTheirFiguresTest(_AnswerFirst):
    def _request(self, *, cookie: bool):
        request = RequestFactory().get("/my-plan")
        request.user = self.user
        if cookie:
            request.COOKIES[costs_follow.COOKIE] = "1"
        return request

    def test_the_answer_to_a_save_that_kept_its_costs_sets_the_cookie(self):
        created = self.plan(MON, self.near[:3])["created"]

        def view(_request):
            with override_settings(SAVES_ANSWER_FIRST=True):
                self.move(created[0], TUE)
            return HttpResponse("saved")

        response = costs_follow.CostsFollowMiddleware(view)(self._request(cookie=False))
        self.assertEqual(
            response.cookies[costs_follow.COOKIE].value,
            str(CostsToFollow.objects.get().id),
        )
        self.assertTrue(response.cookies[costs_follow.COOKIE]["httponly"])
        self.assertTrue(CostsToFollow.objects.exists())

    def test_their_next_request_settles_first_and_the_cookie_goes(self):
        created = self.plan(MON, self.near[:3])["created"]
        with override_settings(SAVES_ANSWER_FIRST=True):
            self.move(created[0], TUE)
        seen = []

        def view(_request):
            seen.append(CostsToFollow.objects.count())
            return HttpResponse("page")

        response = costs_follow.CostsFollowMiddleware(view)(self._request(cookie=True))
        self.assertEqual(seen, [0])
        self.assertEqual(response.cookies[costs_follow.COOKIE]["max-age"], 0)

    def test_the_cookie_names_the_rows_and_the_page_is_told_it_is_after_them(self):
        """The notice of a pricing names its rows; so does the answer to the
        request that waited for them, so the page that saved knows the
        notice whatever the two clocks say (`live.after_costs`)."""
        created = self.plan(MON, self.near[:3])["created"]

        def view(_request):
            with override_settings(SAVES_ANSWER_FIRST=True):
                self.move(created[0], TUE)
            return HttpResponse("saved")

        saved = costs_follow.CostsFollowMiddleware(view)(self._request(cookie=False))
        row = CostsToFollow.objects.get()
        self.assertEqual(saved.cookies[costs_follow.COOKIE].value, str(row.id))
        self.assertNotIn(costs_follow.AFTER_HEADER, saved)

        request = self._request(cookie=False)
        request.COOKIES[costs_follow.COOKIE] = str(row.id)
        page = costs_follow.CostsFollowMiddleware(
            lambda _request: HttpResponse("page")
        )(request)
        self.assertFalse(CostsToFollow.objects.exists())
        self.assertEqual(page[costs_follow.AFTER_HEADER], str(row.id))

    def test_a_cookie_is_read_as_row_numbers_and_nothing_else(self):
        self.assertEqual(costs_follow._rows_named("12.13"), ["12", "13"])
        self.assertEqual(costs_follow._rows_named("1"), ["1"])
        self.assertEqual(
            costs_follow._rows_named("12.<script>.-3.1e4. 5.14"), ["12", "14"]
        )
        self.assertEqual(costs_follow._rows_named(None), [])
        request = self._request(cookie=False)
        request.COOKIES[costs_follow.COOKIE] = "not-a-row"
        page = costs_follow.CostsFollowMiddleware(
            lambda _request: HttpResponse("page")
        )(request)
        self.assertNotIn(costs_follow.AFTER_HEADER, page)

    def test_a_request_without_the_cookie_asks_nothing(self):
        middleware = costs_follow.CostsFollowMiddleware(
            lambda _request: HttpResponse("page")
        )
        with CaptureQueriesContext(connection) as queries:
            response = middleware(self._request(cookie=False))
        self.assertEqual(len(queries), 0)
        self.assertNotIn(costs_follow.COOKIE, response.cookies)


class EveryOpenPageIsToldOnceTheCostsAreInTest(_AnswerFirst):
    """A save announces itself to every open page that shows the plan, and
    each reads itself again (apps.activities.live). Owner, 2026-10-14: "I
    hope everything you have done does not affect the live update of data
    after clicking save or reschedule". Told at the save's own commit, a
    Program Lead's page read itself before the day was priced and again
    after (seen in two browsers with the pricing slowed to a second and a
    half). The save's announcement now goes out with the pricing's."""

    def setUp(self):
        super().setUp()
        from apps.activities import live

        # Turned on here, not on the class: the fixture's frozen clock sets
        # the class up as its base, and a class's own settings never apply.
        self.enterContext(override_settings(LIVE_UPDATES_ENABLED=True))
        live.reset()
        self.addCleanup(live.reset)

    def _moved(self, *, first: bool):
        """A move with the commit's hooks run. Returns (what was pushed at
        the commit, what the thread after the answer was handed)."""
        created = self.plan(MON, self.near[:3])["created"]
        self.plan(TUE, self.near[3:5])
        with (
            mock.patch("apps.realtime.bus.bus.publish_many") as pushed,
            mock.patch.object(costs_follow, "_settle_in_a_thread") as thread,
            override_settings(SAVES_ANSWER_FIRST=first),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.move(created[0], TUE)
        return pushed, thread

    def test_nothing_is_pushed_when_the_save_commits(self):
        pushed, thread = self._moved(first=True)
        pushed.assert_not_called()
        thread.assert_called_once()
        rows = thread.call_args.args[0]
        self.assertEqual(rows, list(CostsToFollow.objects.values_list("id", flat=True)))
        # What the save asked to announce went with the rows, to be told
        # once they are settled, and the thread knows who asked.
        self.assertTrue(thread.call_args.kwargs["tell"])
        self.assertEqual(thread.call_args.kwargs["askers"], frozenset({self.user.id}))

    def test_priced_inside_the_save_it_is_pushed_at_the_commit_as_before(self):
        pushed, thread = self._moved(first=False)
        pushed.assert_called()
        thread.assert_not_called()

    def test_the_pricing_pushes_when_it_commits(self):
        """Settled by whoever gets there (the thread, the person's next
        request, the sweep), the pricing saves each visit of the day and
        that is announced with its commit."""
        self._moved(first=True)
        with mock.patch("apps.realtime.bus.bus.publish_many") as pushed:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(costs_follow.settle(), 1)
        pushed.assert_called()
        told = {user for call in pushed.call_args_list for user in call.args[0]}
        self.assertIn(self.user.id, told)

    def test_the_notice_of_a_pricing_names_the_rows_it_settled(self):
        self._moved(first=True)
        row = CostsToFollow.objects.get()
        with mock.patch("apps.realtime.bus.bus.publish_many") as pushed:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(costs_follow.settle(), 1)
        self.assertEqual(
            {call.args[1].get("after") for call in pushed.call_args_list},
            {str(row.id)},
        )

    def test_a_notice_of_anything_else_names_nothing(self):
        pushed, _thread = self._moved(first=False)
        for call in pushed.call_args_list:
            self.assertNotIn("after", call.args[1])

    def test_what_the_save_asked_is_told_after_the_pricing(self):
        from apps.activities import live

        _pushed, thread = self._moved(first=True)
        with mock.patch("apps.realtime.bus.bus.publish_many") as pushed:
            live.publish(thread.call_args.kwargs["tell"])
        pushed.assert_called()
        self.assertEqual(pushed.call_args.args[1]["type"], "plan.changed")

    def test_a_save_undone_inside_a_larger_one_leaves_its_notice_at_the_commit(self):
        """The costs' part of the transaction is undone to a savepoint and
        the rest commits: nothing follows, so what the rest announced is
        pushed at the commit, as it always was."""
        created = self.plan(MON, self.near[:3])["created"]
        self.plan(TUE, self.near[3:5])
        with (
            mock.patch("apps.realtime.bus.bus.publish_many") as pushed,
            mock.patch.object(costs_follow, "_settle_in_a_thread") as thread,
            override_settings(SAVES_ANSWER_FIRST=True),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                kept = Activity.objects.get(id=created[2])
                kept.last_reason = "Noted"
                kept.save(update_fields=["last_reason", "updated_at"])
                try:
                    with transaction.atomic():
                        self.move(created[0], TUE)
                        raise RuntimeError("the larger save gives this part up")
                except RuntimeError:
                    pass
        self.assertFalse(CostsToFollow.objects.exists())
        thread.assert_not_called()
        pushed.assert_called()

    def test_later_records_of_the_same_save_are_told_with_it(self):
        """Whatever the transaction saves after its costs were written down
        (the other half of a pair, a note on the record) is announced with
        them, not at the commit."""
        created = self.plan(MON, self.near[:3])["created"]
        self.plan(TUE, self.near[3:5])
        with (
            mock.patch("apps.realtime.bus.bus.publish_many") as pushed,
            mock.patch.object(costs_follow, "_settle_in_a_thread") as thread,
            override_settings(SAVES_ANSWER_FIRST=True),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    self.move(created[0], TUE)
                    before = len(costs_follow.following(connection).tell)
                    other = Activity.objects.get(id=created[1])
                    other.last_reason = "Noted"
                    other.save(update_fields=["last_reason", "updated_at"])
                    self.assertGreater(
                        len(costs_follow.following(connection).tell), before
                    )
        pushed.assert_not_called()
        thread.assert_called_once()
