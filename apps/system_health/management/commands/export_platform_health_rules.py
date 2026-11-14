"""Write Platform Health's door for Go.

Go's own health page (/platform-health: the gateway, its database
connection, the schemas it owns, the audit chain's tail and the work waiting
on the existing application) opens to whoever may open System Health
(the `system_health` page permission). This command writes those roles to
platform/backend/internal/platformhealth/rules.json; a change must be exported
again, and apps/system_health/test_platform_health_rules_export.py fails until
it is.

    python manage.py export_platform_health_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/platformhealth/rules.json")


def rules() -> dict:
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), "system_health"
            )
        ),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Platform Health's door for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
