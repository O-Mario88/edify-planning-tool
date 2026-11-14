"""Write the Partner Admin's Users page rules for the Go gateway.

Go builds Users (/partner/users, apps.frontend.views.partner_views
.partner_users_view, _team_roster, pages/partner/users.html and
partials/partners/team_table.html) from what this command writes to
platform/backend/internal/partnerusers/rules.json: which roles may open the
page; the label of a member's role; the roster table's page size; and the
query keys the feed never passes. Whose team it is, who leads it and what
each member holds come from the gateway's own partner team service
(internal/teams), which ports apps.partners.member_logins and school_team.
A change to any of them must be exported again;
apps/partners/test_partner_users_rules_export.py fails until it is.

    python manage.py export_partner_users_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/partnerusers/rules.json")

PERMISSION = "partner_users"
PATH = "/partner/users"


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed.views import NOT_PASSED
    from apps.partners.models import PartnerMemberRole

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(_role_user(role.value), PERMISSION)
            and can_open_url(_role_user(role.value), PATH)
        ),
        "member_roles": dict(PartnerMemberRole.choices),
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Partner Admin's Users page rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
