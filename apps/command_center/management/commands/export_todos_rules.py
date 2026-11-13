"""Write the To-Do page's rules for the Go gateway.

Go builds the To-Do page (/todos, apps.frontend.views.extended_views.todos_view,
apps.command_center.todo_service.get_todos, pages/todos/index.html and
partials/todos/row.html) from the vocabularies this command writes to
platform/backend/internal/todos/rules.json. A change to any of them must be
exported again; apps/command_center/test_todos_rules_export.py fails until it
is, so the two can never drift.

Nothing is restated:

* who may open the page is each role's answer from the page's own gates;
* the queue's builders are read from ``_get_todos`` itself (its ``todos +=``
  lines, in order) and ``MODULE_TODO_BUILDERS``, and which of them a role
  reaches is found by running each one as a principal of that role with the
  database replaced by a tripwire: a builder that reads anything for the role
  is reached, one that returns before reading is not. Go answers a reader only
  when it has every builder their role reaches, so a builder added here makes
  Go pass the role on rather than answer without it;
* each row's link is kept only where ``can_open_url`` lets the role in; the
  answers are asked of that function for every link shape Go builds;
* the next action of an activity (``compute_next_action``), its priority and
  status are written as a table of cases computed by those functions, which
  Go's own must reproduce;
* a row's icon tone is the row template rendered for each category and read
  by the app feed's own reader.

    python manage.py export_todos_rules
"""

from __future__ import annotations

import ast
import inspect
import itertools
import json
import random
import textwrap
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/todos/rules.json")
#: The next-action cases, which only Go's tests read.
CASES_PATH = Path("platform/backend/internal/todos/testdata/next_action_cases.json")

PAGE_PATH = "/todos"

#: The day the next-action cases are computed for; only its distance to each
#: case's planned date matters.
CASE_TODAY = date(2026, 11, 13)

#: Every link shape the builders Go answers can produce, with a sample of the
#: ids it carries. Go names the shape of each row it builds; can_open_url is
#: asked of the sample for every role.
LINK_SHAPES = {
    "/activities/{id}/complete": "/activities/cmw0000000000000000000001/complete",
    "/activities/{id}/start": "/activities/cmw0000000000000000000001/start",
    "/activities/{id}/evidence": "/activities/cmw0000000000000000000001/evidence",
    "/activities/{id}/salesforce-id": (
        "/activities/cmw0000000000000000000001/salesforce-id"
    ),
    "/activities/{id}/submit": "/activities/cmw0000000000000000000001/submit",
    "/partner/activities/{id}/evidence": (
        "/partner/activities/cmw0000000000000000000001/evidence"
    ),
    "/my-plan/{id}": "/my-plan/cmw0000000000000000000001",
    "/my-plan/{id}/confirm-reimbursement-receipt": (
        "/my-plan/cmw0000000000000000000001/confirm-reimbursement-receipt"
    ),
    "/my-plan/{id}/accountability": (
        "/my-plan/cmw0000000000000000000001/accountability"
    ),
    "/my-plan/{id}?learning_results=1": (
        "/my-plan/cmw0000000000000000000001?learning_results=1"
    ),
    "/planning/visit-requests": "/planning/visit-requests",
    "/fund-requests/weekly/{id}": "/fund-requests/weekly/cmw0000000000000000000001",
    "/fund-requests/weekly": "/fund-requests/weekly",
    "/schools": "/schools",
    "/clusters": "/clusters",
    "/planning": "/planning",
    "/my-plan": "/my-plan",
    "/core-schools": "/core-schools",
    "/extra-work": "/extra-work",
    "/partner-oversight/?partner={id}&status=returned": (
        "/partner-oversight/?partner=cmw0000000000000000000001&status=returned"
    ),
    "/schools/{id}": "/schools/cmw0000000000000000000001",
    "/schools/{code}#school-bt-title": "/schools/1000#school-bt-title",
    "/ssa/verification/?status=returned&mine=1": (
        "/ssa/verification/?status=returned&mine=1"
    ),
    "/clusters/{id}/profile?tab=attendance&show=missing": (
        "/clusters/cmw0000000000000000000001/profile?tab=attendance&show=missing"
    ),
    "/team/coaching?open=new&cceo={id}&kind=one_to_one": (
        "/team/coaching?open=new&cceo=cmw0000000000000000000001&kind=one_to_one"
    ),
    "/performance-conversation?staff={id}": (
        "/performance-conversation?staff=cmw0000000000000000000001"
    ),
}

