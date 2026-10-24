"""Home: the phone's first tab and the native app's start page.

Home answers three questions for the person signed in: what needs me now,
what is coming up, and where do I go to do it. It computes nothing of its own.
Every figure and row comes from the service that already owns it:

  • Priority actions — the To-Do queue (apps.command_center.todo_service),
    which is role-scoped, permission-filtered and ordered by priority then due
    date. Home shows its first entries; the To-Do page shows the rest.
  • Plan figures and upcoming activities — the reader's own My Plan
    (apps.my_plan.services.my_plan_activities) in the operational financial
    year, split by `plan_state_q`, the same filter each figure opens on My
    Plan. Only roles whose My Plan is the field plan get them; everyone else
    gets the To-Do figures instead of zeros that mean nothing.
  • Quick access — the role's own sidebar pages that are not bottom-bar tabs
    (apps.core.navigation.build_home_shortcuts_for_user).

Nothing here grants access: each row links to a page that runs its own
permission check, and the To-Do queue already dropped rows whose page the
role cannot open.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, Q
from django.utils import timezone

from apps.command_center.todo_groups import context_line
from apps.core.navigation import (
    CCEO,
    PARTNER,
    PL,
    build_home_shortcuts_for_user,
    get_user_role_slug,
)

#: How many To-Do entries Home lists before "View all".
PRIORITY_LIMIT = 5
#: How many upcoming activities Home lists before "View all".
UPCOMING_LIMIT = 4

#: Roles whose My Plan is the field plan at /my-plan. A Project Coordinator's
#: plan is project-scoped (/projects/my-plan) and other roles have no plan of
#: their own, so they get no plan figures rather than misleading zeros.
PLAN_ROLES = frozenset({CCEO, PL, PARTNER})

#: How the header names each role, from the slug every permission reads.
ROLE_TITLES = {
    "ADMIN": "Admin",
    "CCEO": "CCEO",
    "PL": "Programme Lead",
    "CD": "Country Director",
    "IA": "Impact Assessment",
    "RVP": "Regional Vice President",
    "RPL": "Regional Programme Lead",
    "HR": "Human Resources",
    "ACCOUNTANT": "Accountant",
    "PARTNER": "Partner",
    "PROJECT_COORDINATOR": "Project Coordinator",
    "BUSINESS_TRANSFORMATION": "Business Transformation",
    "MFI_ADMIN": "MFI Admin",
    "MFI_OFFICER": "MFI Loan Officer",
}

#: A To-Do's category → the small icon its row carries.
CATEGORY_ICONS = {
    "Execution": "calendar",
    "Evidence": "upload",
    "SSA": "chart",
    "Finance": "money",
}

#: A To-Do priority → the tone of its tag.
PRIORITY_TONES = {"critical": "alert", "high": "caution", "medium": "info"}

#: The queue's tones (todo_service) → Home's tone class names. Home's classes
#: avoid the words the indexed stylesheet build matches on ("danger",
#: "warning", "success"…, scripts/build_indexed_css.cjs), so a legacy rule
#: written for another page can never reach them.
TONES = {
    "danger": "alert",
    "warning": "caution",
    "success": "good",
    "info": "info",
    "primary": "brand",
}


def tone(value: str | None) -> str:
    return TONES.get(value or "", "plain")


def greeting_for(moment: datetime) -> str:
    """Good morning / afternoon / evening for a local time."""
    if moment.hour < 12:
        return "Good morning"
    if moment.hour < 17:
        return "Good afternoon"
    return "Good evening"


def first_name(user) -> str:
    name = (getattr(user, "name", "") or "").strip()
    return name.split()[0] if name else ""


#: Home's plan figures: (state, registered metric, icon, tone, helper). The
#: state is a My Plan filter (apps.my_plan.services.PLAN_STATES), so each
#: figure opens the list of exactly the activities it counts.
PLAN_FIGURES = (
    ("upcoming", "home_plan_upcoming", "calendar", "brand", "Not started, date ahead"),
    ("under_way", "home_plan_under_way", "clock", "info", "Started, not yet verified"),
    ("overdue", "home_plan_overdue", "warning", "alert", "Not started, date passed"),
)

#: The To-Do queue's figures: (count, registered metric, icon, tone, helper).
#: The tone is the figure's when it is not zero.
QUEUE_FIGURES = (
    ("waiting_me", "home_todo_waiting", "check", "caution", "Waiting on you"),
    ("due_today", "home_todo_due_today", "clock", "caution", "Finish before day end"),
    ("critical", "home_todo_critical", "warning", "alert", "Highest priority"),
)


def _figure(metric_key, value, *, key, icon, tone, helper, url, loading=False):
    """One overview tile, through the metrics registry (apps.core.metrics): its
    label, definition and accessible description are the registered
    metric's."""
    from apps.core.metrics import render_precomputed_metric_item

    return render_precomputed_metric_item(
        metric_key,
        value,
        drilldown_url=url,
        key=key,
        icon=icon,
        tone=tone,
        helper=helper,
        url=url,
        loading=loading,
    )


