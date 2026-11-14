"""Write the Leave Tracker's rules for the Go gateway.

Go builds the Team Leave & Coverage Tracker (/leave/tracker,
apps.frontend.views.leave_views.leave_tracker_view, drawn by
pages/leave/leave_tracker.html) and the Team Availability Heatmap
(/leave/team-availability, team_availability_view and
pages/leave/team_availability.html) from what this command writes to
platform/backend/internal/leavetracker/rules.json: who may open each page and
the workspace strip each role is shown above it; which roles read their own
team and which read everyone in the heatmap; the balance shown when a person
has none for the year; how many people the heatmap lists; and the page size.
A change to any of them must be exported again;
apps/hr/test_leave_tracker_rules_export.py fails until it is.

    python manage.py export_leave_tracker_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/leavetracker/rules.json")

PAGE_PATH = "/leave/tracker"
AVAILABILITY_PATH = "/leave/team-availability"


def rules() -> dict:
    from apps.core.navigation import get_user_role_slug
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import leave_views

    roles, leads, everyone = {}, [], []
    for role in EdifyRole:
        user = _role_user(role.value)
        slug = get_user_role_slug(user)
        if slug == "PL":
            leads.append(role.value)
        if slug in leave_views.TRACKER_COUNTRY_SCOPE_SLUGS:
            everyone.append(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, "leave_tracker")
            and bool(can_open_url(user, PAGE_PATH)),
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html"),
            "availability": RolePermissionService.can_view_page(
                user, "team_availability"
            )
            and bool(can_open_url(user, AVAILABILITY_PATH)),
            "availability_strip": strip(
                user, AVAILABILITY_PATH, "partials/_section_nav.html"
            ),
        }
    return {
        "roles": roles,
        "lead_roles": sorted(leads),
        "heatmap_everyone_roles": sorted(everyone),
        "default_balances": leave_views.TRACKER_DEFAULT_BALANCES,
        "heatmap_limit": leave_views.TRACKER_HEATMAP_LIMIT,
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Leave Tracker's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
