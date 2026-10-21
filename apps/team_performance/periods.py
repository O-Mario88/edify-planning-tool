"""The windows the report reads.

Owner, 2026-10-20: "Report can be filtered by period to avoid overcrowding
... periods include Weekly, Monthly, quarterly (Q1, Q2, Q3 and Q4) and apply
the filters only where they are needed", then "add annual to the period".
A `ReportPeriod` is one chosen week, month, quarter or the whole financial
year, read as:

* ``span`` — the period itself;
* ``to_date`` — October to the period's end (the year to date);
* ``before`` — October to the period's start: the figures as they stood at
  the end of the previous week, month or quarter, the workbook's "prior week"
  (for the year, its first day).

Edify's year runs 1 October to 30 September (`apps.core.fy`); month 1 is
October, Q1 is October to December.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.core.fy import get_month_date_range, get_operational_fy

WEEK, MONTH, QUARTER, YEAR = "week", "month", "quarter", "year"
KINDS = ((WEEK, "Weekly"), (MONTH, "Monthly"), (QUARTER, "Quarterly"), (YEAR, "Annual"))


def _int(value, low, high) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if low <= number <= high else None


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ReportPeriod:
    fy: str
    kind: str
    month: int  # month of the FY, 1 = October
    quarter: int
    week: date  # the Monday of the chosen week
    today: date

    @classmethod
    def resolve(
        cls, fy=None, month=None, *, kind=None, quarter=None, week=None, today=None
    ) -> ReportPeriod:
        from django.utils import timezone

        today = today or timezone.localdate()
        current = get_operational_fy(today)
        # A year from a link is read only when it is one: four digits.
        fy = str(fy) if _int(fy, 2000, 2999) else current
        if fy == current:
            anchor = today
        elif int(fy) < int(current):
            anchor = date(int(fy), 9, 30)
        else:
            anchor = date(int(fy) - 1, 10, 1)
        default_month = (anchor.month - 10) % 12 + 1
        month = _int(month, 1, 12) or default_month
        quarter = _int(quarter, 1, 4) or (month - 1) // 3 + 1
        monday = _day(week)
        monday = (monday or anchor) - timedelta(days=(monday or anchor).weekday())
        kind = kind if kind in dict(KINDS) else MONTH
        return cls(
            fy=fy, kind=kind, month=month, quarter=quarter, week=monday, today=today
        )

    # ── The year ────────────────────────────────────────────────────────────
    def month_window(self, month: int) -> tuple[date, date]:
        start, end = get_month_date_range(self.fy, month)
        return start.date(), end.date()

    @property
    def fy_start(self) -> date:
        return self.month_window(1)[0]

    @property
    def fy_end(self) -> date:
        return self.month_window(12)[1]

    def _clip(self, day: date) -> date:
        return min(max(day, self.fy_start), self.fy_end)

    # ── The chosen period ───────────────────────────────────────────────────
    @property
    def span(self) -> tuple[date, date]:
        if self.kind == WEEK:
            return self._clip(self.week), self._clip(self.week + timedelta(days=7))
        if self.kind == QUARTER:
            return self.month_window(self.quarter * 3 - 2)[0], self.month_window(
                self.quarter * 3
            )[1]
        if self.kind == YEAR:
            return self.fy_start, self.fy_end
        return self.month_window(self.month)

    @property
    def to_date(self) -> tuple[date, date]:
        """October to the end of the period (or today, if sooner)."""
        end = min(self.span[1], self.today + timedelta(days=1))
        return self.fy_start, max(end, self.span[0])

    @property
    def before(self) -> tuple[date, date]:
        """October to the start of the period: where the figures stood when
        the previous week, month or quarter ended."""
        return self.fy_start, self.span[0]

    @property
    def months(self) -> tuple[int, ...]:
        """The FY months a period target is the sum of; none for a week, which
        no plan phases."""
        if self.kind == QUARTER:
            return tuple(range(self.quarter * 3 - 2, self.quarter * 3 + 1))
        if self.kind == YEAR:
            return tuple(range(1, 13))
        if self.kind == MONTH:
            return (self.month,)
        return ()

    @property
    def last_month(self) -> int:
        """The FY month the period ends in, for a target to date."""
        if self.kind == QUARTER:
            return self.quarter * 3
        if self.kind == MONTH:
            return self.month
        last = self.span[1] - timedelta(days=1)
        return (last.month - 10) % 12 + 1

    @property
    def started(self) -> bool:
        return self.span[0] <= self.today

    def through(self, month: int) -> tuple[date, date]:
        """October to the end of this FY month: a quarter's cumulative figure."""
        return self.fy_start, self.month_window(month)[1]

    def quarter_started(self, quarter: int) -> bool:
        return self.month_window(quarter * 3 - 2)[0] <= self.today

    @property
    def month_span(self) -> tuple[date, date]:
        """The chosen month, for the {Month} {Year} Summary."""
        return self.month_window(self.month)

    @property
    def month_to_date(self) -> tuple[date, date]:
        end = min(self.month_window(self.month)[1], self.today + timedelta(days=1))
        return self.fy_start, max(end, self.month_window(self.month)[0])

    @property
    def month_before(self) -> tuple[date, date]:
        return self.fy_start, self.month_window(self.month)[0]

    @property
    def now(self) -> tuple[date, date]:
        """The year to today."""
        return self.fy_start, min(self.fy_end, self.today + timedelta(days=1))

    # ── Words ───────────────────────────────────────────────────────────────
    @property
    def label(self) -> str:
        start, end = self.span
        if self.kind == WEEK:
            return f"Week of {start.day} {start:%b %Y}"
        if self.kind == QUARTER:
            last = end - timedelta(days=1)
            return f"Q{self.quarter} FY{self.fy} ({start:%b}–{last:%b %Y})"
        if self.kind == YEAR:
            last = end - timedelta(days=1)
            return f"FY{self.fy} ({start:%b %Y}–{last:%b %Y})"
        return f"{start:%B %Y}"

    @property
    def previous_label(self) -> str:
        return {
            WEEK: "last week",
            MONTH: "last month",
            QUARTER: "last quarter",
            YEAR: "last year",
        }[self.kind]

    @property
    def kind_label(self) -> str:
        return {WEEK: "Week", MONTH: "Month", QUARTER: "Quarter", YEAR: "Year"}[
            self.kind
        ]

    @property
    def month_label(self) -> str:
        """ "October 2026": the {Month} {Year} of the summary tab."""
        return f"{self.month_window(self.month)[0]:%B %Y}"

    def month_options(self) -> list[tuple[int, str]]:
        return [(m, f"{self.month_window(m)[0]:%B %Y}") for m in range(1, 13)]

    def quarter_options(self) -> list[tuple[int, str]]:
        out = []
        for q in (1, 2, 3, 4):
            start = self.month_window(q * 3 - 2)[0]
            last = self.month_window(q * 3)[1] - timedelta(days=1)
            out.append((q, f"Q{q} ({start:%b}–{last:%b %Y})"))
        return out

    def week_options(self) -> list[tuple[str, str]]:
        """The year's weeks to date, latest first."""
        first = self.fy_start - timedelta(days=self.fy_start.weekday())
        last = min(self.today, self.fy_end - timedelta(days=1))
        weeks = []
        monday = first
        while monday <= last:
            weeks.append((monday.isoformat(), f"Week of {monday.day} {monday:%b %Y}"))
            monday += timedelta(days=7)
        return list(reversed(weeks))
