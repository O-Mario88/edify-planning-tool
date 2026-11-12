"""Write the Escalations page's rules for the Go gateway.

Go builds Escalations (/escalations, apps.frontend.views.escalation_views.
escalations_view, apps.flags.escalation_service.board and
pages/escalations/index.html with _table.html) from the vocabularies this
command writes to platform/backend/internal/escalations/rules.json: who may
open the page, the level each role raises to and the level it decides for,
who decides everything and who reads the country's board, the addressee
levels with their labels and the role holding each, the categories,
decisions and severities with their words, how long each severity may wait,
the statuses, the table's page size and the query keys the app's feed never
passes to a page. A change to any of them must be exported again;
apps/flags/test_escalations_rules_export.py fails until it is, so the two can
never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks.

    python manage.py export_escalations_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/escalations/rules.json")

PAGE_PATH = "/escalations"


def roles() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.flags import escalation_service as service

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("escalations") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "escalations")
            and bool(can_open_url(user, PAGE_PATH)),
            # addressee_for: the level this role raises to, if any.
            "raises_to": service.addressee_for(user) or "",
            # ADDRESSEE_FOR_ROLE: the level this role decides for, if any.
            "decides_for": service.ADDRESSEE_FOR_ROLE.get(role.value, ""),
            # Admin decides everything and reads every escalation.
            "decides_all": role.value == EdifyRole.ADMIN.value,
            # visible_to: the Country Director reads what the country's
            # Programme Leads received and what it sent up.
            "reads_country_board": role.value == EdifyRole.COUNTRY_DIRECTOR.value,
        }
    return out


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.flags import escalation_service as service
    from apps.flags.models import (
        EscalationAddressee,
        EscalationSeverity,
        EscalationStatus,
    )
    from apps.mobile_feed.views import NOT_PASSED

    return {
        "roles": roles(),
        "addressee_labels": [
            [str(v), str(label)] for v, label in EscalationAddressee.choices
        ],
        "role_for_addressee": dict(service.ROLE_FOR_ADDRESSEE),
        "programme_lead_level": EscalationAddressee.PROGRAM_LEAD.value,
        "regional_level": EscalationAddressee.REGIONAL_VICE_PRESIDENT.value,
        "categories": [list(pair) for pair in service.CATEGORIES],
        "decisions": [list(pair) for pair in service.DECISIONS],
        "severities": [[str(v), str(label)] for v, label in EscalationSeverity.choices],
        "default_severity": EscalationSeverity.NORMAL.value,
        "sla_days": dict(service.SLA_DAYS),
        "statuses": {
            "open": EscalationStatus.OPEN.value,
            "acknowledged": EscalationStatus.ACKNOWLEDGED.value,
            "resolved": EscalationStatus.RESOLVED.value,
        },
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Escalations page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
