"""Role briefs: one short message that answers a role's morning question.

A brief is composed here and nowhere else, from the figures the pages already
show: the Planning Monitor's totals, the To-Do queue's counts, the Regional
Lead roster and My Plan. It never computes a figure of its own, so a brief and
the page it links to cannot disagree.

Three rules shape every line:

* **Counts and links only.** A brief is read on a phone, often with someone
  else looking at it. It never carries a school's name, a person's name, a sum
  of money or any personal detail.
* **Each line opens its table.** A line names the page that holds the rows
  behind its figure, and only a page the reader may open.
* **Nothing to say, nothing sent.** A brief with no lines is not built; the
  platform does not message someone to tell them there is no news.

The four briefs:

==================  ================  =====================================
Kind                Reader            Asked
==================  ================  =====================================
``country_morning`` Country Director  Is the country on plan, and what
                                      needs my decision today?
``team_monday``     Programme Lead    Who on my team is behind, and what
                                      is waiting on me?
``regional_monday`` Regional          How are my Programme Leads doing?
                    Programme Lead
``field_evening``   CCEO              Where am I going next, and has my
                                      money come?
==================  ================  =====================================
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.core.rbac import EdifyRole

COUNTRY_MORNING = "country_morning"
TEAM_MONDAY = "team_monday"
REGIONAL_MONDAY = "regional_monday"
FIELD_EVENING = "field_evening"

#: The role each brief is written for. A person who holds two of these roles
#: is briefed for each, by the role and not by the hat they are wearing.
BRIEF_ROLES: dict[str, str] = {
    COUNTRY_MORNING: EdifyRole.COUNTRY_DIRECTOR.value,
    TEAM_MONDAY: EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    REGIONAL_MONDAY: EdifyRole.REGIONAL_PROGRAM_LEAD.value,
    FIELD_EVENING: EdifyRole.CCEO.value,
}

BRIEF_NAMES: dict[str, str] = {
    COUNTRY_MORNING: "Morning Country Brief",
    TEAM_MONDAY: "Monday Team Brief",
    REGIONAL_MONDAY: "Weekly Regional Digest",
    FIELD_EVENING: "Evening Message",
}

#: An officer who has planned under this share of their visit target is
#: "behind" in a brief. The Planning Monitor colours the same line.
BEHIND_BELOW_PCT = 50

#: How many exceptions the Country Director's brief names.
MAX_EXCEPTIONS = 3

#: The weekly fund request's state, in the words an officer would use.
FUND_STATES: dict[str, str] = {
    "pending_responsible_confirmation": "not requested yet",
    "submitted_to_pl": "waiting for your Programme Lead",
    "submitted_to_cd": "waiting for the Country Director",
    "confirmed_for_advance": "approved, not paid yet",
    "disbursed": "paid",
    "accounted": "accounted",
    "returned_by_pl": "returned to you",
    "returned_by_cd": "returned to you",
    "returned_by_accountant": "returned to you",
    "self_fund": "self-funded",
    "self_funded": "self-funded",
    "not_requested": "not requested",
}


@dataclass(frozen=True)
class BriefLine:
    label: str
    text: str
    url: str = ""


@dataclass(frozen=True)
class Brief:
    kind: str
    day: date
    lines: tuple[BriefLine, ...]

    @property
    def name(self) -> str:
        return BRIEF_NAMES[self.kind]

    @property
    def title(self) -> str:
        return f"{self.name}: {self.lines[0].text}"

    @property
    def body(self) -> str:
        """The lines after the first, for the bell and for a message."""
        return " ".join(f"{line.label}: {line.text}." for line in self.lines[1:])

    @property
    def message(self) -> str:
        """The whole brief as plain text, one line each."""
        return "\n".join(
            [self.name, *(f"{line.label}: {line.text}." for line in self.lines)]
        )


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def as_role(user, role: str):
    """``user`` as a reader in ``role``, without touching the saved account.

    The page services read the role a person is acting in. A brief is written
    for the role a person HOLDS, whichever hat they last wore in the browser.
    """
    reader = copy.copy(user)
    reader.active_role = role
    return reader


def _openable(reader, lines) -> tuple[BriefLine, ...]:
    """Lines keep a link only where the reader may follow it."""
    from apps.core.permissions import can_open_url

    return tuple(
        line
        if not line.url or can_open_url(reader, line.url)
        else BriefLine(line.label, line.text)
        for line in lines
    )


def previous_working_day(day: date) -> date:
    step = {0: 3, 6: 2}.get(day.weekday(), 1)
    return day - timedelta(days=step)


def next_working_day(day: date) -> date:
    step = {4: 3, 5: 2}.get(day.weekday(), 1)
    return day + timedelta(days=step)


def _before(day: date) -> Q:
    """Dated before ``day``, read the way My Plan reads a date."""
    return Q(planned_date__lt=day) | Q(
        planned_date__isnull=True, scheduled_date__date__lt=day
    )


def _on(day: date) -> Q:
    return Q(planned_date=day) | Q(planned_date__isnull=True, scheduled_date__date=day)


def _past_due(activities, today: date) -> int:
    from apps.my_plan.past_due_service import TERMINAL_OR_COMPLETED_STATUSES

    return (
        activities.exclude(status__in=TERMINAL_OR_COMPLETED_STATUSES)
        .filter(_before(today))
        .count()
    )


def _decisions(reader) -> tuple[int, int]:
    """(waiting on the reader, of which overdue), from their To-Do queue."""
    from apps.command_center.todo_service import get_todos

    counts = get_todos(reader)["counts"]
    return counts["waiting_me"], counts["overdue"]


def _decision_line(reader) -> BriefLine | None:
    waiting, overdue = _decisions(reader)
    if not waiting:
        return None
    text = f"{waiting} waiting on you"
    if overdue:
        text += f", {overdue} overdue"
    return BriefLine("Decisions", text, "/todos")


def _plan_line(label: str, totals, url: str) -> BriefLine | None:
    if not totals.visits_target:
        return None
    return BriefLine(
        label,
        f"{totals.staff_visits} of {totals.visits_target} visits planned "
        f"({totals.visit_progress or 0}%)",
        url,
    )


def _behind(officers) -> int:
    return sum(
        1
        for officer in officers
        if officer.visits_target and (officer.visit_progress or 0) < BEHIND_BELOW_PCT
    )


# ── Country Director ─────────────────────────────────────────────────────────
def country_morning(user, today: date) -> Brief | None:
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import activity_country_q, resolve_user_scope
    from apps.planning.planning_monitor import planning_monitor

    reader = as_role(user, BRIEF_ROLES[COUNTRY_MORNING])
    fy = get_operational_fy(today)
    totals = planning_monitor(reader, fy=fy)["totals"]
    country = Activity.objects.filter(deleted_at__isnull=True).filter(
        activity_country_q(resolve_user_scope(reader))
    )

    lines: list[BriefLine] = []
    plan = _plan_line("Plan", totals, f"/planning-monitor/?fy={fy}")
    if plan:
        lines.append(plan)
    decisions = _decision_line(reader)
    if decisions:
        lines.append(decisions)

    exceptions: list[BriefLine] = []
    behind = _behind(totals.officers)
    if behind:
        exceptions.append(
            BriefLine(
                "Behind on planning",
                f"{behind} of {_plural(len(totals.officers), 'person', 'people')} "
                f"under {BEHIND_BELOW_PCT}% of target",
                f"/planning-monitor/?fy={fy}",
            )
        )
    past_due = _past_due(country.filter(fy=fy), today)
    if past_due:
        exceptions.append(
            BriefLine(
                "Past due",
                _plural(past_due, "activity", "activities"),
                f"/country-planning-oversight/?view=execution&fy={fy}",
            )
        )
    late = country.filter(
        status="awaiting_ia_verification",
        submitted_to_ia_at__lte=timezone.now() - timedelta(hours=24),
    ).count()
    if late:
        exceptions.append(
            BriefLine(
                "Verification",
                f"{_plural(late, 'item')} waiting more than 24 hours",
                f"/country-planning-oversight/?view=execution&fy={fy}",
            )
        )
    lines += exceptions[:MAX_EXCEPTIONS]

    yesterday = previous_working_day(today)
    verified = country.filter(ia_confirmed_at__date=yesterday).count()
    if verified:
        lines.append(
            BriefLine(
                "Verified " + ("Friday" if today.weekday() == 0 else "yesterday"),
                _plural(verified, "activity", "activities"),
                "/completed-activities",
            )
        )
    return _brief(COUNTRY_MORNING, today, reader, lines)


# ── Programme Lead ───────────────────────────────────────────────────────────
def team_monday(user, today: date) -> Brief | None:
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.hr.team_roster import team_members
    from apps.my_plan.services import staff_my_plan_q
    from apps.planning.planning_monitor import planning_monitor

    reader = as_role(user, BRIEF_ROLES[TEAM_MONDAY])
    fy = get_operational_fy(today)
    totals = planning_monitor(reader, fy=fy)["totals"]
    officers = [o for o in totals.officers if not o.is_lead]

    lines: list[BriefLine] = []
    plan = _plan_line("Team plan", totals, f"/planning-monitor/?fy={fy}")
    if plan:
        lines.append(plan)
    if officers:
        behind = _behind(officers)
        lines.append(
            BriefLine(
                "Officers",
                f"{behind} of {len(officers)} under {BEHIND_BELOW_PCT}% of target"
                if behind
                else f"all {len(officers)} at or above {BEHIND_BELOW_PCT}% of target",
                f"/planning-monitor/?fy={fy}",
            )
        )

    team_ids = [
        identifier
        for member in team_members(reader)
        for identifier in (member.id, member.user_id)
        if identifier
    ]
    if team_ids:
        past_due = _past_due(
            Activity.objects.filter(deleted_at__isnull=True).filter(
                staff_my_plan_q(team_ids, reader)
            ),
            today,
        )
        if past_due:
            lines.append(
                BriefLine(
                    "Past due",
                    _plural(past_due, "activity", "activities"),
                    "/team-planning-oversight/",
                )
            )
    decisions = _decision_line(reader)
    if decisions:
        lines.append(BriefLine("Waiting on you", decisions.text, decisions.url))
    return _brief(TEAM_MONDAY, today, reader, lines)


# ── Regional Programme Lead ──────────────────────────────────────────────────
def regional_monday(user, today: date) -> Brief | None:
    from apps.analytics.rpl_dashboard_service import lead_roster_summary
    from apps.core.fy import get_operational_fy

    reader = as_role(user, BRIEF_ROLES[REGIONAL_MONDAY])
    summary = lead_roster_summary(reader, fy=get_operational_fy(today))

    lines: list[BriefLine] = []
    if summary["leads"]:
        lines.append(
            BriefLine(
                "Programme Leads",
                f"{summary['on_track']} of {summary['leads']} teams on track",
                "/dashboard",
            )
        )
    if summary["needs_coaching"]:
        lines.append(
            BriefLine(
                "Call first",
                f"{_plural(summary['needs_coaching'], 'team')} "
                "well behind on delivery",
                "/dashboard",
            )
        )
    if summary["follow_ups_active"]:
        text = f"{summary['follow_ups_active']} open"
        if summary["follow_ups_overdue"]:
            text += f", {summary['follow_ups_overdue']} overdue"
        lines.append(BriefLine("Your follow-ups", text, "/dashboard"))
    return _brief(REGIONAL_MONDAY, today, reader, lines)


# ── CCEO ─────────────────────────────────────────────────────────────────────
def field_evening(user, today: date) -> Brief | None:
    from apps.activities.models import Activity
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.core.scoping import owner_ids
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.my_plan.past_due_service import TERMINAL_OR_COMPLETED_STATUSES
    from apps.my_plan.services import ACTIVE_MY_PLAN_EXCLUDED_STATUSES, staff_my_plan_q

    reader = as_role(user, BRIEF_ROLES[FIELD_EVENING])
    ids = [i for i in owner_ids(reader) if i]
    if not ids:
        return None
    day = next_working_day(today)
    work = (
        Activity.objects.filter(deleted_at__isnull=True)
        .filter(_on(day))
        .filter(staff_my_plan_q(ids, reader))
        .exclude(
            status__in=(
                *ACTIVE_MY_PLAN_EXCLUDED_STATUSES,
                *COMPLETED_WORK_STATUSES,
                *TERMINAL_OR_COMPLETED_STATUSES,
            )
        )
    )
    counts = work.aggregate(
        activities=Count("id", distinct=True),
        schools=Count("school_id", distinct=True),
        sub_counties=Count("school__sub_county_id", distinct=True),
    )
    if not counts["activities"]:
        return None

    when = "Tomorrow" if (day - today).days == 1 else day.strftime("%A")
    text = _plural(counts["activities"], "activity", "activities")
    if counts["schools"]:
        text += f" at {_plural(counts['schools'], 'school')}"
    if counts["sub_counties"]:
        text += f" in {_plural(counts['sub_counties'], 'sub-county', 'sub-counties')}"
    lines = [BriefLine(when, text, "/my-plan")]

    request = (
        WeeklyFundRequest.objects.filter(
            responsible_user=user.id,
            week_start_date__lte=day,
            week_end_date__gte=day,
        )
        .order_by("-week_start_date")
        .first()
    )
    if request is not None:
        lines.append(
            BriefLine(
                "Funds",
                FUND_STATES.get(request.status, request.status.replace("_", " ")),
                f"/fund-requests/weekly/{request.id}",
            )
        )
    return _brief(FIELD_EVENING, today, reader, lines)


def _brief(kind: str, today: date, reader, lines) -> Brief | None:
    if not lines:
        return None
    return Brief(kind=kind, day=today, lines=_openable(reader, lines))


BUILDERS = {
    COUNTRY_MORNING: country_morning,
    TEAM_MONDAY: team_monday,
    REGIONAL_MONDAY: regional_monday,
    FIELD_EVENING: field_evening,
}


def build(kind: str, user, today: date | None = None) -> Brief | None:
    """The brief of ``kind`` for ``user`` on ``today``, or None for no news."""
    return BUILDERS[kind](user, today or timezone.localdate())


def kinds_for(user) -> list[str]:
    """The briefs a person is sent, by the roles they hold."""
    roles = set(getattr(user, "roles", None) or [])
    return [kind for kind, role in BRIEF_ROLES.items() if role in roles]