#: The categories the row template draws an icon for; any other category is
#: drawn as the last one here.
ICON_CATEGORIES = (
    "Evidence",
    "Finance",
    "Budget Approval",
    "IA Verification",
    "SSA",
    "Leave",
    "Approval",
    "Data Quality",
    "Planning",
    "",
)


class _Reached(BaseException):
    """Raised by the tripwire the first time a builder reads the database.
    A BaseException, so a builder's own ``except Exception`` cannot hide it."""


def queue_builders() -> list[tuple[str, list[str]]]:
    """``_get_todos``'s builders in order, each with the names it is given."""
    from apps.command_center import todo_service

    source = textwrap.dedent(inspect.getsource(todo_service._get_todos))
    out: list[tuple[str, list[str]]] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            out.append((node.value.func.id, [a.id for a in node.value.args]))
    # ast.walk is breadth-first; the += lines sit at one depth, in order.
    return out


def builder_names() -> list[str]:
    """Every builder of the queue, in the order the queue adds their rows."""
    from apps.command_center import todo_service

    names: list[str] = []
    for name, _args in queue_builders():
        if name == "_module_todos":
            names += list(todo_service.MODULE_TODO_BUILDERS)
        else:
            names.append(name)
    return names


def _probe_principal(role: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="probe-user",
        pk="probe-user",
        user_id="probe-user",
        staff_profile_id="probe-staff",
        active_role=role,
        roles=[role],
        is_authenticated=True,
        is_superuser=False,
        country="Uganda",
        name="Probe",
        email="probe@example.org",
    )


def _probe_scope(role: str) -> SimpleNamespace:
    from apps.core.rbac import EdifyRole

    # resolve_user_scope resolves partner ids for the two partner roles only.
    partner = role in (
        EdifyRole.PARTNER_ADMIN.value,
        EdifyRole.PARTNER_FIELD_OFFICER.value,
    )
    return SimpleNamespace(
        staff_ids=["probe-staff"],
        partner_ids=["probe-partner"] if partner else [],
        own_school_ids=["probe-school"],
        school_ids=["probe-school"],
        active_role=role,
    )


def reached_builders(role: str) -> list[str]:
    """The builders that read anything for a principal of ``role``."""
    from django.db import connections

    from apps.command_center import todo_service

    def tripwire(*_args, **_kwargs):
        raise _Reached()

    principal, scope = _probe_principal(role), _probe_scope(role)
    given = {
        "principal": principal,
        "scope": scope,
        "today": CASE_TODAY,
        "fy": "2027",
        "role": role,
    }
    calls: list[tuple[str, object, list]] = []
    for name, args in queue_builders():
        if name == "_module_todos":
            for path in todo_service.MODULE_TODO_BUILDERS:
                module_name, _, attr = path.partition(":")
                builder = getattr(import_module(module_name), attr)
                calls.append((path, builder, [principal, role, CASE_TODAY]))
        else:
            calls.append((name, getattr(todo_service, name), [given[a] for a in args]))
    connection = connections["default"]
    saved = (connection.cursor, connection.chunked_cursor)
    reached: list[str] = []
    connection.cursor = connection.chunked_cursor = tripwire
    try:
        for name, builder, args in calls:
            try:
                builder(*args)
            except _Reached:
                reached.append(name)
            except Exception:  # noqa: BLE001 - a builder that fails reads nothing
                pass
    finally:
        connection.cursor, connection.chunked_cursor = saved
    return reached


def roles() -> dict:
    """Each role's door to the page and the builders its queue runs."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("todos") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "todos")
            and bool(can_open_url(user, PAGE_PATH)),
            "builders": reached_builders(role.value),
        }
    return out


def open_links() -> dict:
    """can_open_url's answer for each link shape, role by role."""
    from apps.core.permissions import can_open_url
    from apps.core.rbac import EdifyRole

    return {
        shape: {
            role.value: bool(can_open_url(_role_user(role.value), sample))
            for role in EdifyRole
        }
        for shape, sample in LINK_SHAPES.items()
    }


