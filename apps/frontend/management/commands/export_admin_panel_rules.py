"""Write the Admin Panel pages' rules for the Go gateway.

Go builds the Admin Panel's pages (apps.frontend.views.extended_views:
admin_workflow_rules_view, admin_school_upload_history_view and the others
listed in PAGES) as the existing
feed reads them, from what this command writes to
platform/backend/internal/adminpanel/rules.json: for each page, which roles
may open it (its page permission and the feed's door); the workflow rules
the reference page lists; and what the Admin Dashboard's missing cost lines
count leaves out (system_health.services.missing_cost_lines_count). A change to any of them must be exported
again; apps/frontend/test_admin_panel_rules_export.py fails until it is.

    python manage.py export_admin_panel_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/adminpanel/rules.json")

#: Each page Go answers and its page permission.
PAGES = {
    "/admin-panel/workflow-rules": "workflow_rules",
    "/admin-panel/school-upload-history": "upload_history",
    "/admin-panel": "admin_dashboard",
    "/admin-panel/audit-log": "audit_log",
    "/admin-panel/region-district-setup": "region_district_setup",
    "/admin-panel/notifications-mgmt": "notifications_mgmt",
}


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.extended_views import WORKFLOW_RULES

    return {
        "pages": {
            path: sorted(
                role.value
                for role in EdifyRole
                if RolePermissionService.can_view_page(
                    _role_user(role.value), permission
                )
                and can_open_url(_role_user(role.value), path)
            )
            for path, permission in PAGES.items()
        },
        "workflow_rules": [[r["key"], r["label"]] for r in WORKFLOW_RULES],
        "missing_lines": missing_lines(),
        # Who may open a district's profile (school_links.district_link).
        "district_profile_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open_url(_role_user(role.value), "/districts/0")
        ),
    }


def missing_lines() -> dict:
    from apps.activities.online_training import ONLINE, ONLINE_TRAINING_TYPES
    from apps.activities.pair_costing import (
        COMPANION_GONE_STATUSES,
        REPRICEABLE_PAIR_STATUSES,
    )
    from apps.system_health.services import MISSING_LINE_EXEMPT_STATUSES

    return {
        "exempt_statuses": list(MISSING_LINE_EXEMPT_STATUSES),
        # UNCOSTED_PAIR_TRAINING and DELIVERED_PAIR_TRAINING: an in-school
        # training paired with a live visit, or a delivered pair.
        "companion_gone_statuses": list(COMPANION_GONE_STATUSES),
        "repriceable_pair_statuses": list(REPRICEABLE_PAIR_STATUSES),
        # ONLINE_TRAINING.
        "online_training_types": sorted(ONLINE_TRAINING_TYPES),
        "online_mode": ONLINE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Admin Panel pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
