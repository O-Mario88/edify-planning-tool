"""Write the role → permission matrix for the Go gateway.

Go owns permission checks for what has moved to it (owner brief, 2026-11-11:
"Roles and permission management"). It reads the same matrix as this
application, from platform/backend/internal/rbac/role_permissions.json, which
this command writes from apps.core.rbac.ROLE_PERMISSIONS. A change to the
matrix here must be exported again; apps/core/test_rbac_matrix_export.py
fails until it is, so the two can never drift.

    python manage.py export_rbac_matrix
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.rbac import ROLE_PERMISSIONS, EdifyRole, Permission

EXPORT_PATH = Path("platform/backend/internal/rbac/role_permissions.json")


def matrix() -> dict:
    """The matrix as the Go side reads it: every role and permission key the
    existing application defines, each role's keys sorted."""
    return {
        "roles": [role.value for role in EdifyRole],
        "permissions": sorted(permission.value for permission in Permission),
        "grants": {
            role.value: sorted(p.value for p in ROLE_PERMISSIONS.get(role, []))
            for role in EdifyRole
        },
    }


def rendered() -> str:
    return json.dumps(matrix(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the role → permission matrix for the Go gateway."

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / EXPORT_PATH
        path.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
