"""Home's Priority actions for a CCEO and a Programme Lead.

Owner, 2026-10-24: the phone Home's Priority actions are a fixed list per
role, each row linked to its page.

  Programme Lead: My Overdue Plans, Follow up with CCEOs Overdue Plans,
  Schools Not Clustered, Verify CCEO Completed Activities, Schools With No
  Visits, Schools With No Trainings, Schools With No SSA, My Team
  Performance.

  CCEO: My Overdue Plans, Schools Not Clustered, Schools With No Visits,
  Schools With No Trainings, Schools With No SSA, My Performance.

Each row opens the table that lists what it counts (owner, later that day),
and every count is read from the service behind that table, so the number
and the list cannot disagree:

  • overdue plans — the dashboard's overdue table, "What needs you now"
    (`past_due_service`): a CCEO's own; a Lead's opened on My Plans for
    their own and on Team Plans for their CCEOs';
  • a CCEO's school rows — their own Planning Monitor row (`own_monitor`),
    the same schools My Plan lists under ?list=<list>;
  • a Lead's school rows — the Lead's team on the Planning Monitor
    (`planning_monitor`), the table its ?gap=<list> opens on their
    dashboard, where the monitor lives;
  • completions to verify — the Lead's Completion Reviews register, on the
    same dashboard;
  • a CCEO's no SSA — the School Directory's "No Confirmed SSA" gap.

A school is "with no visits", "no trainings" or "no SSA" until one is
completed (owner: "ONLY schools with completed visits or training or ssa are
not fetched"): a planned one does not take it off the list.

A figure that cannot be read shows no number, never a zero. Every other role
keeps the To-Do queue (`home_service.build_home_queue`).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

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
        "no_ssa",
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

#: Each school row → the Planning Monitor list that holds its schools
#: (planning_monitor.GAPS and LISTS). A CCEO's no SSA is the School
#: Directory's instead (`_ssa_gap_count`).
SCHOOL_LISTS = {
    "not_clustered": "not_clustered",
    "no_visit": "not_visited",
    "no_training": "not_trained",
    "no_ssa": "no_ssa",
}

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
        "past their date, not completed",
    ),
    "team_overdue": (
        "Follow up with CCEOs Overdue Plans",
        "",
        "bell",
        "Follow up",
        "past their date, not completed",
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
        "No visit completed this year",
    ),
    "no_training": (
        "Schools With No Trainings",
        "School With No Trainings",
        "calendar",
        "Plan",
        "No training completed this year",
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


def _on_dashboard(query: str, anchor: str, fy) -> str:
    """A table of the Planning Monitor where a Lead reads it: carried on
    their dashboard (apps.frontend.views.dashboard_embed), opened at the
    table itself (static/js/dashboard-embed.js scrolls to it once the
    monitor is in)."""
    from apps.frontend.views.dashboard_embed import PLANNING_MONITOR

    params = urlencode({"fy": fy, PLANNING_MONITOR.param: query})
    return f"/dashboard?{params}#{anchor}"


def _url(key: str, role: str, fy) -> str:
    if key == "my_overdue":
        if role == PL:
            return "/dashboard?view=week&plans=own#what-needs-you-now"
        return "/dashboard?view=week#what-needs-you-now"
    if key == "team_overdue":
        return "/dashboard?view=week&plans=team#what-needs-you-now"
    if key == "verify":
        return _on_dashboard(f"view=execution&fy={fy}", "completion-reviews", fy)
    if key == "no_ssa" and role != PL:
        return "/schools?gap=no_ssa"
    if key in SCHOOL_LISTS:
        listed = SCHOOL_LISTS[key]
        if role == PL:
            return _on_dashboard(
                f"view=planning&fy={fy}&gap={listed}", "monitor-list", fy
            )
        return f"/my-plan?list={listed}#plan-list"
    return {
        "my_performance": "/team-performance/",
        "team_performance": "/team-performance/",
    }[key]


# ── The figures ─────────────────────────────────────────────────────────────
def _overdue(user, role) -> dict[str, int]:
    """The dashboard overdue table's counts: a CCEO's own; a Lead's own and
    their team's, its My Plans and Team Plans."""
    from apps.my_plan.past_due_service import get_past_due_dashboard_context

    table = get_past_due_dashboard_context(user)
    if role == PL:
        return {
            "my_overdue": table["pl_own_past_due_count"],
            "team_overdue": table["pl_team_past_due_count"],
        }
    return {"my_overdue": table["past_due_total_count"]}


def _school_counts(user, role, fy) -> dict[str, int]:
    """Each school row's count on the reader's monitor: their own row for a
    CCEO, their team for a Lead."""
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
    keys = [key for key in SCHOOL_LISTS if key in ROLE_ROWS[role]]
    if role != PL:
        keys = [key for key in keys if key != "no_ssa"]
    return {key: len(list_schools(officers, SCHOOL_LISTS[key])) for key in keys}


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


def _counts(user, role, fy) -> dict[str, int | None]:
    keys = ROLE_ROWS[role]
    overdue = _read("overdue", lambda: _overdue(user, role)) or {}
    schools = _read("school_rows", lambda: _school_counts(user, role, fy)) or {}
    # A figure missing from here was not read: its row shows no number.
    counts: dict[str, int | None] = {**overdue, **schools}
    if "verify" in keys:
        counts["verify"] = _read("verify", lambda: _waiting_review(user))
    if "no_ssa" in keys and role != PL:
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

    fy = get_operational_fy()
    counts = _counts(user, role, fy)
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
        f"home-priorities:v2:{user.id}:{role}:{timezone.localdate().isoformat()}",
        lambda: _build(user, role),
        timeout=settings.TODO_SNAPSHOT_CACHE_SECONDS,
    )
