"""Write the IA review pages' rules for the Go gateway.

Go builds the Impact Assessment review pages (apps.frontend.views.ia_views)
from what this command writes to
platform/backend/internal/iapages/rules.json: for each page Go answers, who
may open it (the pages draw no workspace strip); which
roles hold the IA verification permission (without it a reader sees only the
work an Impact Assessment officer ran, `_ia_reach_q`); each activity
type's label; and who may open a school's profile. A change to any of them must be exported again;
apps/activities/test_ia_pages_rules_export.py fails until it is.

    python manage.py export_ia_pages_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/iapages/rules.json")

#: The pages Go answers and their page permission.
PAGES = {
    "/ia/duplicates/": "ia_duplicates",
    "/ia/returned/": "ia_returned",
    "/ia/history/": "ia_history",
}


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.permissions import (
        Permission,
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed.views import NOT_PASSED

    pages = {}
    for path, permission in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            roles[role.value] = {
                "page": RolePermissionService.can_view_page(user, permission)
                and bool(can_open_url(user, path)),
            }
        pages[path] = {"roles": roles}
    return {
        "pages": pages,
        "ia_verify_roles": sorted(
            role.value
            for role in EdifyRole
            if has_permission(_role_user(role.value), Permission.IA_VERIFY.value)
        ),
        "activity_types": dict(ActivityType.choices),
        "query_keys_not_passed": sorted(NOT_PASSED),
        # Who may open a school's profile, so a school's name is a link
        # (apps.frontend.templatetags.school_links._may_open_profiles).
        "school_profile_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open_url(_role_user(role.value), "/schools/0")
        ),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the IA review pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