def category_tones() -> dict:
    """The tone the app feed reads from a row's icon, by category."""
    from django.template.loader import render_to_string

    from apps.mobile_feed.page_blocks import _list_item, parse

    out = {}
    for category in ICON_CATEGORIES:
        html = render_to_string(
            "partials/todos/row.html",
            {
                "t": {
                    "title": "T",
                    "linked": "L",
                    "category": category or "Something else",
                    "priority": "low",
                    "priority_label": "Low",
                    "action_label": "Open",
                    "action_url": "/x",
                    "actionable": True,
                }
            },
        )
        row = next(n for n in parse(html).children if not isinstance(n, str))
        out[category] = _list_item(row)["tone"]
    return out


def _activity_case(values: dict, today: date) -> SimpleNamespace:
    planned = {
        "none": None,
        "past": today - timedelta(days=3),
        "today": today,
        "future": today + timedelta(days=4),
    }[values["planned"]]
    school = (
        None
        if values["school"] == "none"
        else SimpleNamespace(current_fy_ssa_status=values["school"])
    )
    return SimpleNamespace(
        id="ACT",
        status=values["status"],
        delivery_type=values["delivery"],
        evidence_status=values["evidence"],
        planned_date=planned,
        salesforce_activity_id=values["sf"],
        activity_type=values["type"],
        teachers_attended=values["teachers"],
        leaders_attended=values["leaders"],
        school=school,
        ia_verification_status=values["ia"],
        payment_status=values["payment"],
    )


def _advances(kinds: list[str]) -> list[SimpleNamespace]:
    out = []
    for kind in kinds:
        status, _, flag = kind.partition("+")
        out.append(
            SimpleNamespace(
                status=status,
                reimbursement_receipt_confirmed_at="x" if flag == "receipt" else None,
                accountability_netsuite_id="NS" if flag == "netsuite" else None,
            )
        )
    return out


#: The order of a next-action case's fields: ``given => answer``, each side
#: joined by "|", the advances by "+", the answer being the next action's
#: text, action and link, the row's priority and its status.
CASE_FIELDS = (
    "status",
    "delivery",
    "evidence",
    "planned",
    "sf",
    "type",
    "teachers",
    "leaders",
    "school",
    "ia",
    "payment",
    "advances",
)


def next_action_cases() -> list[str]:
    """compute_next_action, _act_priority and _act_status over a grid of
    activities: every status against every delivery, evidence, date and ID
    state, and a fixed random sample over everything else."""
    from apps.activities.models import Activity
    from apps.command_center import todo_service as ts
    from apps.my_plan.services import compute_next_action

    statuses = [v for v, _ in Activity._meta.get_field("status").choices]
    statuses += ["awaiting_owner_approval", "completion_started", "unknown_status"]
    statuses = sorted(set(statuses))
    evidence = sorted(
        {v for v, _ in Activity._meta.get_field("evidence_status").choices} | {"x"}
    )
    ia = sorted(
        {v for v, _ in Activity._meta.get_field("ia_verification_status").choices}
    )
    payment = sorted({v for v, _ in Activity._meta.get_field("payment_status").choices})
    types = [
        "school_visit",
        "training",
        "cluster_meeting",
        "core_training",
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "cluster_training_ssa_collection",
    ]
    advance_kinds = [
        "reimbursement_disbursed",
        "reimbursement_disbursed+receipt",
        "disbursed",
        "disbursed+netsuite",
        "accountability_pending",
        "accountability_pl_pending",
        "reimbursement_pl_pending",
        "reimbursement_submitted",
        "pending_responsible_confirmation",
    ]
    base = {
        "status": "scheduled",
        "delivery": "staff",
        "evidence": "none",
        "planned": "future",
        "sf": "",
        "type": "school_visit",
        "teachers": 0,
        "leaders": 0,
        "school": "not_done",
        "ia": "pending",
        "payment": "none",
        "advances": [],
    }
    grid = []
    for status, delivery, ev, planned, sf in itertools.product(
        statuses,
        ["staff", "partner"],
        evidence,
        ["none", "past", "today", "future"],
        ["", "SF1"],
    ):
        grid.append(
            {**base, "status": status, "delivery": delivery, "evidence": ev,
             "planned": planned, "sf": sf}
        )  # fmt: skip
    rng = random.Random(20261113)  # noqa: S311 - a fixed sample, not a secret
    for _ in range(1500):
        grid.append(
            {
                "status": rng.choice(statuses),
                "delivery": rng.choice(["staff", "partner"]),
                "evidence": rng.choice(evidence),
                "planned": rng.choice(["none", "past", "today", "future"]),
                "sf": rng.choice(["", "SF1"]),
                "type": rng.choice(types),
                "teachers": rng.choice([0, 0, 2]),
                "leaders": rng.choice([0, 1]),
                "school": rng.choice(["none", "done", "not_done"]),
                "ia": rng.choice(ia),
                "payment": rng.choice(payment),
                "advances": rng.sample(advance_kinds, rng.choice([0, 0, 1, 2, 3])),
            }
        )
    cases = []
    for values in grid:
        activity = _activity_case(values, CASE_TODAY)
        na = compute_next_action(
            activity, CASE_TODAY, advances=_advances(values["advances"])
        )
        status = ts._act_status(activity, na["action"], CASE_TODAY)
        given = [str(values[k]) for k in CASE_FIELDS[:-1]]
        given.append("+".join(values["advances"]))
        answer = [
            na["text"],
            na["action"],
            na["url"],
            ts._act_priority(activity, na["action"], CASE_TODAY),
            status[0],
        ]
        cases.append("|".join(given) + " => " + "|".join(answer))
    return cases


