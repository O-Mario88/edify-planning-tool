"""Planning Progress over a chosen reporting period.

The dashboard card carries a Week / Month / Quarter / FY switch. Those four
labels were `<span>` elements with no href, no handler and no target: they could
not be clicked, and the chart rendered the same five weeks whichever one looked
active. This module is the missing half — one definition of "what share of the
work planned in a period was actually completed", for all four periods.

Two rules the old weekly-only code established and this keeps:

* **Done** means ``COMPLETED_WORK_STATUSES``, not a local list. A hand-written
  ``["completed", "ia_verified", "closed"]`` once omitted ``accountant_confirmed``,
  so finished work stopped counting as finished the moment it reached the
  accountant.
* **One query per series.** The original ran two COUNTs per bucket inside a
  loop. Every period here reads ``(planned_date, status)`` once over the whole
  span and buckets in Python, so a longer period costs no extra round trips.

A bucket with nothing planned reports ``None``, not 0%. "Nothing was planned"
and "everything planned was missed" are different facts, and a chart that draws
them identically is lying about the quieter one.
"""

from __future__ import annotations

from calendar import month_abbr
from dataclasses import dataclass
from datetime import date, timedelta

from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.fy import get_operational_fy

PERIODS: tuple[str, ...] = ("week", "month", "quarter", "fy")

PERIOD_LABELS: dict[str, str] = {
    "week": "Week",
    "month": "Month",
    "quarter": "Quarter",
    "fy": "FY",
}

# How many buckets each period shows. Enough to read a trend, few enough that
# the labels stay legible in the card's width.
BUCKET_COUNT: dict[str, int] = {"week": 5, "month": 6, "quarter": 4, "fy": 3}

PERIOD_DESCRIPTION: dict[str, str] = {
    "week": "Completion rate across the five most recent planning weeks.",
    "month": "Completion rate across the six most recent months.",
    "quarter": "Completion rate across the four most recent financial quarters.",
    "fy": "Completion rate across the three most recent financial years.",
}


def normalise_period(value: str | None) -> str:
    """Fall back to the week view for anything unrecognised."""
    candidate = (value or "").strip().lower()
    return candidate if candidate in PERIODS else "week"


@dataclass(frozen=True)
class Bucket:
    label: str
    start: date
    end: date  # inclusive


def _month_start(at: date) -> date:
    return at.replace(day=1)


def _add_months(at: date, months: int) -> date:
    month_index = at.month - 1 + months
    year = at.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _quarter_of(at: date) -> tuple[str, int]:
    """(FY label, quarter number 1-4) for a date. FY Q1 is Oct-Dec."""
    fy = get_operational_fy(at)
    month = at.month
    if month >= 10:
        return fy, 1
    if month <= 3:
        return fy, 2
    if month <= 6:
        return fy, 3
    return fy, 4


def _quarter_start(fy: str, quarter: int) -> date:
    start_month = {1: 10, 2: 1, 3: 4, 4: 7}[quarter]
    year = int(fy) - 1 if quarter == 1 else int(fy)
    return date(year, start_month, 1)


def buckets_for(period: str, today: date) -> list[Bucket]:
    """The ordered buckets a period shows, oldest first."""
    period = normalise_period(period)
    count = BUCKET_COUNT[period]

    if period == "week":
        this_week = today - timedelta(days=today.weekday())
        return [
            Bucket(
                label=f"{start:%d %b}",
                start=start,
                end=start + timedelta(days=6),
            )
            for start in (
                this_week - timedelta(weeks=offset)
                for offset in range(count - 1, -1, -1)
            )
        ]

    if period == "month":
        this_month = _month_start(today)
        out = []
        for offset in range(count - 1, -1, -1):
            start = _add_months(this_month, -offset)
            end = _add_months(start, 1) - timedelta(days=1)
            out.append(
                Bucket(
                    label=f"{month_abbr[start.month]} {start:%y}", start=start, end=end
                )
            )
        return out

    if period == "quarter":
        fy, quarter = _quarter_of(today)
        out = []
        for offset in range(count - 1, -1, -1):
            q = quarter - offset
            q_fy = int(fy)
            while q <= 0:
                q += 4
                q_fy -= 1
            start = _quarter_start(str(q_fy), q)
            end = _add_months(start, 3) - timedelta(days=1)
            out.append(Bucket(label=f"{q_fy} Q{q}", start=start, end=end))
        return out

    # fy
    current = int(get_operational_fy(today))
    out = []
    for offset in range(count - 1, -1, -1):
        fy_num = current - offset
        out.append(
            Bucket(
                label=f"FY {fy_num}",
                start=date(fy_num - 1, 10, 1),
                end=date(fy_num, 9, 30),
            )
        )
    return out


def series(activities_qs, period: str, today: date | None = None) -> list[dict]:
    """Completion rate per bucket for the chosen period.

    ``activities_qs`` must be scoped to the viewer but NOT filtered to a single
    financial year: the FY view spans three of them, and an fy-filtered queryset
    would silently report two empty years next to the current one.
    """
    period = normalise_period(period)
    today = today or date.today()
    windows = buckets_for(period, today)
    if not windows:
        return []

    span_start = windows[0].start
    span_end = windows[-1].end

    rows = activities_qs.filter(
        planned_date__gte=span_start, planned_date__lte=span_end
    ).values_list("planned_date", "status")

    totals = [0] * len(windows)
    done = [0] * len(windows)
    for planned_date, status in rows:
        for index, window in enumerate(windows):
            if window.start <= planned_date <= window.end:
                totals[index] += 1
                if status in COMPLETED_WORK_STATUSES:
                    done[index] += 1
                break

    out = []
    for index, window in enumerate(windows):
        total = totals[index]
        out.append(
            {
                "label": window.label,
                # Kept for the existing template/table, which reads `week`.
                "week": window.label,
                "start": window.start,
                "end": window.end,
                "total": total,
                "done": done[index],
                # None, not 0 — see the module docstring.
                "percentage": round(done[index] * 100 / total) if total else None,
                # Explicit flag for templates: Django has no `None` literal, so
                # `{% if point.percentage is not None %}` would compare against
                # an unresolvable variable rather than against None.
                "measured": total > 0,
            }
        )
    return out


def tabs(active: str) -> list[dict]:
    """The four switch controls, with the active one marked."""
    active = normalise_period(active)
    return [
        {
            "period": period,
            "label": PERIOD_LABELS[period],
            "active": period == active,
        }
        for period in PERIODS
    ]
