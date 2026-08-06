"""Single time source for scheduling/policy decisions (REG-02).

Business logic that needs "today" or "now" for scheduling-policy purposes
should read it from here rather than calling django.utils.timezone.now() or
datetime.date.today() directly, so there is exactly one place resolving
"now". Tests pin it with freezegun, which patches the underlying datetime
primitives these methods sit on — no test-only branch needed here.
"""

from __future__ import annotations

from django.utils import timezone


class ClockService:
    @staticmethod
    def now():
        """Aware current datetime."""
        return timezone.now()

    @staticmethod
    def today():
        """Current date in the project's configured timezone (Africa/Kampala),
        not UTC — a date-only value taken from timezone.now().date() would be
        wrong for the hours where UTC and EAT disagree on the calendar day."""
        return timezone.localdate()
