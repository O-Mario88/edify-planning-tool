"""Write the User Management page's rules for the Go gateway.

Go builds the page (/admin-panel/users: apps.frontend.views.extended_views.
admin_users_view and pages/admin/users.html, as the existing feed reads them)
from what this command writes to platform/backend/internal/adminusers/
rules.json: for each role, whether it may open the page, the workspace strip
it is shown, whether it reads every account (the Admin) and whether it
manages partner organisations, their logins and their permanent deletion;
the roles the role filter offers; the partner user-setup states' names; the
interventions' names; and the table page size and the query keys a pager
does not carry. A change to any of them must be exported again;
apps/accounts/test_admin_users_rules_export.py fails until it is.

    python manage.py export_admin_users_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/adminusers/rules.json")

PAGE_PERMISSION = "users"
PATH = "/admin-panel/users"


def roles() -> dict:
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.partners.services import may_manage_partner_users

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        slug = get_user_role_slug(user)
        manages = slug in {"ADMIN", "CD"}
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "reads_everyone": role is EdifyRole.ADMIN,
            "manages_partners": manages,
            "manages_partner_users": manages and may_manage_partner_users(user),
            "purges_partners": slug == "ADMIN",
        }
    return out


def rules() -> dict:
    from apps.core.enums import SsaIntervention
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed.views import NOT_PASSED
    from apps.partners.models import PartnerUserSetupStatus

    return {
        "roles": roles(),
        "filter_roles": [r.value for r in EdifyRole],
        "user_setup_states": {
            str(value): str(label) for value, label in PartnerUserSetupStatus.choices
        },
        "interventions": {
            str(value): str(label) for value, label in SsaIntervention.choices
        },
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the User Management page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
