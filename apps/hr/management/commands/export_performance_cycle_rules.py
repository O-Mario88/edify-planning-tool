"""Write the Performance Cycle Console's rules for the Go gateway.

Go builds the Performance Cycle Console (/hr/performance-cycle,
apps.frontend.views.hr_views.hr_performance_console_view,
apps.hr.performance_engine.quarterly_readiness and
pages/hr/performance_console.html) from what this command writes to
platform/backend/internal/perfcycle/rules.json: who may open the page and
which of them its controls are for; the conversation windows it offers; how
it words an agreement's stage; the agreement type it lists; the onboarding
state that puts someone in the cycle; and the page size. A change to any of
them must be exported again; apps/hr/test_performance_cycle_rules_export.py
fails until it is.

    python manage.py export_performance_cycle_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/perfcycle/rules.json")

PAGE_PATH = "/hr/performance-cycle"
PAGE_PERMISSION = "performance_console"


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.hr_views import CONSOLE_ROLES, CONSOLE_STAGE_LABELS
    from apps.hr.models import PerformanceCycle, ReviewType

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), PAGE_PERMISSION
            )
            and can_open_url(_role_user(role.value), PAGE_PATH)
        ),
        "console_roles": list(CONSOLE_ROLES),
        "windows": [
            [value, str(label)]
            for value, label in PerformanceCycle.WINDOWS
            if value != "none"
        ],
        "stage_labels": dict(CONSOLE_STAGE_LABELS),
        "review_type": ReviewType.ANNUAL_PRIORITIES.value,
        "active_onboarding_state": "active",
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Performance Cycle Console's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
