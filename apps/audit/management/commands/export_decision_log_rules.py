"""Write the Decision Log page's rules for the Go gateway.

Go builds the Decision Log (/decision-log, apps.frontend.views.decision_views.
decision_log_view, apps.audit.decision_log_service.decision_log and
partials/analytics/panels/decision_log.html in the analytics workspace) from
the vocabularies this command writes to
platform/backend/internal/decisionlog/rules.json: who may open the page, whose
decisions each role reads and how that is named, the workspace strip a role
is shown above the page, the decision groups and the actions in each, their
labels, the payload keys a subject is read from, the lookback windows, the
row cap, the table's page size and the query keys the app's feed never passes
to a page. A change to any of them must be exported again;
apps/audit/test_decision_log_rules_export.py fails until it is, so the two
can never drift.

The doors and the strip are not restated: each role's answer is computed here
by the gates the page itself asks, and the strip is the workspace template
rendered for that role and read by the feed's own reader.

    python manage.py export_decision_log_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/decisionlog/rules.json")

PAGE_PATH = "/decision-log"


def strip(user, path: str, template: str):
    """The workspace strip the page shows ``user`` at ``path``, as the feed
    reads it (a linkTabs block), or None when there is none."""
    from django.template.loader import render_to_string

    from apps.core.navigation import build_workspace
    from apps.mobile_feed import page_blocks

    html = render_to_string(template, {"workspace": build_workspace(user, path)})
    blocks = page_blocks.read(html)["blocks"]
    return blocks[0]["linkTabs"] if blocks else None


def partner_team_members(page_key: str) -> dict:
    """Whether a partner's team member (a login on a team it does not lead)
    is refused the page, and which roles are a partner's
    (apps.partners.member_scope.page_withheld)."""
    from apps.partners import member_scope

    return {
        "withheld": page_key in member_scope.MEMBER_WITHHELD_PAGES,
        "roles": list(member_scope._PARTNER_ROLES),
    }


def roles() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.audit import decision_log_service as service
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        if role.value in service.GLOBAL_READERS:
            reach = "global"
        elif role.value in service.COUNTRY_READERS:
            reach = "country"
        else:
            reach = "own"
        out[role.value] = {
            # require_page_permission("decision_log") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "decision_log")
            and bool(can_open_url(user, PAGE_PATH)),
            "reach": reach,
            "scope_label": service._scope_label(role.value),
            "strip": strip(user, PAGE_PATH, "partials/analytics/tab_rail.html"),
        }
    return out


def rules() -> dict:
    from apps.audit import decision_log_service as service
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.mobile_feed.views import NOT_PASSED

    return {
        "roles": roles(),
        "groups": [
            [name, list(actions)] for name, actions in service.DECISION_ACTIONS.items()
        ],
        "labels": dict(service.ACTION_LABELS),
        "detail_keys": list(service.DETAIL_KEYS),
        "day_options": list(service.DAY_OPTIONS),
        "default_days": service.DEFAULT_DAYS,
        "max_days": service.MAX_DAYS,
        "row_limit": service.ROW_LIMIT,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
        "partner_team_members": partner_team_members("decision_log"),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Decision Log page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
