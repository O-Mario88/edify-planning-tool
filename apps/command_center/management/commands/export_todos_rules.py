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

from apps.audit.management.commands.export_decision_log_rules import strip
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
    "/my-coaching?open={id}": "/my-coaching?open=cmw0000000000000000000001",
    "/priorities?guidance={id}": "/priorities?guidance=cmw0000000000000000000001",
    "/quality-checks": "/quality-checks",
    "/performance-conversation?staff={id}": (
        "/performance-conversation?staff=cmw0000000000000000000001"
    ),
    # Impact Assessment's queue (docs/migration/56).
    "/ia/verification/{id}/": "/ia/verification/cmw0000000000000000000001/",
    "/ia/partner-evidence/{id}/": "/ia/partner-evidence/cmw0000000000000000000001/",
    "/ia/dashboard/?view=collection": "/ia/dashboard/?view=collection",
    "/ia/dashboard/?view=collection&owner={id}": (
        "/ia/dashboard/?view=collection&owner=cmw0000000000000000000001"
    ),
    "/ia/dashboard/?view=collection&district={id}": (
        "/ia/dashboard/?view=collection&district=cmw0000000000000000000001"
    ),
    "/ssa/upload/history/?has_blocked=1": "/ssa/upload/history/?has_blocked=1",
    "/team-planning-oversight/?view=coverage": "/team-planning-oversight/?view=coverage",
    "/ia/framework/?tab=rules&status=required": (
        "/ia/framework/?tab=rules&status=required"
    ),
    "/country-budget": "/country-budget",
    "/country-budget/": "/country-budget/",
    "/dashboard": "/dashboard",
    "/budget": "/budget",
    "/disbursements": "/disbursements",
    "/cost-settings": "/cost-settings",
    "/cost-settings?fy={fy}": "/cost-settings?fy=2028",
    "/staff/{id}": "/staff/cmw0000000000000000000001",
    "/cce-leadership/reports": "/cce-leadership/reports",
    "/cce-leadership/engagements": "/cce-leadership/engagements",
    "/partner/assignments/{id}": "/partner/assignments/cmw0000000000000000000001",
    "/loans#loan-record-title": "/loans#loan-record-title",
    "/analytics/country-director/drilldown?drill=risk&issue=no_ssa&fy={fy}": (
        "/analytics/country-director/drilldown?drill=risk&issue=no_ssa&fy=2028"
    ),
    "/analytics/country-director/drilldown?drill=district_low_lship&fy={fy}": (
        "/analytics/country-director/drilldown?drill=district_low_lship&fy=2028"
    ),
    "/analytics/country-director/drilldown?drill=partner&fy={fy}": (
        "/analytics/country-director/drilldown?drill=partner&fy=2028"
    ),
    "/analytics/country-director/drilldown?drill=pl&fy={fy}": (
        "/analytics/country-director/drilldown?drill=pl&fy=2028"
    ),
    "/analytics/country-director/drilldown?drill=budget&fy={fy}": (
        "/analytics/country-director/drilldown?drill=budget&fy=2028"
    ),
    "/work-plan?view=fy": "/work-plan?view=fy",
    "/admin-panel/users#partner-directory-title": (
        "/admin-panel/users#partner-directory-title"
    ),
    "/projects/planning?project={id}": (
        "/projects/planning?project=cmw0000000000000000000001"
    ),
    "/loans?open={id}#loan-register-title": (
        "/loans?open=cmw0000000000000000000001#loan-register-title"
    ),
    "/business-transformation/impact-reports": (
        "/business-transformation/impact-reports"
    ),
    "/business-transformation": "/business-transformation",
    # Cutover native Go builders (internal/todos/cutover_builders.go).
    "/accounts/partner-payments": "/accounts/partner-payments",
    "/debriefs": "/debriefs",
    "/escalations": "/escalations",
    "/fund-approvals": "/fund-approvals",
    "/hr/policies": "/hr/policies",
    "/leave/approvals": "/leave/approvals",
    "/my-actions": "/my-actions",
    "/my-professional-development": "/my-professional-development",
    "/my-target": "/my-target",
    "/pl/review-queue": "/pl/review-queue",
    "/ssa/verification/": "/ssa/verification/",
    "/staff-activity": "/staff-activity",
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
            # The workspace strip the page shows the role (_section_nav).
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html"),
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
            na["description"],
            ts._act_priority(activity, na["action"], CASE_TODAY),
            status[0],
        ]
        cases.append("|".join(given) + " => " + "|".join(answer))
    return cases


