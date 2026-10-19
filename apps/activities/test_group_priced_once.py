"""A group of moves or cancellations prices each day it touches once.

Owner, 2026-10-12, asked whether to price each day once for a whole group,
which "changes what a failure part-way leaves behind": "yes do the group
action change".

A group used to change one activity at a time, each in its own transaction,
and every one of them re-priced the day it left and the day it joined. Three
visits moved off a day of ten priced nine, eight and seven of it and then
one, two and three of the day they joined. The group is now one transaction,
each activity undone to its own savepoint if it is refused, and each day is
priced once when the last activity has been changed.

Held here, each plan carried out both ways on the same records:

* The money ends where it did. Every table is compared; the lines, advances,
  weekly and monthly requests and day pools of work that is still in the plan
  are the same.
* Only the pricings in between are missing from the record: every cost
  snapshot, audit entry and event the new way writes is one the old way
  wrote too.
* Two things differ, and are meant to. Every visit a group moves carries the
  note of its move on its cost lines, where only the one moved last onto a
  day used to keep it (the next visit's pricing wrote the others' lines
  again). And a visit cancelled with others keeps the cost it was planned at
  when the group was cancelled, where the second one cancelled used to be
  re-priced first as if the others had already gone.
* When the pricing at the end refuses, nothing of the attempt is kept and the
  group is changed one at a time, as it always was: the same activities are
  refused in the same words and the rest go through.
"""

from __future__ import annotations

import collections
import json
from unittest import mock

from django.db import connection, transaction
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from apps.activities import group_actions
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import ActivityCostSnapshot
from apps.daily_visit_batches.services import (
    each_day_priced_once,
    once_days_are_priced,
    remove_school,
)
from apps.hr.leave_services import LeaveBudgetImpactService
from apps.daily_visit_batches.test_day_priced_once import (
    HISTORY,
    MON,
    TUE,
    WED,
    _ADayOfVisits,
    _Compared,
    _everything,
    _nearest,
    _without_step_numbers,
)

REASON = "The district moved its meeting"


def _apart_from(text: str, *columns: str) -> str:
    row = json.loads(text)
    for column in columns:
        row.pop(column, None)
    return json.dumps(row, sort_keys=True)


