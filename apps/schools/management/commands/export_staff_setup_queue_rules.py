"""Write the Staff Setup Queue's rules for the Go gateway.

Go builds the Staff Setup Queue (/admin-panel/staff-setup-queue,
apps.frontend.views.extended_views.admin_staff_setup_queue_view and
pages/admin/staff_setup_queue.html) from what this command writes to
platform/backend/internal/staffsetup/rules.json: which roles may open it,
which may open a school's and a district's profile (so a name is a link),
the school statuses that still need an owner, the operating statuses
(`active_schools`), the table's page size, and the query keys the feed
never passes. A change to any of them must be exported again;
apps/schools/test_staff_setup_queue_rules_export.py fails until it is.

    python manage.py export_staff_setup_queue_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/staffsetup/rules.json")

PERMISSION = "staff_setup_queue"
PATH = "/admin-panel/staff-setup-queue"

#: The owner statuses the queue lists (the view's filter).
PENDING_STATUSES = ["pending", "unmatched"]


def _roles(test) -> list[str]:
    from apps.core.rbac import EdifyRole

    return sorted(role.value for role in EdifyRole if test(_role_user(role.value)))


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.mobile_feed.views import NOT_PASSED
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "page_roles": _roles(
            lambda u: RolePermissionService.can_view_page(u, PERMISSION)
            and bool(can_open_url(u, PATH))
        ),
        "school_profile_roles": _roles(lambda u: bool(can_open_url(u, "/schools/0"))),
        "district_profile_roles": _roles(
            lambda u: bool(can_open_url(u, "/districts/0"))
        ),
        "pending_statuses": PENDING_STATUSES,
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Staff Setup Queue's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
