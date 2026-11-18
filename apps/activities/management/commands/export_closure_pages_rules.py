"""Write the closure pages' rules for the Go gateway.

Go builds the Analytics Publishing Status page (/analytics/publishing:
apps.frontend.views.closure_views.analytics_publishing_status_view and
partials/analytics/panels/publishing_status.html) and the Completed Activities
ledger (/completed-activities: completed_activities_view and
partials/analytics/panels/completed_work.html), as the existing feed reads them, from what this command writes to
platform/backend/internal/closurepages/rules.json: for each role, whether it
may open each page, whether a school's name opens its profile and the
workspace strip it is shown on each; and the rank
each publishing status sorts by. A change to any of them must be exported
again; apps/activities/test_closure_pages_rules_export.py fails until it is.

    python manage.py export_closure_pages_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/closurepages/rules.json")

PUBLISHING_PERMISSION = "analytics_publishing"
PUBLISHING_PATH = "/analytics/publishing"
COMPLETED_PERMISSION = "completed_activities"
COMPLETED_PATH = "/completed-activities"


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "publishing": RolePermissionService.can_view_page(
                user, PUBLISHING_PERMISSION
            )
            and bool(can_open_url(user, PUBLISHING_PATH)),
            # school_links._may_open.
            "open_school": bool(can_open_url(user, "/schools/0")),
            # The workspace strip the page carries for the role (IA's).
            "publishing_strip": strip(
                user, PUBLISHING_PATH, "partials/analytics/tab_rail.html"
            ),
            "completed": RolePermissionService.can_view_page(user, COMPLETED_PERMISSION)
            and bool(can_open_url(user, COMPLETED_PATH)),
            "completed_strip": strip(
                user, COMPLETED_PATH, "partials/analytics/tab_rail.html"
            ),
        }
    return out


def rules() -> dict:
    from apps.frontend.views.closure_views import (
        PUBLISH_STATUS_OTHER_RANK,
        PUBLISH_STATUS_RANK,
    )

    return {
        "roles": roles(),
        "publish_status_rank": PUBLISH_STATUS_RANK,
        "publish_status_other_rank": PUBLISH_STATUS_OTHER_RANK,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the closure pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