def lead_rules() -> dict:
    """What the Programme Lead's builders Go has read (todo_service,
    cce_leadership.todos, hr.review_todos, pl_review, analytics, targets)."""
    from apps.analytics import pl_analytics_service as analytics
    from apps.cce_leadership import coaching
    from apps.cce_leadership import todos as coaching_todos
    from apps.command_center import todo_service as ts
    from apps.hr import performance_engine as perf
    from apps.hr import review_todos
    from apps.cce_leadership.models import CoachingKind
    from apps.hr.models import ReviewStage
    from apps.hr.review_authority import REVIEWER_ROLE_FOR
    from apps.pl_review.services import LEAD_REVIEWABLE_STATUSES
    from apps.ssa.services import VerificationStatus
    from apps.targets import team_targets

    return {
        "reviewer_roles": {
            reviewee: list(reviewers)
            for reviewee, reviewers in REVIEWER_ROLE_FOR.items()
        },
        "review_category": review_todos.CATEGORY,
        "review_stage_manager_review": ReviewStage.PRIORITIES_MANAGER_REVIEW.value,
        "review_stages_before_conversation": [
            ReviewStage.NOT_STARTED.value,
            ReviewStage.PRIORITIES_DRAFT.value,
            ReviewStage.PRIORITIES_MANAGER_REVIEW.value,
        ],
        "review_done_stages": list(perf.REVIEW_DONE_STAGES),
        "review_closed_statuses": list(perf.REVIEW_CLOSED_STATUSES),
        "conversation_windows": list(perf.CONVERSATION_WINDOWS),
        "coaching_category": coaching_todos.LEAD_CATEGORY,
        "coaching_row_limit": coaching_todos.ROW_LIMIT,
        "one_to_one_kind": CoachingKind.ONE_TO_ONE.value,
        "one_to_one_due_day": coaching.ONE_TO_ONE_DUE_DAY,
        "lead_reviewable_statuses": list(LEAD_REVIEWABLE_STATUSES),
        "advance_approver_pending_statuses": list(ts.ADVANCE_APPROVER_PENDING_STATUSES),
        "cceo_backlog_statuses": list(analytics.CCEO_BACKLOG_STATUSES),
        "ssa_pending_status": VerificationStatus.PENDING.value,
        "analytics_completed_statuses": list(analytics.COMPLETED_STATUSES),
        "team_targets_completed_statuses": list(team_targets.COMPLETED_STATUSES),
    }


