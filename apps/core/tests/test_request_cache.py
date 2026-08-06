"""The per-request memo store must never outlive the request that opened it.

These memos exist purely to stop hot paths re-querying immutable-for-a-request
data. The danger of any cache is serving a stale answer, so what is pinned here
is the safety property, not the speed: outside a request there is no cache at
all, and each request starts empty.
"""

from __future__ import annotations

import threading
from datetime import date

from django.core.signals import request_finished, request_started
from django.test import TestCase

from apps.core import request_cache


class RequestCacheScopeTest(TestCase):
    def tearDown(self):
        request_cache.end()

    def test_there_is_no_cache_outside_a_request(self):
        """A management command or scheduled job must always see live data."""
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        self.assertEqual(request_cache.memoize("k", compute), 1)
        self.assertEqual(request_cache.memoize("k", compute), 2)
        self.assertEqual(len(calls), 2, "a value was cached with no request in flight")

    def test_within_a_request_the_value_is_computed_once(self):
        calls = []
        request_cache.begin()
        try:
            for _ in range(5):
                request_cache.memoize("k", lambda: calls.append(1))
            self.assertEqual(len(calls), 1)
        finally:
            request_cache.end()

    def test_a_new_request_does_not_see_the_previous_requests_value(self):
        request_cache.begin()
        request_cache.memoize("k", lambda: "first")
        request_cache.end()

        request_cache.begin()
        try:
            self.assertEqual(
                request_cache.memoize("k", lambda: "second"),
                "second",
                "a value leaked from one request into the next",
            )
        finally:
            request_cache.end()

    def test_the_store_is_not_shared_between_threads(self):
        """Two concurrent requests must not read each other's memo."""
        request_cache.begin()
        request_cache.memoize("k", lambda: "main-thread")
        seen = {}

        def other():
            seen["outside"] = request_cache.store()
            request_cache.begin()
            seen["value"] = request_cache.memoize("k", lambda: "other-thread")
            request_cache.end()

        t = threading.Thread(target=other)
        t.start()
        t.join()
        request_cache.end()

        self.assertIsNone(
            seen["outside"], "a worker thread inherited another request's store"
        )
        self.assertEqual(seen["value"], "other-thread")

    def test_the_request_signals_open_and_close_the_store(self):
        self.assertIsNone(request_cache.store())
        request_started.send(sender=self.__class__)
        self.assertIsNotNone(
            request_cache.store(), "request_started did not open the store"
        )
        request_finished.send(sender=self.__class__)
        self.assertIsNone(
            request_cache.store(), "request_finished did not close the store"
        )


class WorkingDayMemoFreshnessTest(TestCase):
    """The holiday memo must not hide a holiday added after it was populated."""

    def tearDown(self):
        request_cache.end()

    def test_a_new_public_holiday_is_visible_outside_a_request(self):
        from apps.accounts.models import PublicHoliday
        from apps.targets.fy_calendar import FinancialYearCalendarService as Cal

        start, end = date(2026, 10, 5), date(2026, 10, 10)  # Mon–Fri
        self.assertEqual(Cal.working_days(start, end), 5)

        PublicHoliday.objects.create(name="Test Day", date=date(2026, 10, 7))
        self.assertEqual(
            Cal.working_days(start, end),
            4,
            "a public holiday created after the first read was cached away — "
            "management commands and jobs would never see calendar changes",
        )

    def test_within_one_request_the_calendar_is_stable(self):
        from apps.targets.fy_calendar import FinancialYearCalendarService as Cal

        start, end = date(2026, 10, 5), date(2026, 10, 10)
        request_cache.begin()
        try:
            first = Cal.working_days(start, end)
            self.assertEqual(Cal.working_days(start, end), first)
        finally:
            request_cache.end()


class TargetAreaMemoFreshnessTest(TestCase):
    def tearDown(self):
        request_cache.end()

    def test_a_deactivated_target_area_is_seen_immediately_outside_a_request(self):
        from apps.targets.models import TargetArea
        from apps.targets.my_targets import active_target_areas

        before = {a.key for a in active_target_areas()}
        self.assertIn("school_visits", before)

        TargetArea.objects.filter(key="school_visits").update(active=False)
        after = {a.key for a in active_target_areas()}
        self.assertNotIn(
            "school_visits",
            after,
            "target-area configuration was cached outside a request",
        )
