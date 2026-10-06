"""The day a traveller comes home carries no night away.

Owner, 2026-10-05: "a week accommodation is 4 days because the fifth day they
travel back and sleep and eat dinner from home. But transport, breakfast and
lunch remains for 5 days. If the schedule is up to Saturday, then
accommodation and dinner is for 5 days."

So on a run of days in a secondary district, each following the one before,
the last is the return day: it fetches transport, breakfast and lunch, and
neither accommodation nor dinner. Monday to Friday is four nights and four
dinners; add Saturday and Friday gets its night back, and Saturday is the day
home.

A secondary-district day with no such day before it is not a return day: a
single day away is priced as it always was, a night included, and so is the
first day of a run. A day at home (a primary-district day, or none planned)
ends a run, and so does Sunday when nothing is planned on it.

"Away" is read off the Daily Visit Batch, the one record of where a person's
day is spent: a secondary-district batch with at least one live activity.
"""

from __future__ import annotations

from datetime import timedelta

from .models import DailyVisitBatch
from .pricing import ACCOMMODATION_KEYS

ONE_DAY = timedelta(days=1)


def away_on(responsible_user, days) -> set:
    """Which of ``days`` this traveller spends in a secondary district."""
    days = list(days)
    if not responsible_user or not days:
        return set()
    return set(
        DailyVisitBatch.objects.filter(
            responsible_user=responsible_user,
            visit_date__in=days,
            district_type="secondary",
            school_count__gt=0,
        ).values_list("visit_date", flat=True)
    )


def is_return_day(responsible_user, day, *, away=None) -> bool:
    """Whether ``day``, spent in a secondary district, is the day this
    traveller comes home: away the day before, and not the day after.

    ``away`` is ``away_on`` for the two neighbouring days, when the caller
    has already read it."""
    if away is None:
        away = away_on(responsible_user, (day - ONE_DAY, day + ONE_DAY))
    return (day - ONE_DAY) in away and (day + ONE_DAY) not in away


def priced_as_return_day(batch) -> bool:
    """Whether this batch's pool was last priced without its night."""
    return batch.district_type == "secondary" and not (
        set(batch.rate_snapshot or {}) & ACCOMMODATION_KEYS
    )


__all__ = ["away_on", "is_return_day", "priced_as_return_day"]
