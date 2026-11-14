"""Write the Fiscal Year Planning page's rules for the Go gateway.

Go builds Fiscal Year Planning (/planning/fiscal-years,
apps.frontend.views.fy_planning_views.fiscal_year_planning_view,
apps.planning.fy_policy and pages/planning/fiscal_years.html) from what this
command writes to platform/backend/internal/fyplanning/rules.json: for each
role, whether it may open the page and whether it manages the planning policy
(`fy_policy.may_manage`: the follow-up rule's button and the form that opens
the next year); and the country whose policy decides whether the next year is
open (`fy_policy.default_country`). A change to any of them must be exported
again; apps/planning/test_fy_planning_rules_export.py fails until it is.

    python manage.py export_fy_planning_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/fyplanning/rules.json")

PERMISSION = "fy_planning_policy"
PATH = "/planning/fiscal-years"


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.planning import fy_policy

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, PERMISSION)
            and bool(can_open_url(user, PATH)),
            "manages": fy_policy.may_manage(user),
        }
    return {"roles": roles, "default_country": fy_policy.default_country()}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Fiscal Year Planning page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
