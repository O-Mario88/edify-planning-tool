"""Write the To-Do snooze's rules for the Go gateway.

Go makes the Today queue's Snooze save (apps.frontend.views.today_views.
today_snooze -> apps.command_center.today_actions.snooze, docs/migration/50)
from the vocabularies this command writes to
platform/backend/internal/todosnooze/rules.json: which roles open the Today
page (require_page_permission("today")), which roles the page asks per person
(a partner's team member), the snooze choices and their days, the refusal's
words, and the stored columns' lengths the save cuts the posted values to;
and for undoing a snooze (today_unsnooze), the Today panel the existing
application draws again afterwards, where that answer goes, and the field
that keeps a Programme Lead's redraw to their own day.
A change to any of them must be exported again;
apps/command_center/test_todo_snooze_rules_export.py fails until it is.

    python manage.py export_todo_snooze_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/todosnooze/rules.json")
TODAY_PAGE = "today"


def doors() -> dict:
    """Per role: whether the Today page opens (the view's own gate), and
    whether the gate is asked per person (the partner portal's page map,
    apps.partners.member_scope), which Go hands on."""
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        per_person = get_user_role_slug(user) == "PARTNER"
        out[role.value] = {
            "today": False
            if per_person
            else bool(RolePermissionService.can_view_page(user, TODAY_PAGE)),
            "per_person": per_person,
        }
    return out


def refusal() -> str:
    """The words snooze refuses an unknown choice or an empty item with,
    asked of snooze itself (it refuses before it reads anything)."""
    from apps.command_center import today_actions
    from apps.core.exceptions import BadRequest

    try:
        today_actions.snooze(_role_user("CCEO"), "", "")
    except BadRequest as exc:
        return str(getattr(exc, "detail", None) or exc)
    raise AssertionError("snooze accepted an empty item")


def lengths() -> dict:
    from apps.command_center.models import TodoSnooze

    return {
        "todo_id": TodoSnooze._meta.get_field("todo_id").max_length,
        "title": TodoSnooze._meta.get_field("title").max_length,
    }


def unsnooze() -> dict:
    """Undoing a snooze answers with the whole Today panel drawn again
    (today_unsnooze renders what today_panel renders), retargeted onto the
    panel; the This Week Me tab's field rides along to the redraw."""
    from django.urls import reverse

    from apps.frontend.views import today_views

    return {
        "redraw": reverse("frontend:today_panel"),
        "retarget": today_views.UNSNOOZE_RETARGET,
        "reswap": today_views.UNSNOOZE_RESWAP,
        "section_field": today_views.TODAY_SECTION_FIELD,
    }


def rules() -> dict:
    from apps.command_center.today_actions import SNOOZE_DAYS

    return {
        "doors": doors(),
        "snooze_days": dict(SNOOZE_DAYS),
        "refusal": refusal(),
        "lengths": lengths(),
        "unsnooze": unsnooze(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the To-Do snooze's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
