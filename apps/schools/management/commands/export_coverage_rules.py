"""Write the Coverage page's rules for the Go gateway.

Go builds Coverage (/coverage, apps.frontend.views.extended_views
.coverage_view and pages/coverage/index.html) from what this command writes
to platform/backend/internal/coverage/rules.json: who may open the page and
a district's profile; the activity types that are visits and the statuses
that are completed work; the statuses that keep a school operating; and the
clusters table's page size. A change to any of them must be exported again;
apps/schools/test_coverage_rules_export.py fails until it is.

    python manage.py export_coverage_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/coverage/rules.json")

PAGE_PATH = "/coverage"
PAGE_PERMISSION = "coverage"


def rules() -> dict:
    from apps.core.activity_types import COMPLETED_WORK_STATUSES, VISIT_TYPES
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.schools.lifecycle_service import OPERATING_STATUSES

    def roles(test) -> list[str]:
        return sorted(r.value for r in EdifyRole if test(_role_user(r.value)))

    return {
        "page_roles": roles(
            lambda u: RolePermissionService.can_view_page(u, PAGE_PERMISSION)
            and bool(can_open_url(u, PAGE_PATH))
        ),
        "district_profile_roles": roles(
            lambda u: bool(can_open_url(u, "/districts/0"))
        ),
        "visit_types": sorted(str(t) for t in VISIT_TYPES),
        "completed_work_statuses": sorted(str(s) for s in COMPLETED_WORK_STATUSES),
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Coverage page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