def plan_figures(user, today, fy) -> list[dict]:
    """Planned, In progress and Overdue on the reader's own plan, each with the
    My Plan list that shows exactly those activities. One query."""
    from apps.my_plan.services import my_plan_activities, plan_state_q

    counts = my_plan_activities(user, fy).aggregate(
        **{
            state: Count("id", filter=plan_state_q(state, today))
            for state, *_ in PLAN_FIGURES
        }
    )
    figures = []
    for state, metric_key, icon, tone_class, helper in PLAN_FIGURES:
        value = counts[state]
        # Overdue reads as an alarm only when there is something overdue.
        if state == "overdue" and not value:
            tone_class = "plain"
        figures.append(
            _figure(
                metric_key,
                value,
                key=state,
                icon=icon,
                tone=tone_class,
                helper=helper,
                url=f"/my-plan?status={state}",
            )
        )
    return figures


def todo_figures(counts: dict | None, *, with_plan: bool) -> list[dict]:
    """The To-Do queue's own counts. A planner gets one (its plan figures
    carry the rest); anyone else gets the three that describe their queue.

    `counts=None` is the page before the queue has loaded: the same tiles,
    valueless, so the row does not move when the values arrive."""
    specs = QUEUE_FIGURES[:1] if with_plan else QUEUE_FIGURES
    figures = []
    for key, metric_key, icon, tone_class, helper in specs:
        value = None if counts is None else counts.get(key, 0)
        figures.append(
            _figure(
                metric_key,
                value,
                key=key,
                icon=icon,
                tone=tone_class if value else "plain",
                helper=helper,
                url="/todos",
                loading=counts is None,
            )
        )
    return figures


def _group_row(entry: dict) -> dict:
    first = entry["items"][0]
    return {
        "title": entry["title"],
        "context": f"{entry['count']} like this",
        "due_label": first.get("due_label") or "",
        "due_tone": tone(first.get("due_tone")),
        "status_label": entry["priority_label"],
        "status_tone": PRIORITY_TONES.get(entry["priority"], "plain"),
        "action_label": "Review",
        "url": "/todos",
        "icon": CATEGORY_ICONS.get(entry["category"], "flag"),
        "count": entry["count"],
    }


def _todo_row(todo: dict) -> dict:
    due = todo.get("due_label") or ""
    status = todo.get("status_label") or ""
    title = todo.get("title") or ""
    return {
        "title": title,
        "context": context_line(title, todo["linked"])
        if todo.get("linked")
        else todo.get("description") or "",
        # No date, or the same word as the status ("Overdue" twice).
        "due_label": "" if due in ("—", status) else due,
        "due_tone": tone(todo.get("due_tone")),
        "status_label": status,
        "status_tone": tone(todo.get("status_tone")),
        "action_label": todo.get("action_label") or "Open",
        "url": todo.get("action_url") or "/todos",
        "icon": CATEGORY_ICONS.get(todo.get("category"), "flag"),
        "count": 0,
    }


def priority_actions(todos: list[dict], limit: int = PRIORITY_LIMIT) -> list[dict]:
    """The queue's first `limit` entries as Home rows, in the queue's order.
    Identical To-Dos are one row with their count
    (apps.command_center.todo_groups), as on the To-Do page, so eight "plan
    this school" rows do not crowd out everything else."""
    from apps.command_center.todo_groups import group_identical

    return [
        _group_row(entry) if entry["group"] else _todo_row(entry["todo"])
        for entry in group_identical(todos)[:limit]
    ]


