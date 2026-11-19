"""Write the platform-operations registers' rules for the Go gateway.

Go builds Support Tickets (/admin-ops/support), System Incidents
(/admin-ops/incidents), the Maintenance Calendar (/admin-ops/maintenance) and
the Data Repair Center (/data-repair), Admin My Plan (/admin-ops/my-plan)
and Admin Planning (/admin-ops/planning)
(apps.admin_ops.views and pages/admin_ops/) from what this command writes to
platform/backend/internal/adminops/rules.json: for each page, who may open it
(the page permission, the feed's door and the views' Admin-only guard); the
labels of a ticket's status and category, an incident's status and severity, a work
item's status and category; the ticket statuses that are no longer open
work; how many rows each register lists; and the Data Repair Center's catalogue. A change to any of them must be
exported again; apps/admin_ops/test_admin_ops_rules_export.py fails until it
is.

    python manage.py export_admin_ops_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/adminops/rules.json")

#: The registers Go answers and their page permission.
PAGES = {
    "/admin-ops/support": "admin_support_queue",
    "/admin-ops/incidents": "admin_incidents",
    "/admin-ops/maintenance": "admin_maintenance",
    "/data-repair": "data_repair",
    "/admin-ops/my-plan": "admin_my_plan",
    "/admin-ops/planning": "admin_planning",
}

#: The views' `_admin_only` guard: the role in use must be this one.
ADMIN_ROLE = "Admin"

#: tickets[:200], incidents[:200] and the maintenance work's [:50].
LIMITS = {"tickets": 200, "incidents": 200, "maintenance_work": 50}

#: AdminMyPlanService.context: the statuses its sections list, and the newest
#: closed work it shows (recently_done[:8]).
MY_PLAN_STATUSES = ["scheduled", "in_progress", "waiting", "monitoring"]
RECENTLY_DONE = 8

#: AdminPlanningService.context: open incidents and untriaged tickets, the
#: newest 50 of each.
PLANNING_LIMIT = 50

#: Team Plans (apps.admin_ops.team_plans): read by Admin and Impact Assessment
#: (team_plans_view's own guard), not the Admin alone.
TEAM_PLANS_PATH = "/admin-ops/team-plans"
REPORT_PATH = "/support"
TEAM_PLANS_PERMISSION = "admin_team_plans"
TEAM_PLANS_ROLES = ("Admin", "ImpactAssessment")

#: The work item categories the Maintenance Calendar lists as open work.
MAINTENANCE_CATEGORIES = ["preventive_maintenance", "corrective_maintenance"]


def rules() -> dict:
    from apps.admin_ops.models import (
        IncidentStatus,
        Severity,
        TicketCategory,
        TicketStatus,
        WorkItemCategory,
        WorkItemStatus,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    pages = {}
    for path, permission in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            roles[role.value] = {
                "page": role.value == ADMIN_ROLE
                and RolePermissionService.can_view_page(user, permission)
                and bool(can_open_url(user, path)),
            }
        pages[path] = {"roles": roles}
    return {
        "pages": pages,
        "ticket_statuses": dict(TicketStatus.choices),
        "ticket_categories": dict(TicketCategory.choices),
        # Report a Problem (/support, report_problem_view): every role that
        # opens it, and its categories in their order.
        "report_roles": [
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), "report_problem"
            )
            and can_open_url(_role_user(role.value), REPORT_PATH)
        ],
        "ticket_category_choices": [
            [v, str(label)] for v, label in TicketCategory.choices
        ],
        # support_queue_view's "Open tickets": every ticket but these.
        "closed_ticket_statuses": sorted(
            str(s)
            for s in (
                TicketStatus.CLOSED,
                TicketStatus.RESOLVED,
                TicketStatus.INVALID,
                TicketStatus.CANCELLED,
                TicketStatus.DUPLICATE,
            )
        ),
        # A ticket whose row offers the resolve form.
        "resolvable_ticket_statuses": sorted(
            str(s) for s in (TicketStatus.VERIFICATION, TicketStatus.FIX_READY)
        ),
        "untriaged_ticket_status": str(TicketStatus.SUBMITTED),
        "incident_statuses": dict(IncidentStatus.choices),
        "severities": dict(Severity.choices),
        "work_item_statuses": dict(WorkItemStatus.choices),
        "work_item_categories": dict(WorkItemCategory.choices),
        "done_work_item_status": str(WorkItemStatus.DONE),
        "maintenance_categories": MAINTENANCE_CATEGORIES,
        "limits": LIMITS,
        "repairs": repairs(),
        # Admin My Plan and Admin Planning.
        "severity_choices": [[v, str(label)] for v, label in Severity.choices],
        "my_plan_statuses": MY_PLAN_STATUSES,
        "recently_done": RECENTLY_DONE,
        "planning_limit": PLANNING_LIMIT,
        "backlog_status": str(WorkItemStatus.BACKLOG),
        "monitoring_status": str(WorkItemStatus.MONITORING),
        "closed_incident_statuses": sorted(
            str(s) for s in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED)
        ),
        "table_page_size": TABLE_PAGE_SIZE,
        "team_plans": team_plans(),
    }


def team_plans() -> dict:
    """Team Plans: who may open it, the statuses its plan leaves out, how many
    rows it reads (PAGE_SIZE * 5) and shows (PAGE_SIZE), and the activity
    labels."""
    from apps.activities.models import ActivityType
    from apps.admin_ops import team_plans as tp
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    return {
        "roles": sorted(
            role.value
            for role in EdifyRole
            if role.value in TEAM_PLANS_ROLES
            and RolePermissionService.can_view_page(
                _role_user(role.value), TEAM_PLANS_PERMISSION
            )
            and bool(can_open_url(_role_user(role.value), TEAM_PLANS_PATH))
        ),
        "terminal_statuses": list(tp._TERMINAL),
        "page_size": tp.PAGE_SIZE,
        "read_limit": tp.PAGE_SIZE * 5,
        "activity_types": {k: str(v) for k, v in ActivityType.choices},
    }


def repairs() -> list[dict]:
    """The Data Repair Center's catalogue (apps.admin_ops.repair.REPAIRS):
    each repair's key, words, and whether it applies itself or is referred.
    How many records each affects is drawn beside it but not read by the
    feed."""
    from apps.admin_ops.repair import REPAIRS

    return [
        {
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "outcome": spec.outcome,
            "automatic": spec.automatic,
            "referral": spec.referral,
        }
        for spec in REPAIRS.values()
    ]


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the platform-operations registers' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
