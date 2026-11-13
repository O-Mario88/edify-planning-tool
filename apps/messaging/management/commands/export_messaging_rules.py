"""Write the Messages inbox's rules for the Go gateway.

The Go gateway builds the Messages inbox's thread list for the web app
(docs/migration/42-messages.md) from the vocabularies this command writes to
platform/backend/internal/messaging/rules.json: the inbox's tabs and page
size, the Message Rules card, the record kinds a thread can be about and
their badges, the kinds each tab and each role rule reads, who may open the
page, and each role's slug. A change to any of them must be exported again;
apps/messaging/test_messaging_rules_export.py fails until it is, so the two
can never drift.

The role answers are not restated: each is computed here by the gates the
page itself asks (RolePermissionService.can_view_page, get_user_role_slug).

    python manage.py export_messaging_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/messaging/rules.json")


def _roles() -> dict:
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole

    return {
        role.value: {
            "page": RolePermissionService.can_view_page(
                _role_user(role.value), "messages"
            ),
            "slug": get_user_role_slug(_role_user(role.value)),
        }
        for role in EdifyRole
    }


def rules() -> dict:
    from apps.frontend.views import message_views
    from apps.messaging import services
    from apps.messaging.models import MessageParticipant
    from apps.schools import data_gaps

    return {
        "activity_contexts": sorted(services.ACTIVITY_CONTEXTS),
        "allow_cd_operational_planning": bool(
            getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False)
        ),
        "context_labels": dict(services.CONTEXT_LABELS),
        "field_roles": list(data_gaps.FIELD_ROLES),
        "finance_contexts": sorted(services.FINANCE_CONTEXTS),
        "fund_request_readers": sorted(services._FUND_REQUEST_READERS),
        "ia_contexts": sorted(services.IA_CONTEXTS),
        "ia_unresolved_roles": sorted(services._IA_UNRESOLVED_ROLES),
        "leave_readers": sorted(services._LEAVE_READERS),
        "partner_assignment_readers": sorted(services._PARTNER_ASSIGNMENT_READERS),
        "partner_assignment_scoped": sorted(services._PARTNER_ASSIGNMENT_SCOPED),
        "message_rules": list(message_views.MESSAGE_RULES),
        "page_size": message_views.PAGE_SIZE,
        "partner_roles": sorted(services.PARTNER_ROLES),
        "recipient_to": MessageParticipant.TO,
        "roles": _roles(),
        "stage_contexts": {
            key: sorted(roles) for key, roles in services._STAGE_CONTEXTS.items()
        },
        "tabs": [list(tab) for tab in message_views.TABS],
        "time_zone": settings.TIME_ZONE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Messages inbox's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
