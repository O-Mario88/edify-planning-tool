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
    def working_days(start: date, end: date, user=None) -> int:
        """Weekdays in [start, end) minus public holidays minus the user's own
        approved leave days."""
        from apps.accounts.models import Leave
        from apps.hr.leave_services import PublicHolidayService

        # Union both holiday sources (PublicHoliday rows + CalendarBlock
        # PUBLIC_HOLIDAY rows) — querying PublicHoliday alone silently missed
        # holidays added only via the /public-holidays admin surface.
        holidays = set(
            PublicHolidayService.get_holidays_in_range(start, end - timedelta(days=1))
        )
        leave_days: set[date] = set()
        if user is not None:
            sp_id = getattr(user, "staff_profile_id", None)
            leaves = Leave.objects.filter(
                status="approved",
                staff_id__in=[i for i in [sp_id] if i],
                start_date__lt=end.isoformat(),
                end_date__gte=start.isoformat(),
            )
            for lv in leaves:
                try:
                    d0 = date.fromisoformat(lv.start_date)
                    d1 = date.fromisoformat(lv.end_date)
                except (TypeError, ValueError):
                    continue
                d = max(d0, start)
                while d <= min(d1, end - timedelta(days=1)):
                    leave_days.add(d)
                    d += timedelta(days=1)

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
