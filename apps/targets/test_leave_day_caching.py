"""Caching a person's leave by person must not change which days are leave.

`_leave_days_cached` used to key its memo on (person, start, end), which reads
as the tighter key but missed on nearly every call: Team Targets asks about the
same nine people over five different windows, so forty-five distinct keys each
ran their own query. It now reads a person's approved leave once and answers
every window from it.

Working days drive target pacing, so a caching change here is a correctness
change if it gets a boundary wrong. These tests pin the boundaries rather than
the query count.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Leave, StaffProfile, User
from apps.core import request_cache
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal


class LeaveDayWindowTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="leave-cache-user",
            email="leave-cache@edify.org",
            name="Leave Cache",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            id="leave-cache-staff", user=cls.user, title="CCEO"
        )

    def _leave(self, start: date, end: date, status="approved"):
        return Leave.objects.create(
            staff_id=self.staff.id,
            type="annual",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            days=1,
            status=status,
        )

    def test_leave_inside_the_window_counts(self):
        self._leave(date(2026, 3, 10), date(2026, 3, 12))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(
            days, {date(2026, 3, 10), date(2026, 3, 11), date(2026, 3, 12)}
        )

    def test_the_window_start_is_inclusive(self):
        self._leave(date(2026, 3, 1), date(2026, 3, 1))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, {date(2026, 3, 1)})

    def test_the_window_end_is_exclusive(self):
        """`working_days` treats the range as [start, end), and so must this."""
        self._leave(date(2026, 4, 1), date(2026, 4, 1))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, set())

    def test_leave_straddling_the_window_is_clipped_to_it(self):
        self._leave(date(2026, 2, 25), date(2026, 3, 3))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, {date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)})

    def test_leave_outside_the_window_is_ignored(self):
        self._leave(date(2026, 1, 5), date(2026, 1, 9))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, set())

    def test_unapproved_leave_never_counts(self):
        self._leave(date(2026, 3, 10), date(2026, 3, 12), status="pending")
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, set())

    def test_a_malformed_date_is_skipped_not_fatal(self):
        Leave.objects.create(
            staff_id=self.staff.id,
            type="annual",
            start_date="not-a-date",
            end_date="also-not",
            days=1,
            status="approved",
        )
        self._leave(date(2026, 3, 10), date(2026, 3, 10))
        days = Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(days, {date(2026, 3, 10)})


class LeaveCacheReuseTest(TestCase):
    """One read per person, however many windows are asked about."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="leave-reuse-user",
            email="leave-reuse@edify.org",
            name="Leave Reuse",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            id="leave-reuse-staff", user=cls.user, title="CCEO"
        )
        Leave.objects.create(
            staff_id=cls.staff.id,
            type="annual",
            start_date="2026-03-10",
            end_date="2026-03-12",
            days=3,
            status="approved",
        )

    def setUp(self):
        request_cache.begin()
        self.addCleanup(request_cache.end)

    def test_twelve_monthly_windows_cost_one_query(self):
        with CaptureQueriesContext(connection) as queries:
            for month in range(1, 13):
                start = date(2026, month, 1)
                end = (start + timedelta(days=32)).replace(day=1)
                Cal._leave_days_cached(self.staff.id, start, end)

        self.assertEqual(
            len(queries.captured_queries),
            1,
            "the memo is keyed on the person, so extra windows must be free",
        )

    def test_the_answer_is_still_right_after_reuse(self):
        Cal._leave_days_cached(self.staff.id, date(2026, 1, 1), date(2026, 2, 1))
        march = Cal._leave_days_cached(
            self.staff.id, date(2026, 3, 1), date(2026, 4, 1)
        )
        self.assertEqual(
            march, {date(2026, 3, 10), date(2026, 3, 11), date(2026, 3, 12)}
        )

    def test_outside_a_request_there_is_no_cache(self):
        """Jobs and management commands must behave as if it were not there."""
        request_cache.end()
        with CaptureQueriesContext(connection) as queries:
            Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
            Cal._leave_days_cached(self.staff.id, date(2026, 3, 1), date(2026, 4, 1))
        self.assertEqual(len(queries.captured_queries), 2)
