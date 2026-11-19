"""Export the Activity Catalogue page's rules for the Go gateway.

Go builds /settings/activity-catalogue/ (internal/catalogue) from these:
which roles the feed lets open the page, who holds the catalogue's view and
manage permissions, and the labels of a catalogue item's status, activity
type and delivery method, of an SSA intervention and of a mapping mode, in
their order. apps/activity_catalogue/test_activity_catalogue_rules_export.py
fails when the file and this application differ.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/catalogue/rules.json")
PAGE = "/settings/activity-catalogue/"


def _choices(choices) -> list[list[str]]:
    return [[str(value), str(label)] for value, label in choices]


def rules() -> dict:
    from apps.activity_catalogue.models import (
        CatalogueActivityType,
        CatalogueStatus,
        DeliveryMethod,
        MappingMode,
    )
    from apps.core.permissions import can_open_url, has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.ssa.models import SsaIntervention

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": bool(can_open_url(user, PAGE)),
            "view": has_permission(user, Permission.ACTIVITY_CATALOGUE_VIEW.value),
            "manage": has_permission(user, Permission.ACTIVITY_CATALOGUE_MANAGE.value),
        }
    return {
        "roles": roles,
        "statuses": _choices(CatalogueStatus.choices),
        "activity_types": _choices(CatalogueActivityType.choices),
        "delivery_methods": _choices(DeliveryMethod.choices),
        "interventions": _choices(SsaIntervention.choices),
        "mapping_modes": _choices(MappingMode.choices),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Activity Catalogue page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
