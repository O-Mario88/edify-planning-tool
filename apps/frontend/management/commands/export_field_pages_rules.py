"""Write the field pages' rules for the Go gateway.

Go builds the School Map (/map: apps.frontend.views.extended_views.map_view,
pages/map/index.html) and the empty Search page (/search: search_view with no
query) as the existing feed reads them, from what this command writes to
platform/backend/internal/fieldpages/rules.json: for each role, whether it
may open each page. A change must be exported again;
apps/frontend/test_field_pages_rules_export.py fails until it is.

    python manage.py export_field_pages_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/fieldpages/rules.json")

#: Each page, its permission and its path.
PAGES = {
    "map": ("schools", "/map"),
    "search": ("search", "/search"),
}


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            name: bool(
                RolePermissionService.can_view_page(user, permission)
                and can_open_url(user, path)
            )
            for name, (permission, path) in PAGES.items()
        }
    return {"roles": roles}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the field pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
