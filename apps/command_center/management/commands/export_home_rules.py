"""Write Home's rules for the Go gateway.

Go answers Home (GetHome: apps.mobile_feed.views.HomeFeedView over
apps.command_center.home_service.build_home) from what this command writes to
platform/backend/internal/home/rules.json:

  • for each role: whether it may open Home, the slug every permission reads,
    the title Home's header gives it, whether it has a plan of its own, and
    its Quick access, exactly as build_home_shortcuts_for_user picks them;
  • Home's icons (partials/home/icon.html), as the feed draws them;
  • each overview figure's label and description, from the metric registry
    (render_precomputed_metric_item), which do not depend on the value;
  • how many upcoming activities and priority rows Home lists;
  • an activity's status and type as Home words them (the model's choices,
    get_status_display and get_activity_type_display);
  • the Priority actions the owner set for a CCEO and a Programme Lead
    (apps.command_center.home_priorities): each role's rows in order, each
    row's words, icon, action and link — the link with FY_MARK where the
    year goes, which Go fills in.

Nothing is restated: each answer is computed here by the same functions the
feed calls. apps/command_center/test_home_rules_export.py fails until a
change to any of them is exported again.

    python manage.py export_home_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/home/rules.json")

#: The path the feed builds Home for (HomeFeedView).
FEED_PATH = "/home"

#: Every icon Home draws: the page's own glyphs, the figures' and the
#: priority rows'.
ICON_NAMES = (
    "arrow",
    "bell",
    "bolt",
    "calendar",
    "chart",
    "check",
    "chevron",
    "clock",
    "flag",
    "grid",
    "money",
    "upload",
    "warning",
)


def _role(role: str) -> dict:
    from apps.command_center.home_service import PLAN_ROLES, ROLE_TITLES
    from apps.core.navigation import build_home_shortcuts_for_user, get_user_role_slug
    from apps.core.permissions import RolePermissionService

    user = _role_user(role)
    slug = get_user_role_slug(user) or ""
    return {
        "home": RolePermissionService.can_view_page(user, "home"),
        "slug": slug,
        "title": ROLE_TITLES.get(slug, ""),
        "has_plan": slug in PLAN_ROLES,
        "shortcuts": [
            {
                "label": str(s.get("label") or ""),
                "url": str(s.get("url") or ""),
                "icon": str(s.get("icon") or ""),
            }
            for s in build_home_shortcuts_for_user(user, FEED_PATH)
        ],
    }


def _figures() -> dict:
    from apps.command_center.home_service import PLAN_FIGURES, QUEUE_FIGURES
    from apps.core.metrics.payload import render_precomputed_metric_item

    out = {}
    for spec in (*PLAN_FIGURES, *QUEUE_FIGURES):
        metric_key, helper = spec[1], spec[4]
        item = render_precomputed_metric_item(metric_key, 0)
        out[metric_key] = {
            "label": str(item.get("label") or ""),
            "description": str(item.get("definition") or helper or ""),
        }
    return out


def _choices(field: str) -> dict:
    from apps.activities.models import Activity

    return {
        str(value): str(label)
        for value, label in Activity._meta.get_field(field).choices
    }


#: Where a priority row's link carries the year (urlencoded unchanged).
FY_MARK = "9999"


def _priorities() -> dict:
    from apps.command_center.home_priorities import (
        PAGE_LINES,
        ROLE_ROWS,
        SCHOOL_LISTS,
        SPECS,
        UNREAD_LINE,
        _url,
    )
    from apps.core.navigation import get_user_role_slug
    from apps.core.rbac import EdifyRole

    roles = {}
    for role in EdifyRole:
        slug = get_user_role_slug(_role_user(role.value)) or ""
        if slug not in ROLE_ROWS:
            continue
        rows = []
        for key in ROLE_ROWS[slug]:
            title, one, icon, action, counts = SPECS[key]
            rows.append(
                {
                    "key": key,
                    "title": title,
                    "one": one,
                    "icon": icon,
                    "action": action,
                    "counts": counts,
                    "line": PAGE_LINES.get(key, ""),
                    "url": _url(key, slug, FY_MARK),
                }
            )
        roles[role.value] = rows
    return {
        "roles": roles,
        "school_lists": dict(SCHOOL_LISTS),
        "unread_line": UNREAD_LINE,
        "fy_mark": FY_MARK,
    }


def rules() -> dict:
    from apps.command_center.home_service import PRIORITY_LIMIT, UPCOMING_LIMIT
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed.views import home_icon

    return {
        "roles": {role.value: _role(role.value) for role in EdifyRole},
        "icons": {name: home_icon(name) for name in ICON_NAMES},
        "figures": _figures(),
        "upcoming_limit": UPCOMING_LIMIT,
        "priority_limit": PRIORITY_LIMIT,
        "status_labels": _choices("status"),
        "type_labels": _choices("activity_type"),
        "priorities": _priorities(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write Home's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
