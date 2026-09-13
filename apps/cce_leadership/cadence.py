"""The meeting rhythm the CCE Regional Lead's role description sets.

"Meet regularly with the Program Leads in their region", "bi-weekly with the
VP of CCE", "monthly with other Regional Leads and VP of CCE", "regularly with
their RVP", cross-region Programme Lead convenings "once per quarter", every
Country Director and their Programme Leads "quarterly", and "annually with
each CD and their Program Lead(s) ... prior to submission of next fiscal year
budget". Each is a rule here, checked against the engagements the lead
records, so the dashboard can say what is done, what is due and what has
slipped instead of leaving the rhythm to memory.

"Regularly" is read as monthly, the cadence the description uses for the
Regional Leads meeting. The annual input opens in April, when Q3 begins and
country budgets for the next year are being drafted, and is missed once that
country's next-year budget has gone to the RVP without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.core.fy import (
    get_fy_date_range,
    get_operational_fy,
    get_quarter_date_range,
    get_quarter_for_date,
)

from .models import EngagementKind

DUE_SOON_DAYS = 7
QUARTER_DUE_SOON_DAYS = 21
ANNUAL_WINDOW_OPENS_MONTH = 4


@dataclass(frozen=True)
class CadenceRule:
    kind: str
    label: str
    expectation: str
    per: str  # "region" | "lead" | "country"
    window: str = "rolling"  # "rolling" | "quarter" | "year"
    every_days: int | None = None


CADENCE_RULES: tuple[CadenceRule, ...] = (
    CadenceRule(
        EngagementKind.PL_COACHING,
        "Coaching conversation",
        "Every month with each Programme Lead",
        per="lead",
        every_days=31,
    ),
    CadenceRule(
        EngagementKind.VP_CCE_CHECKIN,
        "VP of CCE check-in",
        "Every two weeks",
        per="region",
        every_days=14,
    ),
    CadenceRule(
        EngagementKind.REGIONAL_LEADS_MEETING,
        "Regional Leads and VP of CCE meeting",
        "Every month",
        per="region",
        every_days=31,
    ),
    CadenceRule(
        EngagementKind.RVP_MEETING,
        "Meeting with the RVP",
        "Every month",
        per="region",
        every_days=31,
    ),
    CadenceRule(
        EngagementKind.CROSS_REGION_CONVENING,
        "Cross-region Programme Lead convening",
        "Every quarter",
        per="region",
        window="quarter",
    ),
    CadenceRule(
        EngagementKind.CD_QUARTERLY_REVIEW,
        "Country Director quarterly review",
        "Every quarter with each country",
        per="country",
        window="quarter",
    ),
    CadenceRule(
        EngagementKind.CD_ANNUAL_PLANNING,
        "Annual programming and budget input",
        "Once a year with each country, before its next budget is submitted",
        per="country",
        window="year",
    ),
)

STATE_LABELS = {
    "done": "Done",
    "due_soon": "Due soon",
    "overdue": "Overdue",
    "missed": "Missed",
    "open": "Not due yet",
}
STATE_TONES = {
    "done": "success",
    "due_soon": "warning",
    "overdue": "danger",
    "missed": "danger",
    "open": "neutral",
}
STATE_ORDER = {"overdue": 0, "missed": 0, "due_soon": 1, "open": 2, "done": 3}


@dataclass(frozen=True)
class Held:
    """The part of an engagement the rhythm reads."""

    kind: str
    held_on: date
    country: str
    program_lead_ids: tuple[str, ...]


def _row(rule: CadenceRule, subject: str, *, state: str, last_held, due_by, note: str):
    return {
        "kind": str(rule.kind),
        "label": rule.label,
        "expectation": rule.expectation,
        "subject": subject,
        "state": state,
        "state_label": STATE_LABELS[state],
        "tone": STATE_TONES[state],
        "last_held": last_held,
        "due_by": due_by,
        "note": note,
    }


def _rolling(rule, subject, held_dates, today):
    last = max(held_dates) if held_dates else None
    due_by = last + timedelta(days=rule.every_days) if last else today
    if last is None:
        return _row(
            rule,
            subject,
            state="due_soon",
            last_held=None,
            due_by=today,
            note="Not held yet",
        )
    if due_by < today:
        state = "overdue"
    elif (due_by - today).days <= DUE_SOON_DAYS:
        state = "due_soon"
    else:
        state = "done"
    return _row(rule, subject, state=state, last_held=last, due_by=due_by, note="")


def _quarter(rule, subject, held_dates, today):
    fy = get_operational_fy(today)
    start, end = (
        d.date() for d in get_quarter_date_range(fy, get_quarter_for_date(today))
    )
    last_day = end - timedelta(days=1)
    in_window = [d for d in held_dates if start <= d < end]
    last = max(held_dates) if held_dates else None
    if in_window:
        return _row(
            rule,
            subject,
            state="done",
            last_held=max(in_window),
            due_by=last_day,
            note="",
        )
    days_left = (last_day - today).days
    state = "due_soon" if days_left <= QUARTER_DUE_SOON_DAYS else "open"
    return _row(
        rule, subject, state=state, last_held=last, due_by=last_day, note="This quarter"
    )


def _year(rule, subject, held_dates, today, *, next_budget_submitted: bool):
    fy = get_operational_fy(today)
    start, end = (d.date() for d in get_fy_date_range(fy))
    in_window = [d for d in held_dates if start <= d < end]
    last = max(held_dates) if held_dates else None
    next_fy = str(int(fy) + 1)
    if in_window:
        return _row(
            rule,
            subject,
            state="done",
            last_held=max(in_window),
            due_by=None,
            note=f"Input given for the FY {next_fy} budget",
        )
    if next_budget_submitted:
        return _row(
            rule,
            subject,
            state="missed",
            last_held=last,
            due_by=None,
            note=f"The FY {next_fy} budget went to the RVP without it",
        )
    opens = date(int(fy), ANNUAL_WINDOW_OPENS_MONTH, 1)
    if today >= opens:
        return _row(
            rule,
            subject,
            state="due_soon",
            last_held=last,
            due_by=None,
            note=f"Before the FY {next_fy} budget is submitted",
        )
    return _row(
        rule,
        subject,
        state="open",
        last_held=last,
        due_by=opens,
        note=f"Opens {opens:%-d %b %Y}",
    )


def evaluate(
    held: list[Held],
    *,
    today: date,
    leads: list[dict],
    countries: list[str],
    budgets_submitted: set[str] = frozenset(),
) -> dict:
    """Every rhythm row for one lead, worst first, with counts by state.

    `leads` are the Programme Leads in reach ({"staff_id", "name", "country"});
    `budgets_submitted` names the countries whose next-year budget has already
    gone to the RVP.
    """
    by_kind: dict[str, list[Held]] = {}
    for engagement in held:
        by_kind.setdefault(str(engagement.kind), []).append(engagement)

    rows = []
    for rule in CADENCE_RULES:
        entries = by_kind.get(str(rule.kind), [])
        if rule.per == "region":
            dates = [e.held_on for e in entries]
            if rule.window == "rolling":
                rows.append(_rolling(rule, "Region", dates, today))
            else:
                rows.append(_quarter(rule, "Region", dates, today))
        elif rule.per == "lead":
            for lead in leads:
                dates = [
                    e.held_on for e in entries if lead["staff_id"] in e.program_lead_ids
                ]
                row = _rolling(rule, lead["name"], dates, today)
                row["lead_staff_id"] = lead["staff_id"]
                row["country"] = lead.get("country", "")
                rows.append(row)
        else:
            for country in countries:
                dates = [e.held_on for e in entries if e.country == country]
                if rule.window == "quarter":
                    row = _quarter(rule, country, dates, today)
                else:
                    row = _year(
                        rule,
                        country,
                        dates,
                        today,
                        next_budget_submitted=country in budgets_submitted,
                    )
                row["country"] = country
                rows.append(row)
    rows.sort(key=lambda r: (STATE_ORDER[r["state"]], r["label"], r["subject"]))
    counts = {
        state: sum(1 for r in rows if r["state"] == state) for state in STATE_LABELS
    }
    counts["attention"] = counts["overdue"] + counts["missed"]
    return {"rows": rows, "counts": counts}
