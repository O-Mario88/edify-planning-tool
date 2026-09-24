"""FinancialYearCalendarService — the single place period math comes from.

Wraps the configured FY calendar (apps.core.fy: FY starts October 1) and adds
working-day pacing: weekdays minus public holidays minus the user's own
approved leave. If the FY configuration changes, every consumer follows.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.core.clock import ClockService
from apps.core.fy import (
    get_fy_date_range,
    get_month_date_range,
    get_operational_fy,
    get_quarter_date_range,
)

QUARTERS = ("Q1", "Q2", "Q3", "Q4")
MONTH_LABELS = [
    "Oct",
    "Nov",
    "Dec",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
]


class FinancialYearCalendarService:
    @staticmethod
    def quarter_of_month(month_of_fy: int) -> str:
        return QUARTERS[(month_of_fy - 1) // 3]

    @staticmethod
    def months_of_quarter(quarter: str) -> list[int]:
        i = QUARTERS.index(quarter)
        return [i * 3 + 1, i * 3 + 2, i * 3 + 3]

    @staticmethod
    def month_of_fy_for(d: date, fy: str) -> int | None:
        """1..12 when the date falls inside the FY, else None."""
        start, end = get_fy_date_range(fy)
        if not (start.date() <= d < end.date()):
            return None
        return (d.year - start.date().year) * 12 + d.month - start.date().month + 1

    @staticmethod
    def month_label(fy: str, month_of_fy: int) -> str:
        start, _ = get_month_date_range(fy, month_of_fy)
        return start.strftime("%B %Y")

    @staticmethod
    def current(at: date | None = None) -> dict:
        """Resolve today's FY, month-of-FY and quarter dynamically."""
        today = at or ClockService.today()
        fy = get_operational_fy(today)
        month_of_fy = FinancialYearCalendarService.month_of_fy_for(today, fy) or 1
        return {
            "today": today,
            "fy": fy,
            "month_of_fy": month_of_fy,
            "quarter": FinancialYearCalendarService.quarter_of_month(month_of_fy),
            "month_label": FinancialYearCalendarService.month_label(fy, month_of_fy),
        }

    @staticmethod
    def quarter_label(fy: str, quarter: str) -> str:
        start, end = get_quarter_date_range(fy, quarter)
        last = end - timedelta(days=1)
        return f"{start.strftime('%b')} – {last.strftime('%b')}"

    # ── Working-day pacing ───────────────────────────────────────────────────
    @staticmethod
    def _holidays_cached(start: date, end: date) -> frozenset:
        """working_days() is called per team member, per period, per target
        area, and every call re-queried PublicHoliday and CalendarBlock for the
        SAME dates — 372 of the 471 queries on Team Targets. Holidays cannot
        change within one request, so the answer is memoized for its duration
        (and not at all outside a request; see apps.core.request_cache)."""
        from apps.core.fy import get_fy_date_range, get_operational_fy
        from apps.core.request_cache import memoize
        from apps.hr.leave_services import PublicHolidayService

        fy = get_operational_fy(start)
        fy_start, fy_end = (d.date() for d in get_fy_date_range(fy))
        if not (fy_start <= start and end < fy_end):
            return memoize(
                ("holidays", start, end),
                lambda: frozenset(
                    PublicHolidayService.get_holidays_in_range(start, end)
                ),
            )
        # A page asks for a month, four quarters and the year, and each window
        # read both holiday tables again. Holidays are whole days, so the
        # year's set read once answers every window inside it.
        year = memoize(
            ("holidays_fy", fy),
            lambda: frozenset(
                PublicHolidayService.get_holidays_in_range(
                    fy_start, fy_end - timedelta(days=1)
                )
            ),
        )
        return frozenset(day for day in year if start <= day <= end)

    @staticmethod
    def _all_leave_days(sp_id: str) -> frozenset:
        """Every approved leave day for one staff member, memoised per request.

        Keyed on the person alone, deliberately. The previous cache keyed on
        (person, start, end), which sounds tighter but missed on almost every
        call: Team Targets asks about the same nine people over five different
        windows, so forty-five distinct keys each ran their own query. A
        person's approved leave cannot change mid-request, so it is read once
        and every window is answered from it.

        Approved leave runs to a handful of rows per person, so expanding all
        of it costs less than the query that would otherwise narrow it.
        """
        from apps.accounts.models import Leave
        from apps.core.request_cache import memoize

        def _compute() -> frozenset:
            return FinancialYearCalendarService._leave_day_set(
                Leave.objects.filter(status="approved", staff_id=sp_id).values_list(
                    "start_date", "end_date"
                )
            )

        return memoize(("leave_all", sp_id), _compute)

    @staticmethod
    def prime_leave_days(sp_ids) -> None:
        """Read a roster's approved leave in one query into the request memo
        `_all_leave_days` answers from, rather than one query per person.
        Outside a request there is no memo, and this does nothing."""
        from apps.accounts.models import Leave
        from apps.core.request_cache import store

        bucket = store()
        if bucket is None:
            return
        spans = {sp: [] for sp in sp_ids if sp and ("leave_all", sp) not in bucket}
        if not spans:
            return
        for staff_id, start, end in Leave.objects.filter(
            status="approved", staff_id__in=list(spans)
        ).values_list("staff_id", "start_date", "end_date"):
            spans[staff_id].append((start, end))
        for sp_id, person_spans in spans.items():
            bucket[("leave_all", sp_id)] = FinancialYearCalendarService._leave_day_set(
                person_spans
            )

    @staticmethod
    def _leave_day_set(spans) -> frozenset:
        """Every day of each (start_date, end_date) ISO string pair; a span
        that does not parse is skipped."""
        from datetime import date as _d

        days: set = set()
        for start_date, end_date in spans:
            try:
                d0 = _d.fromisoformat(start_date)
                d1 = _d.fromisoformat(end_date)
            except (TypeError, ValueError):
                continue
            day = d0
            while day <= d1:
                days.add(day)
                day += timedelta(days=1)
        return frozenset(days)

    @staticmethod
    def _leave_days_cached(sp_id: str, start: date, end: date) -> frozenset:
        """A staff member's approved leave days within ``[start, end)``."""
        return frozenset(
            day
            for day in FinancialYearCalendarService._all_leave_days(sp_id)
            if start <= day < end
        )

    @staticmethod
    def working_days(start: date, end: date, user=None) -> int:
        """Weekdays in [start, end) minus public holidays minus the user's own
        approved leave days."""

        # Union both holiday sources (PublicHoliday rows + CalendarBlock
        # PUBLIC_HOLIDAY rows) — querying PublicHoliday alone silently missed
        # holidays added only via the /public-holidays admin surface.
        holidays = FinancialYearCalendarService._holidays_cached(
            start, end - timedelta(days=1)
        )
        leave_days: frozenset = frozenset()
        if user is not None:
            sp_id = getattr(user, "staff_profile_id", None)
            if sp_id:
                leave_days = FinancialYearCalendarService._leave_days_cached(
                    sp_id, start, end
                )

        n = 0
        d = start
        while d < end:
            if d.weekday() < 5 and d not in holidays and d not in leave_days:
                n += 1
            d += timedelta(days=1)
        return n

    @staticmethod
    def expected_pace_pct(
        start: date, end: date, at: date | None = None, user=None
    ) -> int:
        """Expected achievement %% for a period at `at`: working days elapsed /
        working days total. 0 before the period, 100 after it."""
        today = at or ClockService.today()
        if today < start:
            return 0
        if today >= end:
            return 100
        total = FinancialYearCalendarService.working_days(start, end, user)
        if not total:
            return 100
        elapsed = FinancialYearCalendarService.working_days(
            start, today + timedelta(days=1), user
        )
        return min(100, round(elapsed / total * 100))

    @staticmethod
    def month_range(fy: str, month_of_fy: int) -> tuple[date, date]:
        s, e = get_month_date_range(fy, month_of_fy)
        return s.date(), e.date()

    @staticmethod
    def quarter_range(fy: str, quarter: str) -> tuple[date, date]:
        s, e = get_quarter_date_range(fy, quarter)
        return s.date(), e.date()

    @staticmethod
    def fy_range(fy: str) -> tuple[date, date]:
        s, e = get_fy_date_range(fy)
        return s.date(), e.date()
