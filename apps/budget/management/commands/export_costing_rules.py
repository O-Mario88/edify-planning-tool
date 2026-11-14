"""Write the costing engine's rules for Go.

Go prices an activity (apps.budget.costing.cost_for_activity) from what this
command writes to platform/backend/internal/costing/rules.json: the canonical
rates in the registry's order with their labels, the rates a card may lack
(charged only when present), the renamed keys each new key answers for (in
order), the meal rates; the day away's required and optional rates by
district, the two accommodation rates, the dinner and what a return day
drops; and the activity types each recipe answers. A change to any of them
must be exported again; apps/budget/test_costing_rules_export.py fails until
it is.

    python manage.py export_costing_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/costing/rules.json")


def rules() -> dict:
    from apps.budget import costing, reference
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.daily_visit_batches import pricing

    return {
        "canonical_rates": [
            [key, str(label)] for key, label, _cost in reference.CANONICAL_RATES
        ],
        "optional_rate_keys": sorted(reference.OPTIONAL_RATE_KEYS),
        "rate_aliases": [
            [key, list(old)] for key, old in reference.RATE_ALIASES.items()
        ],
        "meals_rate_keys": list(costing.MEALS_RATE_KEYS),
        "day": {
            "required": {k: list(v) for k, v in pricing.REQUIRED_KEYS.items()},
            "optional": {k: list(v) for k, v in pricing.OPTIONAL_KEYS.items()},
            "accommodation_key": pricing.ACCOMMODATION_KEY,
            "accommodation_keys": sorted(pricing.ACCOMMODATION_KEYS),
            "dinner_key": pricing.DINNER_KEY,
            "return_day_dropped": sorted(pricing.RETURN_DAY_DROPPED_KEYS),
            "labels": dict(pricing.KEY_LABELS),
        },
        "types": {
            "cluster_meeting": sorted(CLUSTER_MEETING_TYPES),
            "cluster_training": sorted(costing.CLUSTER_TRAINING_TYPES),
            "training": sorted(TRAINING_TYPES),
            "visit": sorted(VISIT_TYPES),
            "ssa_work": sorted(costing.SSA_WORK_TYPES),
            "core_work": sorted(costing.CORE_WORK_TYPES),
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the costing engine's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
