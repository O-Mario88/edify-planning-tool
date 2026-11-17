"""Write Uganda Priorities' page rules for Go.

Go builds /priorities/master
(apps.frontend.views.target_distribution_views.priorities_master_page) from
what this command writes to
platform/backend/internal/prioritiesmaster/rules.json: which roles may open
the page, which it sends on to the distribution workspace, which read their
own allocation in the target column, the Priorities rail each role is shown
(priority_workspace_tabs) and the years a requested FY may name. A change to
any of them must be exported again;
apps/hr/test_priorities_master_rules_export.py fails until it is.

    python manage.py export_priorities_master_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/prioritiesmaster/rules.json")
PAGE_PATH = "/priorities/master"
PAGE_KEY = "priorities_master"


def _tabs(user) -> list[list[str]] | None:
    """The rail priority_workspace_tabs gives ``user`` on this view, as
    [label, path] pairs with no year carried, or None for one view."""
    from django.test import RequestFactory

    from apps.frontend.views.priority_workspace import priority_workspace_tabs

    request = RequestFactory().get(PAGE_PATH)
    request.user = user
    rail = priority_workspace_tabs(
        request,
        active="distribution",
        view_template="partials/priorities/master_view.html",
    )
    if rail is None:
        return None
    return [[tab["label"], tab["url"]] for tab in rail["tabs"]]


def rules() -> dict:
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.hr_views import MAX_FY_YEAR, MIN_FY_YEAR
    from apps.frontend.views.target_distribution_views import (
        MASTER_RUNNER_ROLES,
        SCOPED_VIEWER_ROLES,
    )
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        if not RolePermissionService.can_view_page(user, PAGE_KEY):
            continue
        roles[role.value] = {
            "runner": role.value in MASTER_RUNNER_ROLES,
            "scoped": role.value in SCOPED_VIEWER_ROLES,
            "lead": role.value == EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            "tabs": None if role.value in MASTER_RUNNER_ROLES else _tabs(user),
        }
    return {"roles": roles, "min_fy_year": MIN_FY_YEAR, "max_fy_year": MAX_FY_YEAR}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Uganda Priorities' page rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
