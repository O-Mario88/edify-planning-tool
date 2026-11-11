"""Write the acting leadership policy for the Go gateway.

Go owns acting appointments (owner brief, 2026-11-11: "acting leadership").
It reads who may appoint whom, the labels, and what each appointment
delegates and withholds from platform/backend/internal/acting/acting_policy.json,
which this command writes from apps.acting.policy.ACTING_ROLES. A change to
the policy here must be exported again; apps/acting/tests/test_policy_export.py
fails until it is, so the two can never drift.

    python manage.py export_acting_policy
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.acting.policy import ACTING_ROLES, ActingRole

EXPORT_PATH = Path("platform/backend/internal/acting/acting_policy.json")


def granted(entry: ActingRole) -> dict:
    """What an appointment grants, as ``services.grant_snapshot`` records it
    beside the seat."""
    return {
        "delegated_write_pages": sorted(entry.delegated_write_pages),
        "follow_up_actions": sorted(entry.follow_up_views or ()),
        "withheld_actions": sorted(entry.withheld_views),
        "delegated_read_pages": sorted(entry.delegated_read_pages),
        "withheld_pages": sorted(entry.withheld_pages),
        "withheld_permissions": sorted(entry.withheld_permission_values()),
        "withheld_authorities": sorted(entry.withheld_authorities),
    }


def policy() -> dict:
    return {
        "roles": [
            {
                "key": entry.key,
                "acting_role": entry.acting_role_value,
                "appointee_role": entry.appointee_role.value,
                "appointer_role": entry.appointer_role.value,
                "scope_type": entry.scope_type,
                "label": entry.label,
                "short_label": entry.short_label,
                "scope_label": entry.scope_label,
                "granted": granted(entry),
            }
            for entry in ACTING_ROLES.values()
        ]
    }


def rendered() -> str:
    return json.dumps(policy(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the acting leadership policy for the Go gateway."

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / EXPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
