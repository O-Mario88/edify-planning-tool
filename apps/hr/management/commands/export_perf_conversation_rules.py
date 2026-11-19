"""Export the Performance Conversation's rules for the Go gateway.

Go builds /performance-conversation (internal/perfconversation) from these:
which roles open the page, the title of each window a cycle opens, the five
ratings, the kinds of value commitment, whom each role is reviewed by and
the People states a reviewer must be in, and the roles holding the HR
channel. apps/hr/test_perf_conversation_rules_export.py fails when the file
and this application differ.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/perfconversation/rules.json")
PAGE = "/performance-conversation"


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.hr_views import (
        CONVERSATION_HR_ROLES,
        CONVERSATION_WINDOW_LABELS,
    )
    from apps.hr.models import PerformanceRating, ValueCommitment
    from apps.hr.review_authority import LIVE_STATES, REVIEWER_ROLE_FOR

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = bool(
            RolePermissionService.can_view_page(user, "performance_conversations")
            and can_open_url(user, PAGE)
        )
    return {
        "roles": roles,
        "window_labels": CONVERSATION_WINDOW_LABELS,
        "ratings": [[value, str(label)] for value, label in PerformanceRating.choices],
        "value_kinds": {
            value: str(label)
            for value, label in ValueCommitment._meta.get_field("kind").choices
        },
        "reviewer_roles": {
            str(role): [str(r) for r in reviewers]
            for role, reviewers in REVIEWER_ROLE_FOR.items()
        },
        "live_states": list(LIVE_STATES),
        "hr_roles": list(CONVERSATION_HR_ROLES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Performance Conversation's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
