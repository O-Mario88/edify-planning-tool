"""Metric definitions for Home's overview figures (owner, 2026-10-21).

Home (templates/pages/home/index.html) is the phone's first tab and the
native app's start page. Its figures are built by
``apps.command_center.home_service`` through ``render_precomputed_metric_item``
and computed by the services that own them: the reader's own My Plan in the
operational financial year (``apps.my_plan.services.my_plan_activities`` split
by ``plan_state_q``) and the reader's To-Do queue
(``apps.command_center.todo_service.get_cached_todos``). Each plan figure opens
the My Plan list of exactly the activities it counts.
"""

from __future__ import annotations

_SOURCE = "apps.command_center.home_service:build_home"
_LOCATION = "apps/command_center/home_service.py"
_PLAN_ROLES = ("CCEO", "Program Lead", "PartnerFieldOfficer")
_ALL_ROLES = ("CCEO", "Program Lead", "CountryDirector", "Admin", "ImpactAssessment")
_PLAN_SCOPE = (
    "The reader's own My Plan in the operational financial year: work they own "
    "and deliver (a partner's: work assigned to its organisation), never their "
    "supervisees'"
)
_QUEUE_SCOPE = "The reader's own To-Do queue, limited to pages their role may open"
_PLAN_SERVICE = "apps.my_plan.services.my_plan_activities"
_QUEUE_SERVICE = "apps.command_center.todo_service.get_cached_todos"


def _row(
    key: str,
    label: str,
    *,
    line: int,
    definition: str,
    question: str,
    numerator: str,
    service: str,
    scope: str,
    roles: tuple[str, ...],
    drilldown: str,
    category: str,
    period: str,
    date_basis: str,
) -> dict:
    return {
        "key": key,
        # The registry's labels are unique; the tile shows `source_label`.
        "label": f"{label} — Home",
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": "count",
        "service": service,
        "source_models": ("apps.activities.models.Activity",),
        "numerator": numerator,
        "denominator": None,
        "date_basis": date_basis,
        "period": period,
        "scope": scope,
        "owner_page": "home",
        "filter_behaviour": "fixed_context",
        "drilldown": drilldown,
        "notes": "Home overview, added 2026-10-21.",
        "roles": roles,
        "source_location": f"{_LOCATION}:{line}",
    }


def _plan(key, label, *, line, definition, question, numerator, drilldown, category):
    return _row(
        key,
        label,
        line=line,
        definition=definition,
        question=question,
        numerator=numerator,
        service=_PLAN_SERVICE,
        scope=_PLAN_SCOPE,
        roles=_PLAN_ROLES,
        drilldown=drilldown,
        category=category,
        period="financial_year",
        date_basis="activity_planned_date",
    )


def _queue(key, label, *, line, definition, question, numerator, category):
    return _row(
        key,
        label,
        line=line,
        definition=definition,
        question=question,
        numerator=numerator,
        service=_QUEUE_SERVICE,
        scope=_QUEUE_SCOPE,
        roles=_ALL_ROLES,
        drilldown="/todos",
        category=category,
        period="point_in_time",
        date_basis="not_time_bound",
    )


# `line` is where home_service builds the figure (PLAN_FIGURES / QUEUE_FIGURES).
HOME_METRIC_ROWS: tuple[dict, ...] = (
    _plan(
        "home_plan_upcoming",
        "Planned",
        line=113,
        definition=(
            "Activities on your own plan this financial year that have not been "
            "started and whose day is still ahead."
        ),
        question="How much of my plan is still ahead of me?",
        numerator="not-started statuses with the planned day today or later",
        drilldown="/my-plan?status=upcoming",
        category="scale",
    ),
    _plan(
        "home_plan_under_way",
        "In progress",
        line=114,
        definition=(
            "Activities on your own plan this financial year that have been "
            "started and are not yet verified: under way, evidence in, or with "
            "a reviewer."
        ),
        question="What have I started that is not finished yet?",
        numerator="under-way statuses (apps.core.activity_types)",
        drilldown="/my-plan?status=under_way",
        category="progress",
    ),
    _plan(
        "home_plan_overdue",
        "Overdue",
        line=115,
        definition=(
            "Activities on your own plan this financial year that were not "
            "started and whose day has passed."
        ),
        question="What did I plan that I have not done?",
        numerator="not-started statuses with the planned day before today",
        drilldown="/my-plan?status=overdue",
        category="risk",
    ),
    _queue(
        "home_todo_waiting",
        "To-Do",
        line=121,
        definition="Open To-Dos whose next step is yours.",
        question="How many actions are waiting on me?",
        numerator="actionable To-Dos not blocked on someone else",
        category="pending_action",
    ),
    _queue(
        "home_todo_due_today",
        "Due today",
        line=122,
        definition="Open To-Dos due today.",
        question="What must I finish today?",
        numerator="To-Dos whose due day is today",
        category="pending_action",
    ),
    _queue(
        "home_todo_critical",
        "Critical",
        line=123,
        definition="Open To-Dos at the highest priority, such as money already out.",
        question="What is most urgent?",
        numerator="To-Dos at critical priority",
        category="risk",
    ),
)