class _Groups(_ADayOfVisits):
    def setUp(self):
        super().setUp()
        #: `facts()` at the end of each way, in the order they were run.
        self.ended = []

    def both_ways(self, setup, act):
        """`setup()` then `act()`, once with the group changed one activity
        at a time and once with its days priced when it ends. Returns
        (comparison, statements each way, outcome each way)."""
        states, statements, outcomes = [], [], []
        for once in (False, True):
            with transaction.atomic():
                made = setup()
                with (
                    override_settings(PRICE_A_DAY_ONCE_PER_SAVE=once),
                    # The note a move writes on its lines is held on its own
                    # (`test_every_visit_moved_carries_the_note_of_its_move`).
                    # Left in, the lines of the two ways would differ by it
                    # and every row that points at a line would with them.
                    mock.patch.object(
                        LeaveBudgetImpactService,
                        "handle_reschedule",
                        lambda *args, **kwargs: None,
                    ),
                ):
                    with CaptureQueriesContext(connection) as queries:
                        outcomes.append(act(made))
                statements.append(len(queries))
                states.append(_everything())
                self.ended.append(self.facts())
                transaction.set_rollback(True)
        return _Compared(*states, started="2026-07-27"), statements, outcomes

    def assertTheMoneyEndsWhereItDid(self, compared, *, apart=None):
        """Every table but the history is the same, apart from the columns
        named for a table in `apart`; the history of the new way is part of
        the history of the old. Returns what the old way wrote beyond it."""
        apart = apart or {}
        surplus = {}
        for table in sorted(compared.tables):
            each, once = compared.rows(table)
            if table in HISTORY:
                each = collections.Counter(
                    _without_step_numbers(text) for text in each.elements()
                )
                once = collections.Counter(
                    _without_step_numbers(text) for text in once.elements()
                )
                for text in once - each:
                    self.fail(
                        f"{table}: pricing the group's days once recorded "
                        "something changing it one at a time did not: "
                        + _nearest(text, each)
                    )
                kinds = collections.Counter()
                for text, count in (each - once).items():
                    row = json.loads(text)
                    kinds[
                        row.get("action")
                        or row.get("event_type")
                        or ("snapshot" if "operational_breakdown" in row else "?")
                    ] += count
                surplus[table] = dict(kinds)
                continue
            columns = apart.get(table, ())
            each = collections.Counter(
                _apart_from(text, *columns) for text in each.elements()
            )
            once = collections.Counter(
                _apart_from(text, *columns) for text in once.elements()
            )
            for text in (once - each) or (each - once):
                self.fail(
                    f"{table} ends differently when a group's days are priced "
                    "once: " + _nearest(text, each if text in once else once)
                )
        return surplus

    # Each way makes its own activities, so a pick is named by its school.
    def ids_done(self, outcome):
        return sorted(pick.activity.school.school_id for pick in outcome.done)

    def said(self, outcome):
        return sorted(
            (pick.activity.school.school_id, pick.refusal) for pick in outcome.refused
        )

    def facts(self):
        """What the plan and its money come to, by school and by day."""
        from apps.daily_visit_batches.models import DailyVisitBatch
        from apps.fund_requests.models import (
            AdvanceRequest,
            FundRequest,
            WeeklyFundRequest,
        )

        visits = {}
        for activity in Activity.objects.select_related("school").order_by("id"):
            visits[activity.school.school_id] = {
                "status": activity.status,
                "day": str(activity.planned_date),
                "cost": activity.est_cost_cents,
                "lines": sorted(
                    ActivityScheduleCostLine.objects.filter(
                        activity=activity
                    ).values_list("cost_setting_key", "amount")
                ),
                "advances": sorted(
                    AdvanceRequest.objects.filter(activity=activity).values_list(
                        "amount", "status"
                    )
                ),
            }
        return {
            "visits": visits,
            "days": sorted(
                DailyVisitBatch.objects.values_list(
                    "visit_date",
                    "school_count",
                    "daily_pool_amount",
                    "per_school_amount",
                )
            ),
            "weeks": sorted(
                WeeklyFundRequest.objects.values_list(
                    "week_start_date", "total_amount", "status"
                )
            ),
            "months": sorted(
                FundRequest.objects.values_list("period_key", "total_amount", "status")
            ),
        }


class AGroupOfMovesTest(_Groups):
    def test_three_visits_leave_a_day_of_five_for_a_day_of_two(self):
        def setup():
            first = self.plan(MON, self.near[:5])["created"]
            self.plan(TUE, self.near[5:7])
            return first[:3]

        def act(ids):
            return group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        compared, (each, once), (old, new) = self.both_ways(setup, act)
        self.assertEqual(len(new.done), 3)
        self.assertEqual(self.ids_done(old), self.ids_done(new))
        surplus = self.assertTheMoneyEndsWhereItDid(compared)
        # Monday was priced with four, three and two left on it and Tuesday
        # with three, four and five: 21 pricings where 2 + 5 are the end of
        # it.
        self.assertEqual(surplus["activity_cost_snapshot"], {"snapshot": 14})
        self.assertEqual(surplus["audit_log"], {"activity.cost.calculated": 14})
        self.assertLess(once, each * 0.75, (once, each))
        for table in (
            "activity",
            "activity_schedule_cost_line",
            "advance_request",
            "daily_visit_batch",
            "weekly_fund_request_line",
        ):
            self.assertIn(table, compared.tables)

    def test_every_visit_moved_carries_the_note_of_its_move(self):
        first = self.plan(MON, self.near[:4])["created"]
        outcome = group_actions.reschedule(
            first[:3], TUE.isoformat(), REASON, self.user
        )
        self.assertEqual(len(outcome.done), 3)
        for activity_id in first[:3]:
            descriptions = list(
                ActivityScheduleCostLine.objects.filter(
                    activity_id=activity_id
                ).values_list("description", flat=True)
            )
            self.assertTrue(descriptions)
            for description in descriptions:
                self.assertIn("Rescheduled due to", description)

    def test_each_day_has_one_new_revision_not_one_for_every_visit_moved(self):
        first = self.plan(MON, self.near[:5])["created"]
        group_actions.reschedule(first[:3], TUE.isoformat(), REASON, self.user)
        for activity_id in first:
            self.assertEqual(
                list(
                    ActivityCostSnapshot.objects.filter(activity_id=activity_id)
                    .order_by("sequence")
                    .values_list("sequence", "is_current")
                ),
                [(1, False), (2, True)],
            )

    def test_days_away_keep_their_nights(self):
        def setup():
            self.plan(MON, self.far[:2])
            second = self.plan(TUE, self.far[2:5])["created"]
            return second[:2]

        def act(ids):
            return group_actions.reschedule(ids, WED.isoformat(), REASON, self.user)

        compared, _statements, (old, new) = self.both_ways(setup, act)
        self.assertEqual(self.ids_done(old), self.ids_done(new))
        self.assertTheMoneyEndsWhereItDid(compared)

    def test_a_day_past_its_target_takes_them_all(self):
        """No day is full (owner, 2026-10-16: "dont restrict the number of
        visit per day ... lift that restriction"): all five join the day
        that already held two, priced with it once."""

        def setup():
            first = self.plan(MON, self.near[:5])["created"]
            self.plan(TUE, self.near[5:7])
            return first

        def act(ids):
            return group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        compared, _statements, (old, new) = self.both_ways(setup, act)
        self.assertEqual(self.ids_done(old), self.ids_done(new))
        self.assertEqual(self.said(old), self.said(new))
        self.assertEqual(len(new.done), 5)
        self.assertFalse(new.refused)
        self.assertTheMoneyEndsWhereItDid(compared)


