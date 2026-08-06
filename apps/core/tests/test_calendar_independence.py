"""No test may depend on which day of the week the suite runs.

Scheduling is blocked on Sundays (apps/core/calendar_policy.py), so a test that
builds its date from `date.today()` — or from `today + 7`, which keeps the same
weekday — fails one run in seven with a message about weekends rather than
about whatever it was testing. Two such tests were found by running the suite
on a Sunday; on any other day they pass and the suite looks stable.

This pins the shape rather than the symptom: a test that schedules an activity
must derive its date from a helper that skips the blocked days.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)

# Calls that hand a date straight to the scheduling API.
SCHEDULES = re.compile(r'"scheduledDate"\s*:\s*([^,\n]+)')

# Derivations that keep whatever weekday it happens to be today.
WEEKDAY_PRESERVING = re.compile(
    r"date\.today\(\)|timezone\.localdate\(\)|datetime\.now\(\)"
)


class CalendarIndependenceTest(SimpleTestCase):
    def _test_files(self):
        for path in (ROOT / "apps").rglob("test_*.py"):
            yield path
        for path in (ROOT / "apps").rglob("tests.py"):
            yield path

    def test_no_scheduled_date_is_derived_from_today(self):
        offenders = []
        for path in self._test_files():
            source = path.read_text()
            for match in SCHEDULES.finditer(source):
                expression = match.group(1)
                if WEEKDAY_PRESERVING.search(expression):
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{line}: {expression.strip()[:60]}"
                    )
        self.assertEqual(
            offenders,
            [],
            "these tests schedule on whatever weekday the suite runs, so they "
            f"fail on Sundays: {offenders}",
        )
