"""
Operational Fiscal Year utilities — faithful port of fy.util.ts.

FY runs October 1 → September 30. The FY label is the calendar year in which
the FY ENDS (so Oct 2025 → "2026"). Quarters: Q1 Oct–Dec, Q2 Jan–Mar,
Q3 Apr–Jun, Q4 Jul–Sep.

All date math is UTC to match the legacy getUTC* usage. The pinned spec tests
(see fy.util.spec.ts) must keep passing — especially the FY rollover at
Sep 30 → Oct 1 and the seeded May–June window being Q3.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal


Quarter = Literal["Q1", "Q2", "Q3", "Q4"]
CumulativePeriod = Literal["Q1", "Q2", "MidYear", "Q3", "Q4", "FY"]

_QUARTER_START_MONTH = {"Q1": 10, "Q2": 1, "Q3": 4, "Q4": 7}


def get_operational_fy(at: date | datetime | None = None) -> str:
    """The operational FY label for a date (FY starts Oct 1)."""
    at = _as_utc(at)
    y = at.year
    m = at.month  # 1=Jan
    return str(y + 1 if m >= 10 else y)  # Oct(10)–Dec → next year's FY


def get_fy_date_range(fy: str) -> tuple[datetime, datetime]:
    """Calendar date range [start, end) for an FY label."""
    fy_num = int(fy)
    # FY "2026" = Oct 1 2025 00:00 UTC → Oct 1 2026 00:00 UTC.
    start = datetime(fy_num - 1, 10, 1, tzinfo=timezone.utc)
    end = datetime(fy_num, 10, 1, tzinfo=timezone.utc)
    return start, end


def get_quarter_for_date(at: date | datetime | None = None) -> Quarter:
    """The quarter a date falls in within the operational FY."""
    at = _as_utc(at)
    m = at.month
    if m >= 10:
        return "Q1"  # Oct–Dec
    if m <= 3:
        return "Q2"  # Jan–Mar
    if m <= 6:
        return "Q3"  # Apr–Jun
    return "Q4"  # Jul–Sep


def get_quarter_date_range(fy: str, quarter: Quarter) -> tuple[datetime, datetime]:
    """[start, end) range for a quarter within an FY."""
    fy_num = int(fy)
    start_month = _QUARTER_START_MONTH[quarter]
    # Q1 sits in the prior calendar year; Q2–Q4 in the FY year.
    start_year = fy_num - 1 if quarter == "Q1" else fy_num
    start = datetime(start_year, start_month, 1, tzinfo=timezone.utc)
    # +3 months
    end_month = start_month + 3
    end_year = start_year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def get_mid_year_range(fy: str) -> tuple[datetime, datetime]:
    """Mid-Year = Q1 + Q2 (Oct → Mar)."""
    q1_start, _ = get_quarter_date_range(fy, "Q1")
    _, q2_end = get_quarter_date_range(fy, "Q2")
    return q1_start, q2_end


def get_month_date_range(fy: str, month_of_fy: int) -> tuple[datetime, datetime]:
    """Calendar month range for a 1-based month-of-FY (1 = October)."""
    fy_start, _ = get_fy_date_range(fy)
    # month_of_fy=1 → October of (fy-1). Offset months from fy_start.
    start_year = fy_start.year
    start_month = fy_start.month + (month_of_fy - 1)
    while start_month > 12:
        start_month -= 12
        start_year += 1
    start = datetime(start_year, start_month, 1, tzinfo=timezone.utc)
    end_month = start_month + 1
    end_year = start_year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)
    return start, end


def get_cumulative_target_percentage(period: CumulativePeriod) -> int:
    """Cumulative target percentage expected by the end of a period."""
    if period == "Q1":
        return 25
    if period in ("Q2", "MidYear"):
        return 50
    if period == "Q3":
        return 75
    return 100  # Q4, FY


def fy_options(now: date | datetime | None = None) -> list[str]:
    """FY dropdown options from FY 2025 upward through the current FY (+1 ahead)."""
    current = int(get_operational_fy(now))
    return [str(y) for y in range(2025, current + 2)]


def _as_utc(at: date | datetime | None) -> datetime:
    if at is None:
        return datetime.now(timezone.utc)
    if isinstance(at, datetime):
        if at.tzinfo is None:
            return at.replace(tzinfo=timezone.utc)
        return at.astimezone(timezone.utc)
    return datetime(at.year, at.month, at.day, tzinfo=timezone.utc)


__all__ = [
    "Quarter",
    "CumulativePeriod",
    "get_operational_fy",
    "get_fy_date_range",
    "get_quarter_for_date",
    "get_quarter_date_range",
    "get_mid_year_range",
    "get_month_date_range",
    "get_cumulative_target_percentage",
    "fy_options",
]
