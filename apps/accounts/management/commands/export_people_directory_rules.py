"""Write the People Directory's rules for the Go gateway.

Go builds the People Directory (/staff, apps.frontend.views.staff_views
.staff_directory_view and pages/staff/index.html) from what this command
writes to platform/backend/internal/peopledirectory/rules.json: who may open
the page, who reads colleagues' email addresses and who is offered "New Staff
Member"; the words for each role; the activity types that are visits and the
statuses that are completed, out of the plan, or dated work not yet handed
in; and the page size. A change to any of them must be exported again;
apps/accounts/test_people_directory_rules_export.py fails until it is.

    python manage.py export_people_directory_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/peopledirectory/rules.json")

PAGE_PATH = "/staff"
PAGE_PERMISSION = "staff_directory"


def rules() -> dict:
    from apps.accounts.hr_dashboard_service import ROLE_LABELS
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NOT_IN_PLAN_ACTIVITY_STATUSES,
        VISIT_TYPES,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import staff_views

    def roles(test) -> list[str]:
        return sorted(r.value for r in EdifyRole if test(_role_user(r.value)))

    return {
        "page_roles": roles(
            lambda u: RolePermissionService.can_view_page(u, PAGE_PERMISSION)
            and bool(can_open_url(u, PAGE_PATH))
        ),
        "add_staff_roles": roles(
            lambda u: RolePermissionService.can_view_page(u, "users")
        ),
        "email_roles": sorted(staff_views.DIRECTORY_EMAIL_ROLES),
        "singular_role_labels": staff_views.SINGULAR_ROLE_LABELS,
        "role_labels": ROLE_LABELS,
        "visit_types": sorted(str(t) for t in VISIT_TYPES),
        "completed_statuses": sorted(str(s) for s in COMPLETED_WORK_STATUSES),
        "not_in_plan_statuses": sorted(str(s) for s in NOT_IN_PLAN_ACTIVITY_STATUSES),
        "not_finished_statuses": list(staff_views._NOT_FINISHED_IN_FIELD),
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the People Directory's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