def admin_rules() -> dict:
    """What the Admin's builders Go has read (todo_service's finance, budget,
    cost and loan desks, hr.hr_exceptions, partners.user_setup_todos)."""
    from apps.command_center import todo_service as ts
    from apps.core.rbac import EdifyRole
    from apps.hr import hr_exceptions
    from apps.partners.models import PartnerUserSetupStatus
    from apps.partners.services import may_manage_partner_users

    return {
        "accountant_queue_statuses": dict(ts.ACCOUNTANT_QUEUE_STATUSES),
        "country_budget": {
            "country": ts.COUNTRY_BUDGET_COUNTRY,
            "cd_roles": list(ts.COUNTRY_BUDGET_CD_ROLES),
            "rvp_roles": list(ts.COUNTRY_BUDGET_RVP_ROLES),
            "accountant_roles": list(ts.COUNTRY_BUDGET_ACCOUNTANT_ROLES),
            "review_statuses": list(ts.COUNTRY_BUDGET_REVIEW_STATUSES),
            "returned_status": ts.COUNTRY_BUDGET_RETURNED_STATUS,
            "submitted_status": ts.COUNTRY_BUDGET_SUBMITTED_STATUS,
            "approved_status": ts.COUNTRY_BUDGET_APPROVED_STATUS,
            "team_request_status": ts.COUNTRY_BUDGET_TEAM_REQUEST_STATUS,
        },
        "cost_catalogue_settled_statuses": list(ts.COST_CATALOGUE_SETTLED_STATUSES),
        "bt_verification_scheduling_roles": sorted(ts.BT_VERIFICATION_SCHEDULING_ROLES),
        "policy_awaiting_publication_statuses": list(
            hr_exceptions.POLICY_AWAITING_PUBLICATION_STATUSES
        ),
        "partner_user_setup_roles": sorted(
            role.value
            for role in EdifyRole
            if may_manage_partner_users(_role_user(role.value))
        ),
        "partner_user_setup_pending": PartnerUserSetupStatus.PENDING.value,
    }


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


def pc_bt_rules() -> dict:
    """What the Project Coordinator's and Business Transformation's builders
    Go has read (evidence_todos, fy_todos, portfolio_todos, the BT part of
    _business_transformation_todos, learning_todos)."""
    from apps.business_transformation import lending_impact as li
    from apps.business_transformation import services as bt_services
    from apps.business_transformation.models import (
        DISBURSED_LOAN_STATUSES,
        IAValidationStatus,
        LoanPurposeProposalStatus,
        LoanUseFinding,
        SalesforceStatus,
    )
    from apps.command_center import todo_service as ts
    from apps.impact import evidence_todos
    from apps.planning import fy_todos
    from apps.projects import portfolio, portfolio_todos
    from apps.projects.models import OPEN_PROJECT_STATUSES

    return {
        "evidence_field_roles": list(evidence_todos.FIELD_ROLES),
        "fy_planner_roles": list(fy_todos.PLANNER_ROLES),
        "open_project_statuses": sorted(s.value for s in OPEN_PROJECT_STATUSES),
        "project_row_limit": portfolio_todos.ROW_LIMIT,
        "project_scan_factor": portfolio.ENROLMENT_SCAN_FACTOR,
        "project_not_planned_statuses": list(portfolio.NOT_PLANNED_STATUSES),
        "bt_loan_roles": sorted(bt_services.UGANDA_WIDE_ROLES),
        "bt_impact_country_bound_roles": sorted(li.COUNTRY_BOUND_ROLES),
        "bt_impact_country_roles": sorted(li.COUNTRY_ROLES),
        "bt_salesforce_pending": SalesforceStatus.PENDING.value,
        "bt_repayment_risk_statuses": list(ts.BT_REPAYMENT_RISK_STATUSES),
        "bt_concern_findings": [
            v for v in LoanUseFinding.values if v != LoanUseFinding.FULLY_APPROVED
        ],
        "bt_purpose_requested": LoanPurposeProposalStatus.REQUESTED.value,
        "bt_eligible_school_statuses": list(ts.BT_ELIGIBLE_SCHOOL_STATUSES),
        "bt_disbursed_loan_statuses": [str(v) for v in DISBURSED_LOAN_STATUSES],
        "bt_ia_pending": IAValidationStatus.PENDING.value,
        "bt_ia_returned": IAValidationStatus.RETURNED.value,
        "bt_ia_verified": IAValidationStatus.VERIFIED.value,
        "bt_legacy_preparer": li.LEGACY_PREPARER,
    }


