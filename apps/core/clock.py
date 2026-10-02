"""Single time source for scheduling/policy decisions (REG-02).

Business logic that needs "today" or "now" for scheduling-policy purposes
should read it from here rather than calling django.utils.timezone.now() or
datetime.date.today() directly, so there is exactly one place resolving
"now". Tests pin it with freezegun, which patches the underlying datetime
primitives these methods sit on — no test-only branch needed here.
"""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone


def local_day(moment) -> date | None:
    """The calendar day an instant falls on in the project's timezone.

    ``Activity.scheduled_date`` is an instant. A day chosen in a drawer is
    saved as midnight Africa/Nairobi, which the database hands back as 21:00
    UTC on the day before, so ``scheduled_date.date()`` on a row read from the
    database is the previous day. Every reader that wants the day a plan is
    on asks here instead. A date passes through; a naive datetime has no zone
    to convert from and gives its own day.
    """
    if moment is None:
        return None
    if isinstance(moment, datetime):
        if timezone.is_aware(moment):
            return timezone.localtime(moment).date()
        return moment.date()
    return moment


def local_clock(moment, fmt: str = "%-I:%M %p") -> str:
    """The time of day an instant carries, or "" when it carries none.

    A plan dated in a drawer is saved at local midnight: it has a day and no
    hour, and reads as nothing rather than as "12:00 AM".
    """
    if not isinstance(moment, datetime):
        return ""
    local = timezone.localtime(moment) if timezone.is_aware(moment) else moment
    if (local.hour, local.minute) == (0, 0):
        return ""
    return local.strftime(fmt)


class ClockService:
    @staticmethod
    def now():
        """Aware current datetime."""
        return timezone.now()

    @staticmethod
    def today():
        """Current date in the project's configured timezone (Africa/Nairobi),
        not UTC — a date-only value taken from timezone.now().date() would be
        wrong for the hours where UTC and EAT disagree on the calendar day."""
        return timezone.localdate()
