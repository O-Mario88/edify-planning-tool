"""Write Planning Oversight's and Country Oversight's doors for the Go gateway.

Go is to be the application's only backend (owner, 2026-11-11). It answers
the app's feed for Planning Oversight (/team-planning-oversight/,
apps.frontend.views.oversight_views.team_planning_oversight_view) and
Country Oversight (/country-planning-oversight/, country_planning_oversight_
view) from what this command writes to
platform/backend/internal/planningoversight/rules.json: whether the feed
opens each page, and who it opens it for. A change to any of them must be
exported again; apps/planning/test_planning_oversight_rules_export.py fails
until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the feed and the pages themselves ask (the feed's can_open_url, the views'
require_any_page_permission / require_page_permission).

    python manage.py export_planning_oversight_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/planningoversight/rules.json")

#: Each page as the app's feed opens it: its path, its URL name, and the page
#: permissions its view's decorator accepts (any one of them).
PAGES = {
    "team": (
        "/team-planning-oversight/",
        "team_planning_oversight",
        ("team_planning_oversight", "team_targets"),
    ),
    "country": (
        "/country-planning-oversight/",
        "country_planning_oversight",
        ("country_planning_oversight",),
    ),
}


def doors() -> dict:
    """Whether each role reaches each page, by the feed's and the view's gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            key: {
                # apps.mobile_feed.views._run_page: a path the reader may not
                # open is "not available" before the view runs.
                "open": bool(can_open_url(user, path)),
                # The view's own decorator.
                "page": any(
                    RolePermissionService.can_view_page(user, name) for name in pages
                ),
            }
            for key, (path, _name, pages) in PAGES.items()
        }
    return out


def team_plan() -> dict:
    """What the Team Plan lens draws for a Programme Lead whose team has
    nothing planned in the period, from the view's own builders."""
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import oversight_views as views
    from apps.mobile_feed.views import NOT_PASSED
    from apps.planning import flagged_schools
    from apps.planning import oversight_service as oversight

    role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    user = _role_user(role)
    lenses = views.team_oversight_lenses(user)
    lens_tabs = views._lens_tabs(
        views.TEAM_OVERSIGHT_PATH,
        "planning",
        views.team_available_lenses(lenses),
        country=views.is_country_reader(user),
    )
    owner_tabs, _selected, _items = views._team_owner_tabs(
        oversight.OversightScope(kind="pl"), [], views.WHOLE_TEAM_TAB
    )
    kpis = views._kpi_items(oversight.summarize([]), country=False, region=False)
    return {
        "lead_role": role,
        "lens_tabs": [
            {"label": t["label"], "href": t["href"], "active": t["is_active"]}
            for t in lens_tabs
        ],
        "owner_tabs": [{"key": t["key"], "label": t["label"]} for t in owner_tabs],
        "activity_tabs": [
            {"key": t["key"], "label": t["label"]}
            for t in oversight.activity_tabs([], "all")
        ],
        "zero_kpis": [
            {
                "label": k["label"],
                "value": k["display_value"],
                "helper": k["helper"],
                "tone": k["tone"],
            }
            for k in kpis
        ],
        "evidence_link": RolePermissionService.can_view_page(user, "evidence_center"),
        "live_activity_statuses": list(oversight.LIVE_ACTIVITY_STATUSES),
        "not_planned_statuses": list(flagged_schools.NOT_PLANNED_STATUSES),
        "filter_keys": list(oversight.FILTER_KEYS),
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rules() -> dict:
    from apps.mobile_feed.views import NATIVE_PAGES

    return {
        "pages": {
            key: {"path": path, "feed_opens_page": name in NATIVE_PAGES}
            for key, (path, name, _pages) in PAGES.items()
        },
        "doors": doors(),
        "team_plan": team_plan(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Planning Oversight's and Country Oversight's doors for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
