"""Write the My Actions page's rules for the Go gateway.

Go builds My Actions (/actions/mine, apps.frontend.views.action_views.
my_actions_view, apps.planning.action_workspace.actions_received) and Actions
Sent (/actions/sent, actions_sent_view, actions_sent), both drawn by
pages/actions/workspace.html and partials/actions/table.html, from the
vocabularies this command writes to
platform/backend/internal/myactions/rules.json: who may open the page and the
workspace strip each role is shown above it, the tabs, the issue labels, each
state's label and tone, the states that are active, overdue, escalated and
resolved, how many rows the queue reads, the table's page size and the query
keys the app's feed never passes to a page. A change to any of them must be
exported again; apps/planning/test_my_actions_rules_export.py fails until it
is, so the two can never drift.

The doors and the strip are not restated: each role's answer is computed here
by the gates the page itself asks, and the strip is the workspace template
rendered for that role and read by the feed's own reader.

    python manage.py export_my_actions_rules
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import (
    partner_team_members,
    strip,
)
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/myactions/rules.json")

PAGE_PATH = "/actions/mine"

SENT_PATH = "/actions/sent"


def roles(permission: str = "my_actions", path: str = PAGE_PATH) -> dict:
    """What each role is given on a page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission(permission) and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, permission)
            and bool(can_open_url(user, path)),
            "strip": strip(user, path, "partials/_section_nav.html"),
        }
    return out


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.mobile_feed.views import NOT_PASSED
    from apps.planning import action_workspace as workspace
    from apps.planning.action_models import ACTIVE_STATES, ActionState

    return {
        "roles": roles(),
        "tabs": [list(tab) for tab in workspace.TABS],
        "issue_labels": dict(workspace.ISSUE_LABELS),
        "state_tones": {
            str(state): list(pair) for state, pair in workspace._STATE_TONE.items()
        },
        "active_states": sorted(str(s) for s in ACTIVE_STATES),
        "overdue_state": ActionState.OVERDUE.value,
        "escalated_state": ActionState.ESCALATED.value,
        "resolved_state": ActionState.RESOLVED.value,
        "row_limit": inspect.signature(workspace.actions_received)
        .parameters["limit"]
        .default,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
        "partner_team_members": partner_team_members("my_actions"),
        # Actions Sent (actions_sent_view, actions_sent): the same rows read
        # from the sender's end, behind its own page permission.
        "sent_roles": roles("actions_sent", SENT_PATH),
        "sent_partner_team_members": partner_team_members("actions_sent"),
        "sent_row_limit": inspect.signature(workspace.actions_sent)
        .parameters["limit"]
        .default,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the My Actions page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
