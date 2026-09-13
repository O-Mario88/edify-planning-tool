"""Team target distribution To-Dos for a Programme Lead (owner, 2026-09-13).

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS. Impact
Assessment distributes each approved country target to the Programme Leads
(a "team" MilestoneAllocation); the lead then distributes what their team
received across themself and their officers and approves each holder's
quarterly spread (apps.hr.target_distribution, §13). Until now the lead heard
about the received target once, by notification, and nothing reminded them
while it sat undistributed.

* "Distribute your FY<year> team target — <milestone>" for every approved team
  target whose distribution within the team is not approved yet: no member
  rows, or member rows still in draft (approve_employee_distribution approves
  them all at once, and only when they reconcile).
* "Approve <officer>'s quarterly spread" while an approved member allocation
  under the lead's team target waits for its spread, one row per holder.

Rows are derived, so they close when the work is done. Years whose cycle is
archived are left out. Two queries whatever the number of milestones or
officers (apps/hr/test_pl_priorities.py pins it). Rows carry the "Strategic
Direction" responsibility (todo_service.PL_RESPONSIBILITY_CATEGORIES).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

CATEGORY = "Strategic Direction"
SOURCE = "Team Target Distribution"
TEAM_DISTRIBUTION_URL = "/target-distribution/team"

# Milestones named one per row before the rest fold into one row.
MILESTONE_ROW_LIMIT = 5
NOT_LIVE = ("rejected", "superseded")


def _row(key, *, title, description, url, action, linked, today, priority="high"):
    return {
        "id": key,
        "title": title,
        "description": (description or "")[:180],
        "category": CATEGORY,
        "priority": priority,
        "status_key": "waiting_me",
        "status_label": "Waiting on Me",
        "status_tone": "warning",
        "due_label": "—",
        "due_tone": "neutral",
        "linked": linked,
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": SOURCE,
        "_due_sort": today,
    }


def _url(fy: str) -> str:
    return f"{TEAM_DISTRIBUTION_URL}?{urlencode({'fy': fy})}"


def distribution_todos(principal, role, today) -> list[dict]:
    if role != "Program Lead":
        return []
    staff_id = getattr(principal, "staff_profile_id", None)
    if not staff_id:
        return []
    today = today or timezone.localdate()
    try:
        return _team_target_rows(str(staff_id), today) + _spread_rows(
            str(staff_id), today
        )
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Team distribution To-Dos failed")
        return []


def _current_cycles() -> Q:
    return Q(milestone__priority__cycle__isnull=False) & ~Q(
        milestone__priority__cycle__status="archived"
    )


def _team_target_rows(staff_id: str, today) -> list[dict]:
    from .models import MilestoneAllocation

    teams = list(
        MilestoneAllocation.objects.filter(
            _current_cycles(),
            allocated_to_type="team",
            team_id=staff_id,
            status="approved",
            milestone__active=True,
        )
        .annotate(
            live_members=Count(
                "children", filter=~Q(children__status__in=NOT_LIVE), distinct=True
            ),
            approved_members=Count(
                "children", filter=Q(children__status="approved"), distinct=True
            ),
        )
        .values(
            "id",
            "milestone_id",
            "milestone__title",
            "milestone__priority__fy",
            "milestone__priority__sequence",
            "milestone__source_order",
            "live_members",
            "approved_members",
        )
        .order_by(
            "milestone__priority__fy",
            "milestone__priority__sequence",
            "milestone__source_order",
        )
    )
    open_rows = [
        row
        for row in teams
        if not row["live_members"] or row["approved_members"] < row["live_members"]
    ]
    out = []
    for row in open_rows[:MILESTONE_ROW_LIMIT]:
        fy = row["milestone__priority__fy"]
        started = bool(row["live_members"])
        out.append(
            _row(
                f"distribution-team-{row['id']}",
                title=f"Distribute your FY{fy} team target — {row['milestone__title']}",
                description=(
                    "Your team's distribution is drafted but not approved: balance "
                    "it across yourself and your officers, then approve it."
                    if started
                    else "Impact Assessment approved this target for your team. "
                    "Distribute it across yourself and your officers."
                ),
                url=_url(fy),
                action="Continue distribution" if started else "Distribute",
                linked=row["milestone__title"],
                today=today,
            )
        )
    rest = open_rows[MILESTONE_ROW_LIMIT:]
    if rest:
        years = sorted({row["milestone__priority__fy"] for row in rest})
        out.append(
            _row(
                f"distribution-team-more-{staff_id}",
                title=(
                    f"Distribute {len(rest)} more team target"
                    f"{'' if len(rest) == 1 else 's'}"
                ),
                description=(
                    "Further targets Impact Assessment approved for your team are "
                    "not distributed within the team yet (FY"
                    + ", FY".join(years)
                    + ")."
                ),
                url=_url(years[0]),
                action="Open distribution",
                linked="Team Target Distribution",
                today=today,
            )
        )
    return out


def _spread_rows(staff_id: str, today) -> list[dict]:
    from .models import MilestoneAllocation

    waiting = list(
        MilestoneAllocation.objects.filter(
            _current_cycles(),
            allocated_to_type="employee",
            parent__allocated_to_type="team",
            parent__team_id=staff_id,
            parent__status="approved",
            status="approved",
            employee__isnull=False,
        )
        .exclude(quarter_status="approved")
        .values(
            "employee_id",
            "employee__user__name",
            "milestone__title",
            "milestone__priority__fy",
        )
        .order_by("employee__user__name", "milestone__priority__fy", "milestone__title")
    )
    by_holder: dict[str, dict] = {}
    for row in waiting:
        holder = by_holder.setdefault(
            str(row["employee_id"]),
            {
                "name": row["employee__user__name"] or "an officer",
                "milestones": [],
                "fy": row["milestone__priority__fy"],
            },
        )
        holder["milestones"].append(row["milestone__title"])
    out = []
    for holder_id, holder in by_holder.items():
        count = len(holder["milestones"])
        is_self = holder_id == staff_id
        title = (
            "Approve your own quarterly spread"
            if is_self
            else f"Approve {holder['name']}'s quarterly spread"
        )
        out.append(
            _row(
                f"distribution-spread-{holder_id}",
                title=title,
                description=(
                    f"{count} approved target{'' if count == 1 else 's'} waiting for "
                    "a quarterly spread: "
                    + "; ".join(holder["milestones"][:3])
                    + ("…" if count > 3 else "")
                ),
                url=_url(holder["fy"]),
                action="Approve spread",
                linked=holder["name"],
                today=today,
                priority="medium",
            )
        )
    return out
