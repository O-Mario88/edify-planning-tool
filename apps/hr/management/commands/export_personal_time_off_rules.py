"""Write the Personal Time Off page's rules for the Go gateway.

Go builds the page (/personal-time-off/: apps.frontend.views.leave_views.
personal_time_off_view over apps.hr.leave_services, and
pages/leave/personal_time_off.html, as the existing feed reads them) from what
this command writes to platform/backend/internal/personaltimeoff/rules.json:
for each role, whether it may open the page, the workspace strip it is shown,
its role slug (which decides whose leave the tracker lists), whether it may
open the leave policy and the team availability report; the order balances
are listed in; the statuses a request is past in; and the activity statuses
the schedule conflicts read. A change to any of them must be exported again;
apps/hr/test_personal_time_off_rules_export.py fails until it is.

    python manage.py export_personal_time_off_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/personaltimeoff/rules.json")

PAGE_PERMISSION = "personal_time_off"
PATH = "/personal-time-off/"
TEAM_AVAILABILITY = "/leave/team-availability"

#: personal_time_off_view's balance_priority.
BALANCE_PRIORITY = {
    "personal_time_off": 0,
    "sick_leave": 1,
    "maternity_leave": 2,
    "paternity_leave": 3,
    "bereavement_leave": 4,
}
#: personal_time_off_view's past_request_statuses.
PAST_STATUSES = ["completed", "rejected"]


def roles() -> dict:
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "slug": get_user_role_slug(user),
            "leave_policies": RolePermissionService.can_view_page(
                user, "leave_policies"
            ),
            "team_availability": bool(can_open_url(user, TEAM_AVAILABILITY)),
        }
    return out


def rules() -> dict:
    from apps.activities.day_off import AWAITING_DELIVERY

    return {
        "roles": roles(),
        "balance_priority": BALANCE_PRIORITY,
        "past_statuses": PAST_STATUSES,
        "awaiting_delivery": list(AWAITING_DELIVERY),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Personal Time Off page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
