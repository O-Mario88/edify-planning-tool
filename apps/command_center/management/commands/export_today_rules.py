"""Export the Today page's rules for the Go gateway.

Go builds /today (apps.frontend.views.today_views.today_page for a desk role,
partials/today/workbench.html; internal/todaypage) from these: per role,
whether the page opens, where the reader's Today lives
(today_home_url), whether the day is a desk's (no field blocks) and whether
the reader verifies SSA (today_actions.next_ssa_row); the waiting and
exception limits, the grouping of identical To-Dos, the snooze choices; and
each decision adapter (today_actions.ADAPTERS): the To-Do id it matches, what
kind of decision it is, the link it must carry and its operations, each with
its label and the drawer it opens ("{id}" where the record goes).
apps/command_center/test_today_rules_export.py fails when the file and this
application differ.

    python manage.py export_today_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/todaypage/rules.json")
PAGE = "/today"
ID = "{id}"


def _drawer(operation) -> dict:
    """The drawer an operation opens, with "{id}" for the record; whether it
    also carries the row's link query (the coaching log does)."""
    if operation.drawer is None:
        return {"drawer": "", "keeps_query": False}
    bare = operation.drawer(ID, {"action_url": ""})
    asked = operation.drawer(ID, {"action_url": "/x?probe=1"})
    return {"drawer": bare, "keeps_query": asked != bare}


def rules() -> dict:
    from apps.command_center import today_actions
    from apps.command_center.todo_groups import GROUP_MIN, GROUP_PREVIEW
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission
    from apps.frontend.views import today_views

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": bool(can_open_url(user, PAGE))
            and RolePermissionService.can_view_page(user, "today"),
            "home": today_views.today_home_url(user),
            "desk": role.value not in today_views.FIELD_ROLES,
            "verifies_ssa": has_permission(user, Permission.IA_VERIFY.value),
        }
    adapters = []
    for adapter in today_actions.ADAPTERS:
        adapters.append(
            {
                "pattern": adapter.pattern.pattern,
                "kind": adapter.kind,
                "url_contains": adapter.url_contains,
                "operations": [
                    {
                        "key": op.key,
                        "label": op.label,
                        "tone": op.tone,
                        "needs_form": bool(op.reason or op.attest or op.field),
                        **_drawer(op),
                    }
                    for op in adapter.operations
                ],
            }
        )
    return {
        "roles": roles,
        "waiting_limit": today_views.WAITING_LIMIT,
        "exception_limit": today_views.EXCEPTION_LIMIT,
        "group_min": GROUP_MIN,
        "group_preview": GROUP_PREVIEW,
        "snooze_choices": [list(c) for c in today_views.SNOOZE_CHOICES],
        "adapters": adapters,
        "activity_drawer": today_actions._ACTIVITY_DRAWER.pattern,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Today page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
