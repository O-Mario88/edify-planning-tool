"""The day an instant falls on, in the project's timezone (apps.core.clock)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.core.clock import ClockService, local_clock, local_day


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


class TodayIsTheLocalDayTest(SimpleTestCase):
    """ "Today" is the calendar day in Kampala, never the day in UTC.

    ``timezone.now()`` is an instant in UTC, so ``timezone.now().date()`` is
    the UTC day: from midnight until 03:00 East Africa Time it is still
    yesterday. Thirty-two places read the day, the month or the year that way
    (2026-10-09). On the officer's dashboard yesterday's unstarted work stayed
    "Planned" for three more hours; the To-Do queue, the daily debrief, the
    fund dashboards and the HR due dates had the same three hours, and the
    month and year defaults the same on the first night of each.
    """

    #: ``timezone.now().date()``, ``.year`` or ``.month``, under any of the
    #: names the module is imported as.
    UTC_DAY = re.compile(r"\bnow\(\)\.(date\(\)|year\b|month\b)")

    def test_the_clock_gives_the_local_day_in_the_small_hours(self):
        # 00:30 on 9 October in Kampala.
        with freeze_time("2026-10-08 21:30:00"):
            self.assertEqual(timezone.now().date(), date(2026, 10, 8))
            self.assertEqual(ClockService.today(), date(2026, 10, 9))
            self.assertEqual(timezone.localdate(), date(2026, 10, 9))

    def test_no_application_code_reads_the_day_in_utc(self):
        apps = Path(settings.BASE_DIR) / "apps"
        offenders = []
        for path in sorted(apps.rglob("*.py")):
            relative = path.relative_to(settings.BASE_DIR).as_posix()
            if (
                "/migrations/" in relative
                or "/tests/" in relative
                or path.name.startswith("test")
                # The module that states the rule quotes what it replaces.
                or relative == "apps/core/clock.py"
            ):
                continue
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if self.UTC_DAY.search(line):
                    offenders.append(f"{relative}:{number}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "These read the day, month or year from timezone.now(), which is "
            "UTC. Use timezone.localdate() (apps.core.clock): for three hours "
            "after midnight in Kampala the UTC day is still yesterday.",
        )
