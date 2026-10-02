"""The day an instant falls on, in the project's timezone (apps.core.clock)."""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone

from django.test import SimpleTestCase
from django.utils import timezone

from apps.core.clock import local_clock, local_day


class LocalDayTest(SimpleTestCase):
    def test_local_midnight_read_back_in_utc_is_still_the_chosen_day(self):
        chosen = timezone.make_aware(
            datetime(2026, 10, 6), timezone.get_current_timezone()
        )
        as_stored = chosen.astimezone(dt_timezone.utc)

        self.assertEqual(as_stored.date(), date(2026, 10, 5))
        self.assertEqual(local_day(as_stored), date(2026, 10, 6))
        self.assertEqual(local_day(chosen), date(2026, 10, 6))

    def test_dates_naive_datetimes_and_nothing_pass_through(self):
        self.assertEqual(local_day(date(2026, 10, 6)), date(2026, 10, 6))
        self.assertEqual(local_day(datetime(2026, 10, 6, 23, 30)), date(2026, 10, 6))
        self.assertIsNone(local_day(None))

    def test_a_day_with_no_hour_shows_no_time(self):
        chosen = timezone.make_aware(
            datetime(2026, 10, 6), timezone.get_current_timezone()
        )
        afternoon = datetime(2026, 10, 6, 10, 0, tzinfo=dt_timezone.utc)

        self.assertEqual(local_clock(chosen.astimezone(dt_timezone.utc)), "")
        self.assertEqual(local_clock(afternoon), "1:00 PM")
        self.assertEqual(local_clock(None), "")
