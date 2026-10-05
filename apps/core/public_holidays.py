"""Uganda's public holidays, and the observances the Calendar also names.

The one answer to "is this day a public holiday?". The Calendar, the
scheduling policy (apps.core.calendar_policy), leave-day and working-day
arithmetic (apps.hr.leave_services.PublicHolidayService) and the day-off
marks on planned work (apps.activities.day_off) all read it here, so no page
can show a holiday another page does not know about.

A day is a public holiday when it is one of:

- the national calendar below: the Schedule of the Public Holidays Act, with
  Good Friday and Easter Monday worked out from Easter and the two Eids from
  the Islamic calendar;
- a day the Government declared for one year only (``_DECLARED``);
- a day someone recorded under Holidays & Blackouts: a ``PublicHoliday`` row
  or a ``CalendarBlock`` of type PUBLIC_HOLIDAY.

Dates were checked on 2026-10-05 against the Act's Schedule and the
Government's 2026 notices. The Calendar used to draw these from a fixed
(month, day) list that was a day late on every line (Independence Day on
10 October) and gave Easter and the Eids the same date every year.

Two rules that are easy to get wrong:

- An Eid is fixed by the sighting of the moon and announced a day or two
  ahead. A year in ``_ISLAMIC_CONFIRMED`` is the day that was kept; any other
  year is the expected day and says so in its name. When the day is
  announced, record it under Holidays & Blackouts with "Eid" or "Idd" in the
  title: the recorded day replaces the expected one for that year.
- The Act moves nothing to Monday. A holiday that lands on a weekend gets a
  substitute day only when the Government declares one, and a declared day is
  recorded like any other one-off.

Observances (Easter Sunday, Mother's Day, the start of Ramadan…) are shown on
the Calendar and nothing else: nobody is off, so they mark no work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from apps.core import request_cache

PUBLIC = "public"
OBSERVANCE = "observance"

#: The built-in calendar is Uganda's. Another country's staff get only the
#: days recorded for that country.
NATIONAL_COUNTRY = "Uganda"

_FIXED = (
    (1, 1, "New Year's Day"),
    (1, 26, "NRM Liberation Day"),
    (2, 16, "Archbishop Janani Luwum Day"),
    (3, 8, "International Women's Day"),
    (5, 1, "Labour Day"),
    (6, 3, "Uganda Martyrs' Day"),
    (6, 9, "National Heroes' Day"),
    (10, 9, "Independence Day"),
    (12, 25, "Christmas Day"),
    (12, 26, "Boxing Day"),
)

#: Days declared a public holiday for one year only.
_DECLARED = {
    date(2026, 1, 15): "General Election Day",
    date(2026, 1, 16): "General Election Holiday",
    date(2026, 5, 12): "Presidential Inauguration Day",
}

EID_AL_FITR = "Eid al-Fitr"
EID_AL_ADHA = "Eid al-Adha"
RAMADAN_START = "Ramadan Start"

#: (month, day) of the Islamic year each day falls on.
_ISLAMIC_DAYS = {RAMADAN_START: (9, 1), EID_AL_FITR: (10, 1), EID_AL_ADHA: (12, 10)}

#: Days that were announced and kept, by Islamic year.
_ISLAMIC_CONFIRMED = {
    (1446, RAMADAN_START): date(2025, 3, 1),
    (1446, EID_AL_FITR): date(2025, 3, 30),
    (1446, EID_AL_ADHA): date(2025, 6, 6),
    (1447, RAMADAN_START): date(2026, 2, 18),
    (1447, EID_AL_FITR): date(2026, 3, 20),
    (1447, EID_AL_ADHA): date(2026, 5, 27),
}

#: Expected days from the published calendars. The arithmetic calendar below
#: runs a day late in these years.
_ISLAMIC_EXPECTED = {
    (1448, RAMADAN_START): date(2027, 2, 8),
    (1448, EID_AL_FITR): date(2027, 3, 9),
    (1448, EID_AL_ADHA): date(2027, 5, 16),
    (1449, RAMADAN_START): date(2028, 1, 28),
    (1449, EID_AL_FITR): date(2028, 2, 26),
    (1449, EID_AL_ADHA): date(2028, 5, 5),
    (1450, RAMADAN_START): date(2029, 1, 16),
    (1450, EID_AL_FITR): date(2029, 2, 14),
    (1450, EID_AL_ADHA): date(2029, 4, 24),
    (1451, RAMADAN_START): date(2030, 1, 5),
    (1451, EID_AL_FITR): date(2030, 2, 4),
    (1451, EID_AL_ADHA): date(2030, 4, 13),
}

#: Proleptic Gregorian ordinal of 1 Muharram 1 AH (16 July 622, Julian).
_ISLAMIC_EPOCH = 227015

#: How many days a recorded Eid may sit from the expected day it replaces.
_EID_REACH = 7

#: Kampala's day for the two season marks the Calendar carries. Years outside
#: the table show neither.
_SEPTEMBER_EQUINOX = {
    2025: 22,
    2026: 23,
    2027: 23,
    2028: 22,
    2029: 22,
    2030: 23,
}
_DECEMBER_SOLSTICE = {
    2025: 21,
    2026: 21,
    2027: 22,
    2028: 21,
    2029: 21,
    2030: 21,
}


@dataclass(frozen=True)
class Holiday:
    """One named day. ``kind`` is PUBLIC (a day off) or OBSERVANCE."""

    date: date
    name: str
    kind: str = PUBLIC
    #: True while an Eid is the expected day, not yet the announced one.
    expected: bool = False
    #: True for a day recorded under Holidays & Blackouts.
    recorded: bool = False

    @property
    def is_public(self) -> bool:
        return self.kind == PUBLIC

    @property
    def label(self) -> str:
        return f"{self.name} (expected date)" if self.expected else self.name


def easter_sunday(year: int) -> date:
    """Western Easter (the anonymous Gregorian computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _islamic_day(islamic_year: int, name: str) -> tuple[date, bool]:
    """The Gregorian day, and whether it is still only the expected one."""
    key = (islamic_year, name)
    if key in _ISLAMIC_CONFIRMED:
        return _ISLAMIC_CONFIRMED[key], False
    if key in _ISLAMIC_EXPECTED:
        return _ISLAMIC_EXPECTED[key], True
    month, day = _ISLAMIC_DAYS[name]
    ordinal = (
        day
        + 29 * (month - 1)
        + (6 * month - 1) // 11
        + (islamic_year - 1) * 354
        + (3 + 11 * islamic_year) // 30
        + _ISLAMIC_EPOCH
        - 1
    )
    return date.fromordinal(ordinal), True


def _islamic_days(year: int, name: str) -> list[tuple[date, bool]]:
    """Every occurrence in one Gregorian year: the Islamic year is eleven
    days shorter, so a day can fall twice in a year, or not at all."""
    about = int((year - 622) * 33 / 32)
    found = []
    for islamic_year in range(about - 1, about + 3):
        day, expected = _islamic_day(islamic_year, name)
        if day.year == year:
            found.append((day, expected))
    return found


def national_holidays(year: int) -> list[Holiday]:
    """The built-in calendar for one year: public holidays and observances."""
    easter = easter_sunday(year)
    days = [Holiday(date(year, month, day), name) for month, day, name in _FIXED]
    days += [
        Holiday(easter - timedelta(days=2), "Good Friday"),
        Holiday(easter + timedelta(days=1), "Easter Monday"),
    ]
    for name in (EID_AL_FITR, EID_AL_ADHA):
        days += [
            Holiday(day, name, expected=expected)
            for day, expected in _islamic_days(year, name)
        ]
    days += [Holiday(day, name) for day, name in _DECLARED.items() if day.year == year]

    days += [
        Holiday(easter, "Easter Sunday", OBSERVANCE),
        Holiday(_nth_sunday(year, 5, 2), "Mother's Day", OBSERVANCE),
        Holiday(_nth_sunday(year, 6, 3), "Father's Day", OBSERVANCE),
    ]
    days += [
        Holiday(day, RAMADAN_START, OBSERVANCE, expected=expected)
        for day, expected in _islamic_days(year, RAMADAN_START)
    ]
    if year in _SEPTEMBER_EQUINOX:
        days.append(
            Holiday(
                date(year, 9, _SEPTEMBER_EQUINOX[year]),
                "September Equinox",
                OBSERVANCE,
            )
        )
    if year in _DECEMBER_SOLSTICE:
        days.append(
            Holiday(
                date(year, 12, _DECEMBER_SOLSTICE[year]),
                "December Solstice",
                OBSERVANCE,
            )
        )
    return sorted(days, key=lambda holiday: (holiday.date, holiday.name))


_LETTERS = re.compile(r"[^a-z]+")
_MEMO = "public_holidays"


def _eid_named(title: str) -> str | None:
    """Which Eid a recorded title names, however it is spelt: Eid al-Fitr,
    Idd el-Fitri, Eid ul-Adha, Idd Adhuha."""
    letters = _LETTERS.sub("", (title or "").casefold())
    if "fitr" in letters:
        return EID_AL_FITR
    if any(part in letters for part in ("adha", "adhuha", "azha")):
        return EID_AL_ADHA
    return None


def _recorded(start: date, end: date, country: str) -> list[Holiday]:
    from apps.accounts.models import CalendarBlock, PublicHoliday

    days = [
        Holiday(row_date, name, recorded=True)
        for row_date, name in PublicHoliday.objects.filter(
            date__range=(start, end)
        ).values_list("date", "name")
    ]
    blocks = CalendarBlock.objects.filter(
        block_type="PUBLIC_HOLIDAY",
        is_active=True,
        country=country,
        start_date__lte=end,
        end_date__gte=start,
    ).values_list("start_date", "end_date", "title")
    for block_start, block_end, title in blocks:
        day = max(block_start, start)
        while day <= min(block_end, end):
            days.append(Holiday(day, title, recorded=True))
            day += timedelta(days=1)
    return days


def _year_holidays(year: int, country: str) -> tuple[Holiday, ...]:
    """One calendar year, recorded days first on any day both sources name.

    Read by whole year because the Eid rule is a year's rule: the recorded
    Eid may sit a day outside the range a caller asked about.
    """

    def compute():
        recorded = _recorded(date(year, 1, 1), date(year, 12, 31), country)
        announced = [(_eid_named(holiday.name), holiday.date) for holiday in recorded]
        taken = {holiday.date for holiday in recorded}
        national = national_holidays(year) if country == NATIONAL_COUNTRY else []

        def replaced(holiday) -> bool:
            return holiday.expected and any(
                name == holiday.name and abs((day - holiday.date).days) <= _EID_REACH
                for name, day in announced
            )

        kept = [
            holiday
            for holiday in national
            if not replaced(holiday)
            and not (holiday.is_public and holiday.date in taken)
        ]
        return tuple(
            sorted(
                recorded + kept,
                key=lambda holiday: (holiday.date, not holiday.recorded, holiday.name),
            )
        )

    return request_cache.memoize((_MEMO, year, country), compute)


def forget() -> None:
    """Drop this request's memo after a holiday is recorded or removed."""
    bucket = request_cache.store()
    if bucket:
        for key in [k for k in bucket if isinstance(k, tuple) and k[:1] == (_MEMO,)]:
            del bucket[key]


def holidays_between(
    start: date, end: date, *, country: str = NATIONAL_COUNTRY
) -> list[Holiday]:
    """Every named day in [start, end]: public holidays and observances."""
    if start > end:
        return []
    return [
        holiday
        for year in range(start.year, end.year + 1)
        for holiday in _year_holidays(year, country)
        if start <= holiday.date <= end
    ]


def public_holidays_between(
    start: date, end: date, *, country: str = NATIONAL_COUNTRY
) -> dict[date, str]:
    """The public holidays in [start, end], as day -> name."""
    names: dict[date, str] = {}
    for holiday in holidays_between(start, end, country=country):
        if holiday.is_public:
            names.setdefault(holiday.date, holiday.label)
    return names


def public_holiday_name(day: date, *, country: str = NATIONAL_COUNTRY) -> str | None:
    """The public holiday ``day`` is, or None."""
    return public_holidays_between(day, day, country=country).get(day)


def upcoming_public_holidays(
    today: date, *, limit: int = 5, country: str = NATIONAL_COUNTRY
) -> list[Holiday]:
    """The next public holidays from ``today``, soonest first, one per day."""
    seen: set[date] = set()
    upcoming = []
    for holiday in holidays_between(
        today, today + timedelta(days=366), country=country
    ):
        if holiday.is_public and holiday.date not in seen:
            seen.add(holiday.date)
            upcoming.append(holiday)
    return upcoming[:limit]
