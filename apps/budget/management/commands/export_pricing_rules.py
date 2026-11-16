"""Write the save-time pricing rules for Go.

Go prices a stored activity read-only, as the single cost writer would
(apps.activities.services._costing_input, then
apps.budget.costing_service.calculate_dual), from what this command writes to
platform/backend/internal/pricing/rules.json: the Activity Catalogue's
costing profiles; which roles are field staff (read against their primary
district) and the head-office zone everyone else is read against; whose night
away is paid at the second accommodation rate, and the two rates; and which
rate cards price work (the country, the kinds and the published status);
and for the day a visit shares: the activity statuses that draw no money,
the types whose personal per-diems join the day, and the name of a Mixed
day's transport; and which way a stored activity is priced: the trainings a
delivery online makes free, the statuses that mean an in-school Training's
visit no longer makes the journey, and the states of a week's request in
which its days may still be priced again. The
recipe itself is internal/costing (export_costing_rules). A change to any of
them must be exported again; apps/budget/test_pricing_rules_export.py fails
until it is.

    python manage.py export_pricing_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/pricing/rules.json")


def rules() -> dict:
    from django.conf import settings

    from apps.activities import online_training, pair_costing
    from apps.budget.costing_service import _COSTING_PROFILES
    from apps.fund_requests.weekly_service import REBUILDABLE_WEEKLY_STATUSES
    from apps.budget.models import RateCardKind, RateCardStatus
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.daily_visit_batches import districts, pricing

    return {
        "costing_profiles": {
            profile: [activity_type, kind or ""]
            for profile, (activity_type, kind) in _COSTING_PROFILES.items()
        },
        "hq_primary_districts": list(districts.HQ_PRIMARY_DISTRICTS),
        "field_roles": sorted(districts.FIELD_ROLES),
        "field_role_aliases": sorted(districts._FIELD_ROLE_ALIASES),
        "management_accommodation_roles": sorted(
            districts.MANAGEMENT_ACCOMMODATION_ROLES
        ),
        "accommodation_key": pricing.ACCOMMODATION_KEY,
        "management_accommodation_key": pricing.MANAGEMENT_ACCOMMODATION_KEY,
        "country": getattr(settings, "COUNTRY", "Uganda"),
        "operational_kind": RateCardKind.OPERATIONAL.value,
        "reference_kind": RateCardKind.REFERENCE.value,
        "published_status": RateCardStatus.PUBLISHED.value,
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "daily_batch_eligible_types": sorted(pricing.DAILY_BATCH_ELIGIBLE_TYPES),
        "day_pool_extra_types": sorted(pricing.DAY_POOL_EXTRA_TYPES),
        "mixed_transport_label": pricing.MIXED_TRANSPORT_LABEL,
        "online_training_types": sorted(online_training.ONLINE_TRAINING_TYPES),
        "online_mode": online_training.ONLINE,
        "companion_gone_statuses": list(pair_costing.COMPANION_GONE_STATUSES),
        "rebuildable_weekly_statuses": list(REBUILDABLE_WEEKLY_STATUSES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the save-time pricing rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
