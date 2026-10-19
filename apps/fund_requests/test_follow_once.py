"""The weekly request and the monthly draft follow a save once.

A reschedule between two days asked for the owner's week and month to be
re-filed three times: after the day left was re-priced, after the day joined
was, and once for the visit itself. Each re-filing deletes and writes the
week's lines and the month's items. Inside `fund_requests_follow_once` the
askers only name the owner's week and month, and each is re-filed once when
the block ends (apps.fund_requests.follow).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.fund_requests import monthly_service, weekly_service
from apps.fund_requests.follow import fund_requests_follow_once


def _visit(day: date, owner="owner-1", status="scheduled"):
    return SimpleNamespace(
        pk=f"none-{day}",
        scheduled_date=timezone.make_aware(datetime(day.year, day.month, day.day, 9)),
        responsible_staff_id=owner,
        status=status,
    )


MON = date(2026, 8, 3)
NEXT_MON = date(2026, 8, 10)


class FollowOnceTest(TestCase):
    def setUp(self):
        weekly = patch.object(weekly_service, "generate_weekly_fund_request")
        monthly = patch.object(monthly_service, "sync_monthly_periods")
        self.weekly, self.monthly = weekly.start(), monthly.start()
        self.addCleanup(weekly.stop)
        self.addCleanup(monthly.stop)

    def _ask(self, day, prior=()):
        weekly_service.trigger_generate_for_activities(
            [_visit(day)], responsible_user_id="owner-1"
        )
        weekly_service.sync_weekly_requests_for_activities([], prior_buckets=prior)
        monthly_service.sync_monthly_drafts_for_activities([], prior_buckets=prior)

    def test_outside_a_block_each_asking_is_answered_at_once(self):
        self._ask(MON)
        self._ask(MON)
        self.assertEqual(self.weekly.call_count, 2)

    def test_inside_a_block_a_week_asked_for_three_times_is_filed_once(self):
        prior = [("owner-1", "2026", 8, MON)]
        with transaction.atomic(), fund_requests_follow_once():
            self._ask(MON, prior)
            self._ask(MON + timedelta(days=2), prior)  # the same week
            self._ask(NEXT_MON, prior)
            self.weekly.assert_not_called()
            self.monthly.assert_not_called()
        self.assertEqual(
            sorted(call.args for call in self.weekly.call_args_list),
            [("owner-1", MON.isoformat()), ("owner-1", NEXT_MON.isoformat())],
        )
        self.assertEqual(self.monthly.call_count, 1)
        self.assertEqual(self.monthly.call_args.args[0], {("owner-1", "2026", 8)})

    def test_they_are_filed_inside_the_saves_own_transaction(self):
        """No savepoint of their own: a failure there must undo the save."""
        with transaction.atomic(), fund_requests_follow_once():
            self._ask(MON, [("owner-1", "2026", 8, MON)])
        self.assertEqual(self.weekly.call_args.kwargs, {"savepoint": False})
        self.assertEqual(self.monthly.call_args.kwargs, {"savepoint": False})

    def test_a_block_that_ends_in_an_error_files_nothing(self):
        class Refused(Exception):
            pass

        with self.assertRaises(Refused):
            with transaction.atomic(), fund_requests_follow_once():
                self._ask(MON, [("owner-1", "2026", 8, MON)])
                raise Refused
        self.weekly.assert_not_called()
        self.monthly.assert_not_called()

    def test_a_block_inside_a_block_leaves_the_filing_to_the_outer_one(self):
        with transaction.atomic(), fund_requests_follow_once():
            with fund_requests_follow_once():
                self._ask(MON)
            self.weekly.assert_not_called()
        self.assertEqual(self.weekly.call_count, 1)


class ItNeedsTheSavesTransactionTest(TestCase):
    def test_it_refuses_to_run_outside_one(self):
        with patch("django.db.connection.in_atomic_block", False):
            with self.assertRaises(RuntimeError):
                with fund_requests_follow_once():
                    pass