def rules() -> dict:
    from apps.activities.models import Activity, ActivityType
    from apps.business_transformation.models import VerificationRequirementStatus
    from apps.clusters import followups, profile_insights
    from apps.command_center import todo_groups
    from apps.command_center import todo_service as ts
    from apps.core.rbac import EdifyRole
    from apps.hr.models import ExtraAssignment, ReviewStage, ReviewType
    from apps.impact import evidence_services as ev
    from apps.partners.models import PartnerAssignment
    from apps.planning import school_planning_badges as badges
    from apps.planning import visit_requests
    from apps.planning.action_models import ACTIVE_STATES
    from apps.planning.fy_policy import default_country
    from apps.projects.ssa_impact import Impact
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "roles": roles(),
        "builders": builder_names(),
        "partner_scope_roles": [
            EdifyRole.PARTNER_ADMIN.value,
            EdifyRole.PARTNER_FIELD_OFFICER.value,
        ],
        "open_links": open_links(),
        "lead": lead_rules(),
        "category_tones": category_tones(),
        "priority_order": dict(ts.PRIORITY_ORDER),
        "priority_label": dict(ts.PRIORITY_LABEL),
        "actionable": sorted(ts.ACTIONABLE),
        "waiting": sorted(ts.WAITING),
        "action_meta": {k: list(v) for k, v in ts.ACTION_META.items()},
        "group_min": todo_groups.GROUP_MIN,
        "activity_type_labels": dict(ActivityType.choices),
        "activity_field_choices": {
            field: sorted(v for v, _ in Activity._meta.get_field(field).choices)
            for field in ("status", "evidence_status")
        },
        "activity_settled_statuses": list(ts.ACTIVITY_TODO_SETTLED_STATUSES),
        "weekly_confirm_status": ts.WEEKLY_CONFIRM_STATUS,
        "weekly_returned_statuses": list(ts.WEEKLY_RETURNED_STATUSES),
        "weekly_approver_status": dict(ts.WEEKLY_APPROVER_STATUS),
        "monthly_returned_statuses": list(ts.MONTHLY_RETURNED_STATUSES),
        "partner_delay_settled_statuses": list(ts.PARTNER_DELAY_SETTLED_STATUSES),
        "returned_to_staff_status": PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        "team_action_active_states": sorted(str(s) for s in ACTIVE_STATES),
        "visit_request_awaiting": visit_requests.AWAITING,
        "core_done_statuses": sorted(ts._CORE_DONE_STATUSES),
        "core_in_flight_statuses": sorted(ts._CORE_IN_FLIGHT_STATUSES),
        "core_returned_statuses": sorted(ts._CORE_RETURNED_STATUSES),
        "core_kinds": [list(k) for k in ts._CORE_KINDS],
        "loan_field_verification_statuses": [
            VerificationRequirementStatus.NEEDS_SCHEDULING.value,
            VerificationRequirementStatus.OVERDUE.value,
        ],
        "operating_statuses": list(OPERATING_STATUSES),
        "extra_open_statuses": list(ExtraAssignment.OPEN_STATUSES),
        "project_not_yet_measurable": Impact.NOT_YET_MEASURABLE,
        "evidence_tables": sorted(m._meta.db_table for m in ev.MODELS.values()),
        "evidence_returned": ev.RETURNED,
        "onetest_delivered_statuses": list(ev.DELIVERED_STATUSES),
        "cluster_session_types": list(badges.CLUSTER_SESSION_TYPES),
        "cluster_delivered_statuses": sorted(
            badges.AWAITING_VERIFICATION_STATUSES | badges.VERIFIED_STATUSES
        ),
        "missed_in_a_row_alert": profile_insights.MISSED_IN_A_ROW_ALERT,
        "attendance_max_rows": followups.MAX_ROWS,
        "planning_country": default_country(),
        "target_review_type": ReviewType.ANNUAL_PRIORITIES.value,
        "target_review_stages_not_agreed": [
            ReviewStage.NOT_STARTED.value,
            ReviewStage.PRIORITIES_DRAFT.value,
            ReviewStage.PRIORITIES_MANAGER_REVIEW.value,
        ],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def rendered_cases() -> str:
    return (
        json.dumps(
            {"fields": list(CASE_FIELDS), "cases": next_action_cases()},
            indent=0,
            ensure_ascii=False,
        )
        + "\n"
    )


class Command(BaseCommand):
    help = "Write the To-Do page's rules to platform/backend/internal/todos/rules.json"

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
        CASES_PATH.write_text(rendered_cases(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH} and {CASES_PATH}")
