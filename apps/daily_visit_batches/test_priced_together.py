"""A day's visits are priced in one pass, and end exactly where they did.

Owner, 2026-10-12: "it takes about 5 seconds to save", and then "it should
take a 1 second max". A day's pool is shared, so a visit joining or leaving a
day re-prices every visit on it; each member used to read and lock its own
advances and requests, clear and write its own lines, write its own snapshot
and open its own advances, about fifty statements a member. In production a
reschedule between two five-visit days ran 693 to 809 statements.

Two things are held here.

Nothing a save writes has moved. Each plan below is carried out twice on the
same records, once with the day's members written one after another, as they
always were, and once written together, and the whole database is compared
between the two: every table of every app, the history included. Unlike a day
priced once (`test_day_priced_once`), nothing is left out of the record: each
member still has one new cost snapshot and one "cost calculated" entry for
every pricing.

And it takes fewer statements, by a margin that would be lost if a member
went back to asking for what the day already has.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.activities.models import Activity
from apps.activities.services import cancel, reschedule
from apps.budget import costing_service
from apps.budget.models import ActivityCostSnapshot
from apps.core.exceptions import BadRequest

from .services import remove_school
from .test_day_priced_once import (
    MON,
    THU,
    TUE,
    WED,
    _ADayOfVisits,
    _Compared,
    _everything,
    _nearest,
)

_together = costing_service.apply_to_activities


def _one_after_another(items, responsible_user_id=None, **_kwargs):
    """The day's members written as they were before: each on its own, with
    its own reads, locks, lines, snapshot and advances."""
    return [
        _together([item], responsible_user_id=responsible_user_id)[0] for item in items
    ]


def _at_nine(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time())).replace(
        hour=9
    )


class _BothWays(_ADayOfVisits):
    def both_ways(self, steps):
        """Carry `steps` out with each day's members written one after
        another, undo them, carry them out written together, and return
        (comparison, statements each way)."""
        states, statements = [], []
        for together in (False, True):
            with transaction.atomic():
                with mock.patch.object(
                    costing_service,
                    "apply_to_activities",
                    _together if together else _one_after_another,
                ):
                    with CaptureQueriesContext(connection) as queries:
                        steps()
                statements.append(len(queries))
                states.append(_everything())
                transaction.set_rollback(True)
        return _Compared(*states, started="2026-07-27"), statements

    def assertNothingMoved(self, compared):
        for table in sorted(compared.tables):
            one_by_one, together = compared.rows(table)
            for text in (together - one_by_one) or (one_by_one - together):
                self.fail(
                    f"{table} ends differently when a day's visits are written "
                    "together: "
                    + _nearest(text, one_by_one if text in together else together)
                )

    def move(self, activity_id, day):
        return reschedule(
            activity_id,
            {"scheduledDate": _at_nine(day).isoformat(), "reason": "Asked to move"},
            self.user,
        )


class NothingMovedTest(_BothWays):
    def test_a_day_of_five_then_one_leaves(self):
        def steps():
            created = self.plan(MON, self.near[:5])["created"]
            remove_school(activity_id=created[2])

        compared, (one_by_one, together) = self.both_ways(steps)
        self.assertNothingMoved(compared)
        for table in (
            "activity",
            "activity_cost_snapshot",
            "activity_schedule_cost_line",
            "advance_request",
            "audit_log",
            "daily_visit_batch",
            "weekly_fund_request_line",
        ):
            self.assertIn(table, compared.tables)
        self.assertLess(together, one_by_one)

    def test_a_visit_moves_between_two_full_days(self):
        """The case the owner timed: one visit from a day of five to a day of
        four re-prices nine visits."""

        def steps():
            first = self.plan(MON, self.near[:5])["created"]
            self.plan(TUE, self.near[5:9])
            self.move(first[0], TUE)

        compared, (one_by_one, together) = self.both_ways(steps)
        self.assertNothingMoved(compared)
        self.assertLess(together, one_by_one)

    def test_days_away_with_their_nights(self):
        """A day in a secondary district shares transport, meals and the
        night, and its neighbours are re-priced when it changes which of
        them is the day home."""

        def steps():
            self.plan(MON, self.far[:2] + self.near[:1])
            self.plan(TUE, self.far[2:4])
            created = self.plan(WED, self.far[4:6])["created"]
            self.move(created[0], THU)

        compared, _ = self.both_ways(steps)
        self.assertNothingMoved(compared)

    def test_a_visit_is_cancelled_off_a_day_of_four(self):
        def steps():
            created = self.plan(MON, self.near[:4])["created"]
            cancel(created[1], {"reason": "School closed for the day"}, self.user)

        compared, _ = self.both_ways(steps)
        self.assertNothingMoved(compared)


class ItTakesFewerStatementsTest(_ADayOfVisits):
    def _leaving_a_day_of_five(self, way):
        with transaction.atomic():
            created = self.plan(MON, self.near[:5])["created"]
            with mock.patch.object(costing_service, "apply_to_activities", way):
                with CaptureQueriesContext(connection) as queries:
                    remove_school(activity_id=created[0])
            transaction.set_rollback(True)
        return len(queries)

    def test_four_visits_re_priced_together_ask_for_far_less(self):
        one_by_one = self._leaving_a_day_of_five(_one_after_another)
        together = self._leaving_a_day_of_five(_together)
        # Four members: what each used to read, lock, clear and write for
        # itself is read, locked, cleared and written once for the day.
        self.assertLess(together, one_by_one * 0.7, (together, one_by_one))


class EachPricingIsStillRecordedTest(_ADayOfVisits):
    def test_every_member_has_a_revision_for_every_pricing(self):
        """A visit leaving a day of three re-prices the two left: each of
        them has a second cost snapshot, the first stepped down."""
        created = self.plan(MON, self.near[:3])["created"]
        remove_school(activity_id=created[0])
        for activity_id in created[1:]:
            self.assertEqual(
                list(
                    ActivityCostSnapshot.objects.filter(activity_id=activity_id)
                    .order_by("sequence")
                    .values_list("sequence", "is_current")
                ),
                [(1, False), (2, True)],
            )


class TheDayIsRefusedAsItWasTest(_BothWays):
    def test_the_same_member_refuses_in_the_same_words(self):
        """A member whose advance is with the accountant may not be
        re-priced. Asked of all members before anything is written, the
        refusal is the one the first such member gave when it was priced on
        its own, and nothing of the day is left written."""
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        created = self.plan(MON, self.near[:4])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=created[2]).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )
        AdvanceRequest.objects.filter(budget_line__activity_id=created[3]).update(
            status=AdvanceRequestStatus.DISBURSED
        )
        messages = []
        for together in (False, True):
            snapshots = ActivityCostSnapshot.objects.count()
            with mock.patch.object(
                costing_service,
                "apply_to_activities",
                _together if together else _one_after_another,
            ):
                with self.assertRaises(BadRequest) as refused:
                    remove_school(activity_id=created[0])
            messages.append(str(refused.exception.detail))
            self.assertEqual(ActivityCostSnapshot.objects.count(), snapshots)
            self.assertTrue(
                Activity.objects.filter(
                    id=created[0], daily_visit_batch__isnull=False
                ).exists()
            )
        self.assertEqual(messages[0], messages[1])
        self.assertIn("accountant", messages[0])


class AFullDayRefusesBeforeAnythingIsPricedTest(_ADayOfVisits):
    def test_no_visit_is_re_priced_for_a_move_that_is_refused(self):
        """Moving onto a full day used to re-price every visit left on the
        day it would have left, and then undo it."""
        first = self.plan(MON, self.near[:5])["created"]
        self.plan(TUE, self.near[5:10])
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(BadRequest) as refused:
                reschedule(
                    first[0],
                    {
                        "scheduledDate": _at_nine(TUE).isoformat(),
                        "reason": "Asked to move",
                    },
                    self.user,
                )
        self.assertIn("You can only schedule", str(refused.exception.detail))
        written = [
            q["sql"]
            for q in queries.captured_queries
            if q["sql"].startswith(("INSERT", "DELETE"))
            and any(
                table in q["sql"]
                for table in (
                    '"activity_cost_snapshot"',
                    '"activity_schedule_cost_line"',
                    '"advance_request"',
                )
            )
        ]
        self.assertEqual(written, [])
        self.assertEqual(
            Activity.objects.get(id=first[0]).planned_date,
            MON,
        )

    def test_a_visit_moved_within_its_own_day_is_not_counted_twice(self):
        """The day is found again once the visit has left it: a full day
        does not refuse the move of one of its own visits to another hour."""
        first = self.plan(MON, self.near[:5])["created"]
        reschedule(
            first[0],
            {
                "scheduledDate": (_at_nine(MON) + timedelta(hours=2)).isoformat(),
                "reason": "Later in the day",
            },
            self.user,
        )
        self.assertEqual(
            Activity.objects.filter(daily_visit_batch__visit_date=MON).count(), 5
        )


class ACostOnlySaveAsksNothingOfTheCoreSlotTest(_ADayOfVisits):
    def test_re_pricing_reads_no_core_slot(self):
        created = self.plan(MON, self.near[:3])["created"]
        with CaptureQueriesContext(connection) as queries:
            remove_school(activity_id=created[0])
        slot_reads = [
            q["sql"]
            for q in queries.captured_queries
            if 'FROM "core_activity_slot"' in q["sql"]
        ]
        # The visit that left its day is saved with its day, which is not a
        # cost-only save; the two re-priced are.
        self.assertLessEqual(len(slot_reads), 2, slot_reads)

    def test_a_save_that_touches_more_than_cost_still_mirrors(self):
        activity = Activity.objects.get(id=self.plan(MON, self.near[:1])["created"][0])
        with CaptureQueriesContext(connection) as queries:
            activity.save(update_fields=["est_cost_cents", "updated_at"])
        self.assertFalse(
            [q for q in queries.captured_queries if "core_activity_slot" in q["sql"]]
        )
        with CaptureQueriesContext(connection) as queries:
            activity.save(update_fields=["est_cost_cents", "status", "updated_at"])
        self.assertTrue(
            [q for q in queries.captured_queries if "core_activity_slot" in q["sql"]]
        )
