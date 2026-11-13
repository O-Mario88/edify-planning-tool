"""Write the notification centre's rules for the Go gateway.

Go builds the notification centre (/notifications, apps.frontend.views.
staff_views.notifications_page_view and pages/notifications/index.html) from
the vocabularies this command writes to
platform/backend/internal/notificationcenter/rules.json: who may open the
page, the statuses and priorities a notification takes, the priority the
page calls Critical, the page size, and when email counts as set up. A
change to any of them must be exported again;
apps/notifications/test_notification_center_rules_export.py fails until it
is, so the two can never drift.

The door is not restated: each role's answer is computed here by the gate
the page itself asks.

    python manage.py export_notification_center_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/notificationcenter/rules.json")

PAGE_PATH = "/notifications"

#: The page's permission (require_page_permission on the view).
PAGE_PERMISSION = "dashboard"


def roles() -> dict:
    """Whether each role opens the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, PAGE_PATH)),
        }
    return out


def rules() -> dict:
    from apps.core.enums import MessageStatus, NotificationPriority
    from apps.core.pagination import TABLE_PAGE_SIZE

    return {
        "roles": roles(),
        "statuses": {
            "unread": MessageStatus.UNREAD.value,
            "read": MessageStatus.READ.value,
            "archived": MessageStatus.ARCHIVED.value,
        },
        "status_values": [str(v) for v, _label in MessageStatus.choices],
        "priority_values": [str(v) for v, _label in NotificationPriority.choices],
        # The priority the page draws as Critical and counts as a critical
        # task (the template's `n.priority == 'urgent'`, the view's kpis).
        "critical_priority": NotificationPriority.URGENT.value,
        # The default status filter: everything but archived and resolved.
        "default_status": "all",
        "page_size": TABLE_PAGE_SIZE,
        # apps.core.email.MailerService.is_configured: email is set up when
        # this provider is chosen and its key is present.
        "email_provider": "resend",
        "email_provider_env": "EMAIL_PROVIDER",
        "email_key_env": "RESEND_API_KEY",
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the notification centre's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
