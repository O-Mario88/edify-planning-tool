"""The weekly check-in: one officer's week on one page, for the Programme
Lead and the officer to read together.

Nothing here is a new record or a new figure. The year's visits are the
officer's Planning Monitor row, the week's work is their My Plan, the money is
their weekly fund request, and what was agreed is the coaching record the Lead
writes at the end (kind "Performance check-in", apps.cce_leadership.coaching).
Next week's page opens with this week's agreed actions, which is what makes
the check-in a rhythm and not a form.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .coaching import _owner_ids, _team, state_of
from .models import CceoCoaching, CoachingKind

CHECK_IN_KIND = CoachingKind.PERFORMANCE_CHECKIN
RETURNED_STATUSES = ("returned_by_pl", "returned", "returned_by_ia")
URL = "/team/check-in"


def week_of(day: date) -> tuple[date, date]:
    """The Monday and the Sunday of ``day``'s week."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def team_order(principal) -> list:
    """The Lead's officers in the order the check-in walks them: by name."""
    return sorted(
        _team(principal), key=lambda m: (getattr(m.user, "name", "") or "").lower()
    )


def neighbours(members, member) -> tuple:
    """(previous, next) officer around ``member``; None at either end."""
    index = next(i for i, m in enumerate(members) if m.id == member.id)
    return (
        members[index - 1] if index else None,
        members[index + 1] if index + 1 < len(members) else None,
    )


def _fact(line: str, figure, url: str = "", tone: str = "") -> dict:
    return {"line": line, "figure": figure, "url": url, "tone": tone}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def week_facts(member, *, today: date | None = None) -> list[dict]:
    """The officer's week and year, one row a line, each with its table."""
    from apps.activities.models import Activity
    from apps.briefs.builder import FUND_STATES, as_role
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.my_plan.past_due_service import TERMINAL_OR_COMPLETED_STATUSES
    from apps.my_plan.services import staff_my_plan_q
    from apps.planning.planning_monitor import own_monitor

    from .coaching import NOT_LIVE_STATUSES

    today = today or timezone.localdate()
    start, end = week_of(today)
    fy = get_operational_fy(today)
    officer = as_role(member.user, EdifyRole.CCEO.value)
    plan_url = "/team-planning-oversight/"

    facts: list[dict] = []
    year = own_monitor(officer, fy)
    if year is not None and year.visits_target:
        facts.append(
            _fact(
                "Visits planned this year",
                f"{year.staff_visits} of {year.visits_target} "
                f"({year.visit_progress or 0}%)",
                f"/planning-monitor/?fy={fy}&officer={year.key}",
                "" if (year.visit_progress or 0) >= 50 else "warning",
            )
        )
        facts.append(
            _fact(
                "Visits delivered this year",
                f"{year.visits_done} of {year.staff_visits} planned",
                f"/planning-monitor/?fy={fy}&officer={year.key}",
            )
        )

    mine = Activity.objects.filter(deleted_at__isnull=True).filter(
        staff_my_plan_q(_owner_ids(member), officer)
    )
    in_week = Q(planned_date__gte=start, planned_date__lte=end) | Q(
        planned_date__isnull=True,
        scheduled_date__date__gte=start,
        scheduled_date__date__lte=end,
    )
    before_today = Q(planned_date__lt=today) | Q(
        planned_date__isnull=True, scheduled_date__date__lt=today
    )
    counts = mine.exclude(status__in=NOT_LIVE_STATUSES).aggregate(
        planned=Count("id", filter=in_week),
        delivered=Count("id", filter=in_week & Q(status__in=COMPLETED_WORK_STATUSES)),
        returned=Count("id", filter=Q(status__in=RETURNED_STATUSES)),
        past_due=Count(
            "id",
            filter=before_today & ~Q(status__in=TERMINAL_OR_COMPLETED_STATUSES),
        ),
    )
    facts += [
        _fact(
            "Planned this week",
            _plural(counts["planned"], "activity", "activities"),
            plan_url,
        ),
        _fact(
            "Delivered this week",
            f"{counts['delivered']} of {counts['planned']}",
            plan_url,
        ),
        _fact(
            "Returned for correction",
            _plural(counts["returned"], "activity", "activities"),
            plan_url,
            "warning" if counts["returned"] else "",
        ),
        _fact(
            "Past due",
            _plural(counts["past_due"], "activity", "activities"),
            plan_url,
            "danger" if counts["past_due"] else "",
        ),
    ]

    request = (
        WeeklyFundRequest.objects.filter(
            responsible_user=member.user_id,
            week_start_date__lte=end,
            week_end_date__gte=start,
        )
        .order_by("-week_start_date")
        .first()
    )
    facts.append(
        _fact(
            "This week's funds",
            FUND_STATES.get(request.status, request.status.replace("_", " "))
            if request
            else "no request this week",
            f"/fund-requests/weekly/{request.id}" if request else "",
        )
    )

    from apps.accounts.models import Leave

    horizon = (end + timedelta(days=7)).isoformat()
    leave = (
        Leave.objects.filter(
            staff_id=member.id,
            status__iexact="approved",
            start_date__lte=horizon,
            end_date__gte=start.isoformat(),
        )
        .order_by("start_date")
        .first()
    )
    facts.append(
        _fact(
            "Leave, this week and next",
            f"{leave.start_date[:10]} to {leave.end_date[:10]}" if leave else "none",
        )
    )
    return facts


def last_check_in(member, *, today: date | None = None) -> dict | None:
    """What was agreed last time, and whether it has been followed up."""
    record = (
        CceoCoaching.objects.filter(cceo_staff_id=member.id, kind=CHECK_IN_KIND)
        .order_by("-held_on", "-created_at")
        .first()
    )
    if record is None:
        return None
    label, tone = state_of(record, today=today)
    return {
        "id": record.id,
        "held_on": record.held_on,
        "agreed_actions": record.agreed_actions,
        "follow_up_due": record.follow_up_due,
        "state": label,
        "tone": tone,
    }


def held_this_week(members, *, today: date | None = None) -> set[str]:
    """Staff ids of the officers already checked in with this week."""
    start, end = week_of(today or timezone.localdate())
    return set(
        CceoCoaching.objects.filter(
            kind=CHECK_IN_KIND,
            cceo_staff_id__in=[m.id for m in members],
            held_on__gte=start,
            held_on__lte=end,
        ).values_list("cceo_staff_id", flat=True)
    )
