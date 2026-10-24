"""Home's Priority actions for a CCEO and a Programme Lead.

Owner, 2026-10-24: the phone Home's Priority actions are a fixed list per
role, each row linked to its page.

  Programme Lead: My Overdue Plans, Follow up with CCEOs Overdue Plans,
  Schools Not Clustered, Verify CCEO Completed Activities, Schools With No
  Visits, Schools With No Trainings, My Team Performance.

  CCEO: My Overdue Plans, Schools Not Clustered, Schools With No Visits,
  Schools With No Trainings, Schools With No SSA, My Performance.

Every count is read from the service behind the page its row opens, so the
number and the list cannot disagree:

  • overdue plans — My Plan's own "overdue" filter (`plan_state_q`);
  • a CCEO's school gaps — their own Planning Monitor row (`own_monitor`),
    the same schools My Plan lists under ?list=<gap>;
  • a Lead's school gaps — the Lead's team on the Planning Monitor
    (`planning_monitor`), the schools its ?gap=<gap> list holds;
  • the CCEOs' overdue plans — the Execution Monitor's overdue, for the
    Lead's CCEOs only (the Lead's own are on My Overdue Plans);
  • completions to verify — the Lead's Completion Reviews register;
  • no SSA — the School Directory's "No Confirmed SSA" gap.

A figure that cannot be read shows no number, never a zero. Every other role
keeps the To-Do queue (`home_service.build_home_queue`).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.core.navigation import CCEO, PL, get_user_role_slug

logger = logging.getLogger(__name__)

#: The rows each role's Home lists, in the owner's order.
ROLE_ROWS: dict[str, tuple[str, ...]] = {
    PL: (
        "my_overdue",
        "team_overdue",
        "not_clustered",
        "verify",
        "no_visit",
        "no_training",
        "team_performance",
    ),
    CCEO: (
        "my_overdue",
        "not_clustered",
        "no_visit",
        "no_training",
        "no_ssa",
        "my_performance",
    ),
}

#: The Planning Monitor gaps a school row counts (planning_monitor.GAPS).
SCHOOL_GAPS = ("not_clustered", "no_visit", "no_training")

#: key → (title, title for one, icon, action label, what it counts). A row
#: whose "title for one" is set carries its count in its title ("12 Schools
#: With No Visits", as the owner wrote them); the others say it underneath.
#: "what it counts" is None for a page to open with nothing to count.
SPECS: dict[str, tuple[str, str, str, str, str | None]] = {
    "my_overdue": (
        "My Overdue Plans",
        "",
        "warning",
        "Open",
        "past their date, not started",
    ),
    "team_overdue": (
        "Follow up with CCEOs Overdue Plans",
        "",
        "bell",
        "Follow up",
        "past their date, not delivered",
    ),
    "not_clustered": (
        "Schools Not Clustered",
        "School Not Clustered",
        "grid",
        "Cluster",
        "In no active cluster",
    ),
    "verify": (
        "Verify CCEO Completed Activities",
        "",
        "check",
        "Verify",
        "waiting on your review",
    ),
    "no_visit": (
        "Schools With No Visits",
        "School With No Visits",
        "calendar",
        "Plan",
        "No visit planned this year",
    ),
    "no_training": (
        "Schools With No Trainings",
        "School With No Trainings",
        "calendar",
        "Plan",
        "No training planned this year",
    ),
    "no_ssa": (
        "Schools With No SSA",
        "School With No SSA",
        "chart",
        "Open",
        "No confirmed SSA this year",
    ),
    "my_performance": ("My Performance", "", "chart", "Open", None),
    "team_performance": ("My Team Performance", "", "chart", "Open", None),
}

#: The line under a page with nothing to count.
PAGE_LINES = {
    "my_performance": "Your targets and achievements this year",
    "team_performance": "Your CCEOs' targets and achievements",
}

#: What a row says when its figure could not be read.
UNREAD_LINE = "Could not be counted just now. Open the list to see it."


def _url(key: str, role: str, fy) -> str:
    if key == "my_overdue":
        return "/my-plan?status=overdue"
    if key in SCHOOL_GAPS:
        if role == PL:
            return f"/planning-monitor/?view=planning&fy={fy}&gap={key}#monitor-list"
        return f"/my-plan?list={key}#plan-list"
    return {
        "team_overdue": f"/planning-monitor/?view=execution&fy={fy}&list=overdue",
        "verify": "/pl/review-queue",
        "no_ssa": "/schools?gap=no_ssa",
        "my_performance": "/team-performance/",
        "team_performance": "/team-performance/",
    }[key]


# ── The figures ─────────────────────────────────────────────────────────────
def _own_overdue(user, today, fy) -> int:
    from apps.my_plan.services import my_plan_activities, plan_state_q

    return my_plan_activities(user, fy).filter(plan_state_q("overdue", today)).count()


def _school_gap_counts(user, role, fy) -> dict[str, int]:
    """Each school gap on the reader's monitor: their own row for a CCEO,
    their team for a Lead."""
    from apps.planning.planning_monitor import (
        list_schools,
        own_monitor,
        planning_monitor,
    )

    if role == PL:
        officers = list(planning_monitor(user, fy=str(fy))["totals"].officers)
    else:
        officer = own_monitor(user, str(fy))
        officers = [officer] if officer is not None else []
    return {key: len(list_schools(officers, key)) for key in SCHOOL_GAPS}


def _team_overdue(user, today, fy) -> int:
    """The Execution Monitor's overdue for the Lead's CCEOs, not the Lead."""
    from apps.planning.execution_monitor import execution_monitor
    from apps.planning.monitor_roster import ROLE_CCEO

    monitor = execution_monitor(user, fy=str(fy), today=today)
    return sum(
        person.overdue
        for team in monitor["teams"]
        for person in team.people
        if person.role == ROLE_CCEO
    )


def _waiting_review(user) -> int:
    from apps.pl_review.services import waiting_count

    return waiting_count(user)


def _ssa_gap_count(user, fy) -> int:
    """The School Directory's "No Confirmed SSA" for the reader's own
    schools, as /schools?gap=no_ssa counts them."""
    from apps.core.scoping import resolve_user_scope, school_queryset
    from apps.schools.data_gaps import no_ssa_q

    schools = school_queryset(resolve_user_scope(user), direct_only=True)
    return schools.filter(deleted_at__isnull=True).filter(no_ssa_q(fy)).count()


def _read(name, compute):
    """A figure, or None when it cannot be read: Home is never the reason a
    page fails, and an unread figure is never shown as zero."""
    try:
        return compute()
    except Exception:  # noqa: BLE001 - one figure must not take Home down
        logger.exception("Home priority figure %s failed", name)
        return None


def _counts(user, role, today, fy) -> dict[str, int | None]:
    keys = ROLE_ROWS[role]
    counts: dict[str, int | None] = {
        "my_overdue": _read("my_overdue", lambda: _own_overdue(user, today, fy))
    }
    gaps = _read("school_gaps", lambda: _school_gap_counts(user, role, fy)) or {}
    for key in SCHOOL_GAPS:
        counts[key] = gaps.get(key)
    if "team_overdue" in keys:
        counts["team_overdue"] = _read(
            "team_overdue", lambda: _team_overdue(user, today, fy)
        )
    if "verify" in keys:
        counts["verify"] = _read("verify", lambda: _waiting_review(user))
    if "no_ssa" in keys:
        counts["no_ssa"] = _read("no_ssa", lambda: _ssa_gap_count(user, fy))
    return counts


# ── The rows ────────────────────────────────────────────────────────────────
def _row(key: str, count: int | None, *, role: str, fy) -> dict:
    title, one, icon, action, counts_what = SPECS[key]
    if counts_what is None:
        context, status, tone = PAGE_LINES[key], ("", "plain"), "info"
    elif count is None:
        context, status, tone = UNREAD_LINE, ("", "plain"), "info"
    else:
        if one:
            title = f"{count:,} {one if count == 1 else title}"
            context = counts_what
        else:
            context = f"{count:,} {counts_what}"
        status = ("Critical", "alert") if count else ("All clear", "good")
        tone = "alert" if count else "info"
    return {
        "key": key,
        "title": title,
        "context": context,
        "due_label": "",
        "due_tone": "plain",
        "status_label": status[0],
        "status_tone": status[1],
        "mark_tone": tone,
        "action_label": action,
        "url": _url(key, role, fy),
        "icon": icon,
        "count": count,
    }


def _build(user, role: str) -> list[dict]:
    from apps.core.fy import get_operational_fy

    today = timezone.localdate()
    fy = get_operational_fy()
    counts = _counts(user, role, today, fy)
    return [_row(key, counts.get(key), role=role, fy=fy) for key in ROLE_ROWS[role]]


def role_priorities(user) -> list[dict] | None:
    """The reader's Priority actions when the owner set their role's list;
    None for every other role, which keeps the To-Do queue.

    Cached as briefly as the To-Do snapshot, under the reader, the role and
    the day, so moving between pages does not read the monitors again."""
    from apps.core.cache_utils import stampede_safe_get_or_compute

    role = get_user_role_slug(user)
    if role not in ROLE_ROWS:
        return None
    return stampede_safe_get_or_compute(
        f"home-priorities:v1:{user.id}:{role}:{timezone.localdate().isoformat()}",
        lambda: _build(user, role),
        timeout=settings.TODO_SNAPSHOT_CACHE_SECONDS,
    )
