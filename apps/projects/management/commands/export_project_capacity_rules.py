"""Write the Project Capacity page's rules for the Go gateway.

Go builds Project Capacity (/projects/capacity,
apps.frontend.views.project_capacity_views.project_capacity_view,
apps.projects.capacity and pages/projects/capacity.html) from what this
command writes to platform/backend/internal/projectcapacity/rules.json: for
each role, whether it may open the page, the workspace strip it is shown and
whether a staff member's name opens their profile; the project statuses the
page lists and those that still take new schools; the share of an
allocation that reads "Near capacity"; the staff table's page size; and the
query keys the feed never passes. A change to any of them must be exported
again; apps/projects/test_project_capacity_rules_export.py fails until it is.

The doors and the strip are not restated: each role's answer is computed
here by the gates the page asks (`require_page_permission`, the feed's
`can_open_url`, `staff_link`'s own question) and the strip is the page's
section nav rendered for that role and read by the feed's own reader.

    python manage.py export_project_capacity_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/projectcapacity/rules.json")

PERMISSION = "project_capacity"
PATH = "/projects/capacity"


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed.views import NOT_PASSED
    from apps.projects.capacity import NEAR_CAPACITY_SHARE
    from apps.projects.models import LIVE_PROJECT_STATUSES, OPEN_PROJECT_STATUSES

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        roles[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "staff_links": bool(can_open_url(user, "/staff/0")),
        }
    return {
        "roles": roles,
        "live_statuses": sorted(str(s.value) for s in LIVE_PROJECT_STATUSES),
        "open_statuses": sorted(str(s.value) for s in OPEN_PROJECT_STATUSES),
        "near_capacity_share": NEAR_CAPACITY_SHARE,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Project Capacity page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
