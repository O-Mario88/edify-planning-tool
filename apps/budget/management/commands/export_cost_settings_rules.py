"""Write the Cost Catalogue page's rules for Go.

Go builds the Cost Catalogue (/cost-settings) and its read-only door, Cost
Intelligence (/cost-intelligence) (apps.frontend.views.finance_views
.cost_settings_view and pages/cost_settings/index.html) from what this command
writes to platform/backend/internal/costsettings/rules.json: who may open
each door, who reads the reference layer (the cost review queue) and who
manages the rates; the country and the published operational card the page
shows; the Activity Catalogue's costing profiles and the names of its types,
deliveries and interventions; the review reasons and how many reviews the
queue shows; the rate card kinds' names. A change to any of them must be
exported again; apps/budget/test_cost_settings_rules_export.py fails until it
is.

    python manage.py export_cost_settings_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/costsettings/rules.json")
#: The view's own literals.
REVIEW_QUEUE_LIMIT = 20
REVIEW_QUEUE_STATUS = "submitted"
MANAGER_ROLE = "CountryDirector"
DOORS = {"/cost-settings": "cost_settings", "/cost-intelligence": "cost_intelligence"}


def _choices(model, field: str) -> dict:
    return {str(k): str(v) for k, v in model._meta.get_field(field).choices}


def rules() -> dict:
    from django.conf import settings

    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityInterventionMapping,
        CatalogueStatus,
    )
    from apps.budget.costing_service import _COSTING_PROFILES
    from apps.budget.models import (
        ActivityCostReview,
        RateCardKind,
        RateCardStatus,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "doors": sorted(
                path
                for path, page in DOORS.items()
                if RolePermissionService.can_view_page(user, page)
                and bool(can_open_url(user, path))
            ),
            "reference": has_permission(
                user, Permission.RATE_CARD_REFERENCE_VIEW.value
            ),
            "manage": role.value == MANAGER_ROLE,
        }
    return {
        "roles": roles,
        "country": getattr(settings, "COUNTRY", "Uganda"),
        "operational_kind": RateCardKind.OPERATIONAL.value,
        "published_status": RateCardStatus.PUBLISHED.value,
        "kind_labels": {str(k): str(v) for k, v in RateCardKind.choices},
        "active_item_status": CatalogueStatus.ACTIVE.value,
        "costing_profiles": {
            profile: [activity_type, kind or ""]
            for profile, (activity_type, kind) in _COSTING_PROFILES.items()
        },
        "activity_types": _choices(ActivityCatalogueItem, "activity_type"),
        "delivery_methods": _choices(ActivityCatalogueItem, "delivery_method"),
        "interventions": _choices(ActivityInterventionMapping, "intervention"),
        "review_reasons": _choices(ActivityCostReview, "reason_code"),
        "review_queue_status": REVIEW_QUEUE_STATUS,
        "review_queue_limit": REVIEW_QUEUE_LIMIT,
        "table_page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Cost Catalogue page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
