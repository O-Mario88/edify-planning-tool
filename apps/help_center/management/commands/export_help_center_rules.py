"""Export the Knowledge Center's rules for the Go gateway.

Go builds the Knowledge Center's reading pages (/help and its articles,
categories, troubleshooting, glossary, release notes and search;
internal/helpcenter) from these: which roles the site lets open them and
which the view's page permission lets read them, the role each role-guide
address names (help_center.views._role_from_slug), each role's own guide
(slug_for_role), the search synonyms and the states an article is read in.
apps/help_center/test_help_center_rules_export.py fails when the file and
this application differ.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/helpcenter/rules.json")
PAGE = "/help"


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.help_center import services
    from apps.help_center.models import HelpArticleState

    roles = {}
    guide_roles: dict[str, str] = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": bool(can_open_url(user, PAGE)),
            "view": RolePermissionService.can_view_page(user, "help"),
            "guide": services.slug_for_role(role.value),
        }
        for candidate in (slugify(role.value), slugify(role.name), role.value.lower()):
            guide_roles.setdefault(candidate, role.value)
    return {
        "roles": roles,
        "guide_roles": guide_roles,
        "synonyms": dict(services.SYNONYMS),
        "readable_states": [
            HelpArticleState.PUBLISHED.value,
            HelpArticleState.REVIEW_DUE.value,
        ],
        "published": HelpArticleState.PUBLISHED.value,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Knowledge Center's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
