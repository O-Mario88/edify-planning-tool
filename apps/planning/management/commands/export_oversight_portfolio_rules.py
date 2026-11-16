"""Write the Team/Country Portfolio lens's rules for the Go gateway.

Go builds the portfolio lens of Planning Oversight, and the Country Map that
draws the same portfolio under its map
(/team-planning-oversight/?view=portfolio and /country-map/: oversight_views.
team_planning_oversight_view, _portfolio_context, _portfolio_kpis and
apps.planning.portfolio_service.country_portfolio) from the vocabularies this
command writes to platform/backend/internal/oversightportfolio/rules.json: who
opens the page and the lens, the lens strip each role is drawn, the activity
types the Visits and Trainings columns count, the statuses that are no work
at all, the operating statuses, the Programme Lead role, the group headings
for a school nobody carries, the table page size and how the feed passes a
page its query. A change to any of them must be exported again;
apps/planning/test_oversight_portfolio_rules_export.py fails until it is.

    python manage.py export_oversight_portfolio_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/oversightportfolio/rules.json")


def _tabs(available, country: bool) -> list[dict]:
    from apps.frontend.views.oversight_views import TEAM_OVERSIGHT_PATH, _lens_tabs

    return [
        {"label": tab["label"], "href": tab["href"], "active": tab["is_active"]}
        for tab in _lens_tabs(
            TEAM_OVERSIGHT_PATH, "portfolio", available, country=country
        )
    ]


def doors() -> dict:
    """What each role reaches, by the page's own gates: the page
    (require_any_page_permission and the feed's can_open_url), the portfolio
    lens, whether the role reads the country (is_country_reader), and the
    strip drawn above the lens for a reader of the country and for a team."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.oversight_views import (
        COUNTRY_MAP_PATH,
        TEAM_OVERSIGHT_PATH,
        is_country_reader,
        team_available_lenses,
        team_oversight_lenses,
    )

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        lenses = team_oversight_lenses(user)
        available = team_available_lenses(lenses)
        out[role.value] = {
            "page": any(
                RolePermissionService.can_view_page(user, page)
                for page in ("team_planning_oversight", "team_targets")
            ),
            "feed_opens": bool(can_open_url(user, TEAM_OVERSIGHT_PATH)),
            # The Country Map (/country-map/), which draws the same portfolio
            # under the map: its page permission and whether the feed opens it.
            "map_page": RolePermissionService.can_view_page(user, "country_map"),
            "map_feed_opens": bool(can_open_url(user, COUNTRY_MAP_PATH)),
            "portfolio": lenses["portfolio"],
            "country_reader": bool(is_country_reader(user)),
            "lens_tabs_country": _tabs(available, True),
            "lens_tabs_team": _tabs(available, False),
        }
    return out


#: The role COVERAGE_LENS_ROLES means and the name it misspells (owner,
#: 2026-11-13: "Can you fix those from the go side"; Go draws the corrected
#: doors, internal/parity/intended.json go-fix-rvp-lens).
_MISSPELT_ROLE, _MEANT_ROLE = "RegionalVP", "RegionalVicePresident"


def fixed_doors() -> dict:
    """The doors of every role whose doors change once COVERAGE_LENS_ROLES
    (and PORTFOLIO_LENS_ROLES, the same set) names the Regional Vice
    President as it means to: what Go draws instead of the existing page."""
    from unittest import mock

    from apps.frontend.views import oversight_views

    meant = frozenset(
        _MEANT_ROLE if role == _MISSPELT_ROLE else role
        for role in oversight_views.COVERAGE_LENS_ROLES
    )
    existing = doors()
    with (
        mock.patch.object(oversight_views, "COVERAGE_LENS_ROLES", meant),
        mock.patch.object(oversight_views, "PORTFOLIO_LENS_ROLES", meant),
    ):
        corrected = doors()
    return {
        role: corrected[role] for role in corrected if corrected[role] != existing[role]
    }


def rules() -> dict:
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed import views as feed
    from apps.planning import portfolio_service as portfolio
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.school_status import DEAD_STATUSES

    return {
        "doors": doors(),
        "fixed_doors": fixed_doors(),
        "visit_types": sorted(VISIT_TYPES),
        "training_types": sorted(TRAINING_TYPES),
        "dead_statuses": sorted(DEAD_STATUSES),
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "program_lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "no_lead_key": portfolio.NO_LEAD_KEY,
        "no_lead_label": portfolio.NO_LEAD_LABEL,
        "unassigned_key": portfolio.UNASSIGNED_KEY,
        "unassigned_label": portfolio.UNASSIGNED_LABEL,
        "page_size": TABLE_PAGE_SIZE,
        # How the feed passes a page its query (apps.mobile_feed.views).
        "query_key_pattern": feed.QUERY_KEY.pattern,
        "query_keys_not_passed": sorted(feed.NOT_PASSED),
        "max_query_value": feed.MAX_QUERY_VALUE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the portfolio lens's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