class AGroupOfCancellationsTest(_Groups):
    def test_the_visits_left_on_the_day_end_where_they_did(self):
        def setup():
            return self.plan(MON, self.near[:5])["created"][:2]

        def act(ids):
            return group_actions.cancel(ids, REASON, self.user)

        compared, (each, once), (old, new) = self.both_ways(setup, act)
        self.assertEqual(len(new.done), 2)
        self.assertEqual(self.ids_done(old), self.ids_done(new))
        cancelled = set(self.ids_done(new))
        one_at_a_time, together = self.ended
        self.assertEqual(one_at_a_time["days"], together["days"])
        self.assertEqual(one_at_a_time["weeks"], together["weeks"])
        self.assertEqual(one_at_a_time["months"], together["months"])
        for school, visit in together["visits"].items():
            if school in cancelled:
                self.assertEqual(visit["status"], "cancelled")
                self.assertEqual(visit["advances"], [])
                continue
            self.assertEqual(visit, one_at_a_time["visits"][school], school)
        # What differs is the cost a cancelled visit is left showing.
        # Cancelled second, it used to be re-priced first as one of four; it
        # keeps the fifth it was planned at.
        shown = sorted(together["visits"][school]["cost"] for school in cancelled)
        self.assertEqual(len(set(shown)), 1, shown)
        self.assertNotEqual(
            shown, sorted(one_at_a_time["visits"][s]["cost"] for s in cancelled)
        )
        # And fewer pricings were written on the way.
        each_rows, once_rows = compared.rows("activity_cost_snapshot")
        self.assertLess(sum(once_rows.values()), sum(each_rows.values()))
        self.assertLess(once, each, (once, each))

    def test_a_cancelled_visit_keeps_the_cost_it_was_planned_at(self):
        created = self.plan(MON, self.near[:3])["created"]
        planned = dict(
            Activity.objects.filter(id__in=created).values_list("id", "est_cost_cents")
        )
        group_actions.cancel(created[:2], REASON, self.user)
        for activity_id in created[:2]:
            activity = Activity.objects.get(id=activity_id)
            self.assertEqual(activity.status, "cancelled")
            self.assertEqual(activity.est_cost_cents, planned[activity_id])
        # The one left carries the whole day.
        self.assertGreater(
            Activity.objects.get(id=created[2]).est_cost_cents, planned[created[2]]
        )


