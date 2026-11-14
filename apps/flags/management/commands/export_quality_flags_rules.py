"""Write the Quality Flags page's rules for the Go gateway.

Go builds Quality Flags (/quality-checks,
apps.frontend.views.extended_views.quality_checks_view, apps.flags.services
and pages/quality_checks/index.html) from what this command writes to
platform/backend/internal/qualityflags/rules.json: who may open the page,
who raises a flag (the form) and who acts on one (the Actions column), the
roles that read every flag rather than their own, a flag's status labels and
how many flags the register lists. A change to any of them must be exported
again; apps/flags/test_quality_flags_rules_export.py fails until it is.

    python manage.py export_quality_flags_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/qualityflags/rules.json")

#: The page's permission and path.
PERMISSION = "quality_checks"
PATH = "/quality-checks"

#: qs[:50] in quality_checks_view: the register lists the 50 most recent.
LIMIT = 50


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.flags.models import CdFlagStatus
    from apps.flags.services import _FLAG_MONITOR_ROLES

    # quality_checks_view's is_cd and is_pl: the Country Director (and Admin)
    # raises a flag, the Programme Lead (and Admin) acts on one.
    raisers = (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value)
    actors = (EdifyRole.COUNTRY_PROGRAM_LEAD.value, EdifyRole.ADMIN.value)
    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, PERMISSION)
            and bool(can_open_url(user, PATH)),
            "raises": role.value in raisers,
            "acts": role.value in actors,
        }
    return {
        "roles": roles,
        "monitor_roles": sorted(_FLAG_MONITOR_ROLES),
        "statuses": dict(CdFlagStatus.choices),
        "limit": LIMIT,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Quality Flags page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
