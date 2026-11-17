"""Write the Uganda Target Distribution page's rules for Go.

Go builds /target-distribution
(apps.frontend.views.target_distribution_views.target_distribution_page) from
what this command writes to
platform/backend/internal/targetdistribution/rules.json: which roles may open
the page and which may import country priorities (the view's own gates); the
Priorities rail each role is shown above the view (priority_workspace_tabs);
and the years a requested FY may name. A change to any of them must be
exported again; apps/hr/test_target_distribution_rules_export.py fails until
it is.

    python manage.py export_target_distribution_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/targetdistribution/rules.json")
PAGE_PATH = "/target-distribution"
PAGE_KEY = "target_distribution"


def _tabs(user) -> list[list[str]] | None:
    """The rail priority_workspace_tabs gives ``user`` on this view, as
    [label, path] pairs with no year carried, or None for a reader with one
    view."""
    from django.test import RequestFactory

    from apps.frontend.views.priority_workspace import priority_workspace_tabs

    request = RequestFactory().get(PAGE_PATH)
    request.user = user
    rail = priority_workspace_tabs(
        request,
        active="distribution",
        view_template="partials/priorities/distribution_view.html",
    )
    if rail is None:
        return None
    return [[tab["label"], tab["url"]] for tab in rail["tabs"]]


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.frontend.views.hr_views import MAX_FY_YEAR, MIN_FY_YEAR
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        if not (
            RolePermissionService.can_view_page(user, PAGE_KEY)
            and has_permission(user, Permission.STRATEGIC_PRIORITIES_VIEW.value)
        ):
            continue
        roles[role.value] = {
            "import": has_permission(
                user, Permission.STRATEGIC_PRIORITIES_IMPORT.value
            ),
            "tabs": _tabs(user),
        }
    return {
        "roles": roles,
        "min_fy_year": MIN_FY_YEAR,
        "max_fy_year": MAX_FY_YEAR,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Uganda Target Distribution page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
