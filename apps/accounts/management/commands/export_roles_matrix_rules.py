"""Write the Roles & Permissions matrix's rules for the Go gateway.

Go builds the Roles & Permissions matrix (/admin-panel/roles-permissions,
apps.frontend.views.extended_views.admin_roles_permissions_view and
pages/admin/roles_permissions.html) from the RBAC tables and what this command
writes to platform/backend/internal/rolesmatrix/rules.json: who may open the
page, the roles in the order the matrix draws its columns (EdifyRole's
order), and the page size of its permission groups. A change to any of them
must be exported again; apps/accounts/test_roles_matrix_rules_export.py fails
until it is.

    python manage.py export_roles_matrix_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/rolesmatrix/rules.json")

PAGE_PATH = "/admin-panel/roles-permissions"
PAGE_PERMISSION = "roles_permissions"


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), PAGE_PERMISSION
            )
            and can_open_url(_role_user(role.value), PAGE_PATH)
        ),
        "role_order": [role.value for role in EdifyRole],
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Roles & Permissions matrix's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