class WhenThePricingRefusesTest(_Groups):
    def _freeze(self, activity_id):
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        AdvanceRequest.objects.filter(budget_line__activity_id=activity_id).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )

    def test_the_group_is_changed_one_at_a_time_as_it_always_was(self):
        """A visit staying on Monday has its advance with the accountant, so
        Monday may not be re-priced and nothing may leave it. Wednesday's
        visits may move. Priced at the end, Monday refuses; nothing of the
        attempt is kept, and the group is changed one activity at a time:
        Monday's are refused in the words they always were and Wednesday's
        move."""

        def setup():
            monday = self.plan(MON, self.near[:4])["created"]
            wednesday = self.plan(WED, self.near[4:7])["created"]
            self._freeze(monday[3])
            return monday[:2] + wednesday[:2]

        def act(ids):
            return group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        compared, _statements, (old, new) = self.both_ways(setup, act)
        self.assertEqual(self.ids_done(old), self.ids_done(new))
        self.assertEqual(self.said(old), self.said(new))
        self.assertEqual(len(new.done), 2)
        self.assertEqual(len(new.refused), 2)
        self.assertIn("accountant", new.refused[0].refusal)
        # Nothing of the attempt is left: the two ways are the same in every
        # table, the history included.
        for table in sorted(compared.tables):
            each, once = compared.rows(table)
            if table in HISTORY:
                each = collections.Counter(
                    _without_step_numbers(t) for t in each.elements()
                )
                once = collections.Counter(
                    _without_step_numbers(t) for t in once.elements()
                )
            for text in (once - each) or (each - once):
                self.fail(
                    f"{table} ends differently after the attempt was undone: "
                    + _nearest(text, each if text in once else once)
                )

    def test_nothing_moves_when_every_one_of_them_is_refused(self):
        monday = self.plan(MON, self.near[:4])["created"]
        self._freeze(monday[3])
        before = _everything()
        outcome = group_actions.reschedule(
            monday[:2], TUE.isoformat(), REASON, self.user
        )
        self.assertEqual(outcome.done, [])
        self.assertEqual(len(outcome.refused), 2)
        compared = _Compared(before, _everything(), started="2026-07-27")
        self.assertEqual(
            sorted(set(compared.tables) - {"audit_log", "domain_event_log"}), []
        )


class TheSwitchAndTheBlockTest(_ADayOfVisits):
    def test_off_each_activity_prices_its_days_as_it_goes(self):
        first = self.plan(MON, self.near[:4])["created"]
        with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=False):
            group_actions.reschedule(first[:2], TUE.isoformat(), REASON, self.user)
        # The visit that stayed was priced again after each of the two left.
        self.assertEqual(
            ActivityCostSnapshot.objects.filter(activity_id=first[3], is_current=True)
            .get()
            .sequence,
            3,
        )

    def test_one_activity_is_changed_as_a_single_one_is(self):
        first = self.plan(MON, self.near[:3])["created"]
        outcome = group_actions.reschedule(
            first[:1], TUE.isoformat(), REASON, self.user
        )
        self.assertEqual(len(outcome.done), 1)
        self.assertEqual(
            ActivityCostSnapshot.objects.filter(activity_id=first[1], is_current=True)
            .get()
            .sequence,
            2,
        )

    def test_a_day_a_visit_leaves_waits_only_where_the_block_says_so(self):
        first, second, third = self.plan(MON, self.near[:3])["created"]

        def revision(activity_id):
            return (
                ActivityCostSnapshot.objects.filter(
                    activity_id=activity_id, is_current=True
                )
                .get()
                .sequence
            )

        with transaction.atomic(), each_day_priced_once(leaving_too=True):
            remove_school(activity_id=first)
            remove_school(activity_id=second)
            self.assertEqual(revision(third), 1)
        self.assertEqual(revision(third), 2)

    def test_what_waits_for_the_days_runs_after_them_and_at_once_outside(self):
        order = []
        once_days_are_priced(lambda: order.append("at once"))
        self.assertEqual(order, ["at once"])
        first, second = self.plan(MON, self.near[:2])["created"]
        with transaction.atomic(), each_day_priced_once(leaving_too=True):
            remove_school(activity_id=first)
            once_days_are_priced(
                lambda: order.append(
                    ActivityCostSnapshot.objects.filter(
                        activity_id=second, is_current=True
                    )
                    .get()
                    .sequence
                )
            )
            self.assertEqual(order, ["at once"])
        self.assertEqual(order, ["at once", 2])