def upcoming_activities(user, today, fy, limit: int = UPCOMING_LIMIT) -> list[dict]:
    """The reader's next not-started activities, soonest first: those the
    Planned figure counts that carry a date."""
    from apps.core.clock import local_clock, local_day
    from apps.my_plan.services import my_plan_activities, plan_state_q

    rows = (
        my_plan_activities(user, fy)
        .filter(plan_state_q("upcoming", today))
        .filter(Q(planned_date__isnull=False) | Q(scheduled_date__isnull=False))
        .select_related("school", "cluster")
        .order_by("planned_date", "scheduled_date", "id")[:limit]
    )
    out = []
    for a in rows:
        day = a.planned_date or local_day(a.scheduled_date)
        if a.school_id:
            where = a.school.name
        else:
            where = a.cluster.name if a.cluster_id else ""
        out.append(
            {
                "id": a.id,
                "month": f"{day:%b}".upper(),
                "day": day.day,
                "is_today": day == today,
                "title": a.activity_purpose_text or a.get_activity_type_display(),
                "type_label": a.get_activity_type_display(),
                "where": where,
                "time": local_clock(a.scheduled_date),
                "status_label": a.get_status_display(),
                "url": f"/my-plan/{a.id}",
            }
        )
    return out


def build_home(user, current_path: str = "/home") -> dict:
    """The Home page for `user`, without the To-Do queue.

    The queue is the slowest read on the page — it derives every workflow's
    open actions for the reader — so the page is drawn first and asks for it
    (`build_home_queue`, /home/queue) once it is on screen."""
    from apps.core.fy import get_operational_fy

    role = get_user_role_slug(user)
    now = timezone.localtime()
    today = now.date()
    fy = get_operational_fy()
    has_plan = role in PLAN_ROLES
    figures = plan_figures(user, today, fy) if has_plan else []
    figures += todo_figures(None, with_plan=has_plan)

    return {
        "greeting": greeting_for(now),
        "first_name": first_name(user),
        "role_title": ROLE_TITLES.get(role, ""),
        "today": today,
        "fy": fy,
        "figures": figures,
        "has_plan": has_plan,
        "upcoming": upcoming_activities(user, today, fy) if has_plan else [],
        "shortcuts": build_home_shortcuts_for_user(user, current_path),
    }


def build_home_queue(user) -> dict:
    """Home's Priority actions, and the To-Do figures where they come with them.

    A CCEO's and a Programme Lead's Priority actions are the list the owner
    set for their role (apps.command_center.home_priorities, 2026-10-24): they
    are drawn without the To-Do queue, whose figures follow in a request of
    their own (`build_home_todo_figures`, /home/todo-figures) — a Lead's
    queue reads the team's whole target page, seven seconds on a seeded
    database, and the rows waited for it. Every other role's Priority actions
    are the first entries of their To-Do queue, figures alongside."""
    from apps.command_center.home_priorities import role_priorities

    role_rows = role_priorities(user)
    has_plan = get_user_role_slug(user) in PLAN_ROLES
    if role_rows is not None:
        return {
            "queue_figures": [],
            "role_rows": role_rows,
            "priority_rows": role_rows,
            "priority_total": None,
            "has_plan": has_plan,
            "todo_figures_later": True,
        }
    from apps.command_center.todo_service import get_cached_todos

    queue = get_cached_todos(user)
    return {
        "queue_figures": todo_figures(queue.get("counts") or {}, with_plan=has_plan),
        "role_rows": None,
        "priority_rows": priority_actions(queue.get("todos") or []),
        "priority_total": queue.get("total", 0),
        "has_plan": has_plan,
        "todo_figures_later": False,
    }


def build_home_todo_figures(user) -> dict:
    """The To-Do figures and the To-Do count, from the reader's queue, for a
    role whose Priority actions do not come from it."""
    from apps.command_center.todo_service import get_cached_todos

    queue = get_cached_todos(user)
    has_plan = get_user_role_slug(user) in PLAN_ROLES
    return {
        "queue_figures": todo_figures(queue.get("counts") or {}, with_plan=has_plan),
        "priority_total": queue.get("total", 0),
        "role_rows": True,
    }
