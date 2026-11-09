"""The period an export of planned activities covers (owner, 2026-11-09).

Four ways to choose it, on Edify's financial calendar (1 October to
30 September; Q1 October–December, Q2 January–March, Q3 April–June, Q4
July–September):

    period=month    fy, month (1–12, October = 10)
    period=quarter  fy, quarter (Q1–Q4)
    period=fy       fy
    period=range    start, end (YYYY-MM-DD, both days included)

Nothing chosen is this month. A choice that cannot be read is refused with
the reason, never quietly replaced by another period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from apps.core.exceptions import BadRequest

PERIOD_TYPES = ("month", "range", "quarter", "fy")
QUARTERS = ("Q1", "Q2", "Q3", "Q4")

#: A date range longer than this is refused: a financial year is the widest
#: period the page offers.
MAX_RANGE_DAYS = 366


@dataclass(frozen=True)
class Period:
    kind: str
    fy: str
    start: date
    end: date  # included
    label: str
    month: int | None = None
    quarter: str | None = None

    def query(self) -> dict[str, str]:
        """The query parameters that choose this period again."""
        if self.kind == "range":
            return {
                "period": "range",
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
            }
        params = {"period": self.kind, "fy": self.fy}
        if self.month:
            params["month"] = str(self.month)
        if self.quarter:
            params["quarter"] = self.quarter
        return params


def _fy(raw: str | None) -> str:
    from apps.core.fy import get_operational_fy

    text = (raw or "").strip()
    if not text:
        return get_operational_fy(timezone.localdate())
    if not (text.isdigit() and len(text) == 4):
        raise BadRequest("Choose a financial year such as FY 2027.")
    return text


def _last_day(exclusive_end) -> date:
    return (exclusive_end - timedelta(days=1)).date()


def _month(fy: str, raw: str | None) -> Period:
    from apps.core.fy import month_range_to_dates

    text = (raw or "").strip()
    if not text:
        month = timezone.localdate().month
    elif text.isdigit() and 1 <= int(text) <= 12:
        month = int(text)
    else:
        raise BadRequest("Choose a month from October to September.")
    start, end = month_range_to_dates(fy, month, month)
    return Period("month", fy, start, end, f"{start:%B %Y}", month=month)


def _quarter(fy: str, raw: str | None) -> Period:
    from apps.core.fy import get_quarter_date_range, get_quarter_for_date

    quarter = (raw or "").strip().upper() or get_quarter_for_date(timezone.localdate())
    if quarter not in QUARTERS:
        raise BadRequest("Choose a quarter: Q1, Q2, Q3 or Q4.")
    start, end = get_quarter_date_range(fy, quarter)
    first, last = start.date(), _last_day(end)
    label = f"{quarter} FY {fy} ({first:%b} – {last:%b %Y})"
    return Period("quarter", fy, first, last, label, quarter=quarter)


def _whole_year(fy: str) -> Period:
    from apps.core.fy import get_fy_date_range

    start, end = get_fy_date_range(fy)
    first, last = start.date(), _last_day(end)
    label = f"FY {fy} ({first:%d %b %Y} – {last:%d %b %Y})"
    return Period("fy", fy, first, last, label)


def _range(raw_start: str | None, raw_end: str | None) -> Period:
    from apps.core.fy import get_operational_fy

    try:
        first = date.fromisoformat((raw_start or "").strip())
        last = date.fromisoformat((raw_end or "").strip())
    except ValueError as exc:
        raise BadRequest("Give a start date and an end date (YYYY-MM-DD).") from exc
    if first > last:
        raise BadRequest("The start date is after the end date.")
    if (last - first).days >= MAX_RANGE_DAYS:
        raise BadRequest("Choose a date range of one year or less.")
    label = f"{first:%d %b %Y} – {last:%d %b %Y}"
    return Period("range", get_operational_fy(first), first, last, label)


def read_period(query) -> Period:
    """The period the query chooses; BadRequest says why one cannot be read."""
    kind = (query.get("period") or "month").strip().lower()
    if kind not in PERIOD_TYPES:
        raise BadRequest("Choose a month, a date range, a quarter or a financial year.")
    if kind == "range":
        return _range(query.get("start"), query.get("end"))
    fy = _fy(query.get("fy"))
    if kind == "quarter":
        return _quarter(fy, query.get("quarter"))
    if kind == "fy":
        return _whole_year(fy)
    return _month(fy, query.get("month"))


def default_period() -> Period:
    return read_period({})