def rules() -> dict:
    from apps.activities.models import Activity, ActivityType
    from apps.business_transformation.models import (
        SalesforceStatus,
        VerificationRequirementStatus,
    )
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
    from apps.ssa import collection_todos

    return {
        "roles": roles(),
        "builders": builder_names(),
        "partner_scope_roles": [
            EdifyRole.PARTNER_ADMIN.value,
            EdifyRole.PARTNER_FIELD_OFFICER.value,
        ],
        "open_links": open_links(),
        "lead": lead_rules(),
        "admin": admin_rules(),
        "pc_bt": pc_bt_rules(),
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
        "partner_released_statuses": list(PartnerAssignment.RELEASED_STATUSES),
        "partner_intake_statuses": list(ts.PARTNER_INTAKE_STATUSES),
        "ssa_keying_roles": sorted(collection_todos.KEYING_ROLES),
        "salesforce_returned_status": SalesforceStatus.RETURNED.value,
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
        "ia": ia_rules(),
    }


def ia_rules() -> dict:
    """What Impact Assessment's own builders read (docs/migration/56)."""
    from apps.activities import ia_todos
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.activity_catalogue.models import MappingStatus
    from apps.analytics import ia_collection
    from apps.command_center import todo_service as ts
    from apps.impact import evidence_services as ev
    from apps.impact import framework_todos
    from apps.impact.models import DefinitionStatus
    from apps.planning import coverage_todos
    from apps.planning.country_oversight import rules as oversight
    from apps.schools import school_status
    from apps.ssa import collection_todos
    from apps.targets.models import MSCSStatus

    return {
        "waiting_status": ts.IA_TODO_WAITING_STATUS,
        "category": ts.IA_TODO_CATEGORY,
        "collection_category": collection_todos.CATEGORY,
        "collection_max_owner_rows": collection_todos.MAX_OWNER_ROWS,
        "collection_blocked_rows_days": collection_todos.BLOCKED_ROWS_DAYS,
        "collection_blocked_status": collection_todos.BLOCKED_ROW_STATUS,
        "collection_operating_statuses": list(
            ia_collection.COLLECTION_OPERATING_STATUSES
        ),
        "collection_open_statuses": list(ia_collection.OPEN_COLLECTION_STATUSES),
        "collection_delivered_statuses": list(ia_collection.DELIVERED_STATUSES),
        "collection_record_returned": ia_collection.RECORD_RETURNED,
        "collection_record_pending": ia_collection.RECORD_PENDING,
        "collection_record_confirmed": ia_collection.RECORD_CONFIRMED,
        "collection_partner": ia_collection.PARTNER,
        "coverage_roles": list(coverage_todos.RESPONSIBLE_ROLES),
        "coverage_url": coverage_todos.COVERAGE_URL,
        "coverage_session_types": sorted(school_status.CLUSTER_SESSION_TYPES),
        "coverage_dead_statuses": sorted(school_status.DEAD_STATUSES),
        "coverage_school_training_types": [str(t) for t in SCHOOL_TRAINING_TYPES],
        "coverage_trained_types": list(oversight.TRAINED_TYPES),
        "framework_category": framework_todos.CATEGORY,
        "framework_in_review": MappingStatus.IN_REVIEW.value,
        "framework_draft": MappingStatus.DRAFT.value,
        "definition_in_review": DefinitionStatus.IN_REVIEW.value,
        "definition_returned": DefinitionStatus.RETURNED.value,
        "evidence_pending": ev.PENDING,
        "story_submitted": MSCSStatus.SUBMITTED.value,
        "queue_ssa_pending": ia_todos.SSA_PENDING_STATUS,
        "queue_unmatched_open": list(ia_todos.UNMATCHED_OPEN_STATUSES),
        "queue_duplicate_open": ia_todos.DUPLICATE_OPEN_STATUS,
        "queue_sample_pending": ia_todos.SAMPLE_PENDING_STATUS,
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
