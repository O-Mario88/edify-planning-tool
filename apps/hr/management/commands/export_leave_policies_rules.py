"""Write the Leave Policies page's rules for the Go gateway.

Go builds HR Leave Policies & Holiday Settings (/leave/policies,
apps.frontend.views.leave_views.leave_policies_view, drawn by
pages/leave/leave_policies.html) from what this command writes to
platform/backend/internal/leavepolicies/rules.json: who may open the page,
the workspace strip each role is shown above it and how many upcoming
national holidays it lists. A change to any of them must be exported again;
apps/hr/test_leave_policies_rules_export.py fails until it is.

    python manage.py export_leave_policies_rules
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/leavepolicies/rules.json")

PAGE_PATH = "/leave/policies"


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, "leave_policies")
            and bool(can_open_url(user, PAGE_PATH)),
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html"),
        }
    return out


def national_limit() -> int:
    """How many upcoming national holidays the view asks for."""
    from apps.frontend.views import leave_views

    source = inspect.getsource(inspect.unwrap(leave_views.leave_policies_view))
    found = re.search(
        r"upcoming_public_holidays\(date\.today\(\), limit=(\d+)\)", source
    )
    if found is None:
        raise ValueError(
            "leave_policies_view no longer says how many holidays it lists"
        )
    return int(found.group(1))


def rules() -> dict:
    return {"roles": roles(), "national_limit": national_limit()}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Leave Policies page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
