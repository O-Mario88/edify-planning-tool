"""Write the platform-operations registers' rules for the Go gateway.

Go builds Support Tickets (/admin-ops/support), System Incidents
(/admin-ops/incidents), the Maintenance Calendar (/admin-ops/maintenance) and
the Data Repair Center (/data-repair)
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
}

#: The views' `_admin_only` guard: the role in use must be this one.
ADMIN_ROLE = "Admin"

#: tickets[:200], incidents[:200] and the maintenance work's [:50].
LIMITS = {"tickets": 200, "incidents": 200, "maintenance_work": 50}

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
