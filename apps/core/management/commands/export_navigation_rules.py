"""Write every role's navigation for the Go gateway.

Go answers the app's and the web app's navigation (GetNavigation: the bottom
bar and the full menu, apps.mobile_feed.views.NavigationFeedView) from what
this command writes to platform/backend/internal/navigation/rules.json: for
each role, the bar and the menu exactly as the feed builds them
(apps.core.navigation.build_sidebar_for_user and build_mobile_nav_for_user,
read through the feed's own nav_item), once for a login in its own role and,
for the partner roles, once more for a partner's team member
(apps.partners.member_scope), whose menu withholds the Partner Admin's pages.

Nothing is restated: the registry, its role audiences, folds, visit tiers,
short labels and icons stay in apps.core.navigation, and each role's answer is
computed here by the same functions the feed calls. A change to any of them
must be exported again; apps/core/test_navigation_rules_export.py fails until
it is, so the two can never drift.

    python manage.py export_navigation_rules
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/navigation/rules.json")

#: The path the feed builds the navigation for (NavigationFeedView).
FEED_PATH = "/home"


def _team_member(role: str):
    """A partner login that is a team member (member_scope.team_member's
    answer, already read for this request object)."""
    from apps.partners.member_scope import _CACHE_ATTR

    user = SimpleNamespace(**vars(_role_user(role)))
    user.pk = user.id = user.user_id = "team-member"
    setattr(user, _CACHE_ATTR, SimpleNamespace(partner=None))
    return user


def _acting_user(entry):
    """A staff login working in an acting capacity (apps.acting.services.build_context)."""
    from datetime import date

    from apps.core.acting import CONTEXT_ATTR, ActingContext

    user = SimpleNamespace(**vars(_role_user(entry.appointee_role.value)))
    user.pk = user.id = user.user_id = f"acting-{entry.key}"
    setattr(
        user,
        CONTEXT_ATTR,
        ActingContext(
            assignment_id=f"export-{entry.key}",
            acting_role=entry.acting_role_value,
            substantive_role=entry.appointee_role.value,
            label=entry.label,
            short_label=entry.short_label,
            scope_type=entry.scope_type,
            seat_staff_id="export-seat-staff",
            seat_user_id="export-seat-user",
            seat_name="Export Seat",
            country="Uganda",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            appointed_by_id="export-appointer",
            appointed_by_name="Export Appointer",
            withheld_permissions=entry.withheld_permission_values(),
            withheld_pages=frozenset(entry.withheld_pages),
            withheld_authorities=frozenset(entry.withheld_authorities),
        ),
    )
    user.active_role = entry.acting_role_value
    return user


def _navigation(user, icons: list[str]) -> dict:
    """The feed's answer for this reader, icons by their place in `icons`."""
    from apps.core.navigation import build_mobile_nav_for_user, build_sidebar_for_user
    from apps.mobile_feed.views import nav_item

    def item(raw: dict) -> dict:
        out = nav_item(raw, user)
        svg = out.pop("iconSvg")
        if svg not in icons:
            icons.append(svg)
        return {
            "label": out["label"],
            "url": out["url"],
            "icon": icons.index(svg),
            "page_key": out["pageKey"],
            "native": out["native"],
        }

    sections = build_sidebar_for_user(user, FEED_PATH)
    bottom = build_mobile_nav_for_user(user, FEED_PATH, sections)
    return {
        "bottom": [item(i) for i in bottom],
        "sections": [
            {
                "label": str(s.get("label") or s.get("title") or ""),
                "items": [item(i) for i in s.get("items", [])],
            }
            for s in sections
        ],
    }


def rules() -> dict:
    from apps.acting.policy import ACTING_ROLES
    from apps.core.rbac import EdifyRole
    from apps.partners.member_scope import _PARTNER_ROLES

    icons: list[str] = []
    roles = {
        role.value: _navigation(_role_user(role.value), icons) for role in EdifyRole
    }
    team_members = {
        role: _navigation(_team_member(role), icons) for role in _PARTNER_ROLES
    }
    acting = {
        key: _navigation(_acting_user(entry), icons)
        for key, entry in ACTING_ROLES.items()
    }
    return {
        "roles": roles,
        "team_members": team_members,
        "acting": acting,
        "partner_team": {"withheld": True, "roles": list(_PARTNER_ROLES)},
        "icons": icons,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write every role's navigation for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
