"""Write a day's costing rules, and how they answer, for the Go gateway.

Go prices a staff member's day of field work (docs/migration/35) from what
this command writes to platform/backend/internal/costing/daypool/:

* ``rules.json``: the vocabularies the day's pool is priced from: the
  head-office zone and the field roles (apps.daily_visit_batches.districts),
  the rates each kind of day fetches, the two accommodation rates and whose
  night each is, what the day home drops (apps.daily_visit_batches.pricing),
  the renamed rate keys (apps.budget.reference.RATE_ALIASES) and the
  statuses that draw no money (apps.core.activity_types).
* ``vectors.json``: those rules' own answers, asked of this code over a grid
  of inputs, so Go is checked against what the functions do and not against
  a restatement of them.

A change to either must be exported again;
apps/budget/test_costing_rules_export.py fails until it is.

    python manage.py export_daypool_rules
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand

from apps.budget.reference import RATE_ALIASES
from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.daily_visit_batches import districts, pricing

EXPORT_DIR = Path("platform/backend/internal/costing/daypool")
RULES_PATH = EXPORT_DIR / "rules.json"
VECTORS_PATH = EXPORT_DIR / "vectors.json"


def rules() -> dict:
    return {
        "district": {
            "hq_zone": sorted(districts._HQ_ZONE),
            "field_roles": sorted(districts.FIELD_ROLES),
            "field_role_aliases": sorted(districts._FIELD_ROLE_ALIASES),
            "management_accommodation_roles": sorted(
                districts.MANAGEMENT_ACCOMMODATION_ROLES
            ),
            "primary": districts.PRIMARY,
            "secondary": districts.SECONDARY,
        },
        "pricing": {
            "required_keys": pricing.REQUIRED_KEYS,
            "optional_keys": pricing.OPTIONAL_KEYS,
            "accommodation_key": pricing.ACCOMMODATION_KEY,
            "management_accommodation_key": pricing.MANAGEMENT_ACCOMMODATION_KEY,
            "return_day_dropped_keys": sorted(pricing.RETURN_DAY_DROPPED_KEYS),
            "key_labels": pricing.KEY_LABELS,
            "mixed_transport_label": pricing.MIXED_TRANSPORT_LABEL,
            "day_mark_labels": pricing.DAY_MARK_LABELS,
        },
        "rate_aliases": {key: list(old) for key, old in RATE_ALIASES.items()},
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
    }


# ── The answers ──────────────────────────────────────────────────────────────

_ROLES = [
    None,
    "",
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.ADMIN.value,
    "pl",
    " Program Lead ",
    "PROGRAMME LEAD",
    "cceo",
]
_DISTRICTS = [None, "", "Kampala", " wakiso ", "MUKONO", "Gulu", "gulu", "Lira"]
_RATE_CARDS = [
    {
        "primary_transport_per_day": 50000,
        "secondary_transport_per_day": 90000,
        "lunch_per_day": 12000,
        "secondary_breakfast_per_day": 8000,
        "secondary_overnight_dinner_per_day": 15000,
        "secondary_accommodation_per_night": 70000,
        "management_accommodation_per_night": 110000,
    },
    # A card seeded before the 2026-09-06 list: the lunch and the second
    # night answer from their old keys.
    {
        "primary_transport_per_day": 40000,
        "secondary_transport_per_day": 80001,
        "primary_lunch_per_day": 10001,
        "secondary_breakfast_per_day": 7003,
        "secondary_overnight_dinner_per_day": 14999,
        "secondary_accommodation_per_night": 65000,
    },
    # Missing the secondary breakfast: a secondary day is refused.
    {
        "primary_transport_per_day": 50000,
        "secondary_transport_per_day": 90000,
        "lunch_per_day": 12000,
        "secondary_overnight_dinner_per_day": 15000,
        "secondary_accommodation_per_night": 70000,
    },
    {},
]
_ACCOMMODATION_KEYS = [
    None,
    pricing.ACCOMMODATION_KEY,
    pricing.MANAGEMENT_ACCOMMODATION_KEY,
    "something_else",
]
_PEOPLE = [
    ([], None),
    ([], EdifyRole.CCEO.value),
    ([], EdifyRole.COUNTRY_DIRECTOR.value),
    ([EdifyRole.CCEO.value], EdifyRole.CCEO.value),
    ([EdifyRole.COUNTRY_PROGRAM_LEAD.value], EdifyRole.COUNTRY_PROGRAM_LEAD.value),
    ([EdifyRole.CCEO.value, EdifyRole.ADMIN.value], EdifyRole.CCEO.value),
    (
        [EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value],
        EdifyRole.CCEO.value,
    ),
    ([EdifyRole.HUMAN_RESOURCES.value], EdifyRole.HUMAN_RESOURCES.value),
    ([EdifyRole.PARTNER_ADMIN.value], EdifyRole.PARTNER_ADMIN.value),
]


def _resolve(role, primary, target) -> str:
    try:
        return districts.resolve_district_type(role, primary, target)
    except ValueError:
        return "error"


def _pool(rates, district_type, accommodation_key, return_day) -> dict:
    try:
        return {
            "pool": pricing.compute_daily_pool(
                rates, district_type, accommodation_key, return_day=return_day
            )
        }
    except BadRequest as refusal:
        return {"refused": str(refusal)}


def vectors() -> dict:
    people = [{"roles": roles, "active_role": active} for roles, active in _PEOPLE]
    return {
        "resolve_district_type": [
            {
                "role": role,
                "primary": primary,
                "target": target,
                "answer": _resolve(role, primary, target),
            }
            for role, primary, target in product(_ROLES, _DISTRICTS, _DISTRICTS)
        ],
        "hq_district_type": [
            {"district": d, "answer": districts.hq_district_type(d)} for d in _DISTRICTS
        ],
        "day_district_mark": [
            {"types": list(types), "answer": pricing.day_district_mark(types)}
            for types in [
                [],
                [None],
                ["primary"],
                ["secondary"],
                ["primary", "primary"],
                ["secondary", "secondary"],
                ["primary", "secondary"],
                [None, "secondary"],
                ["", "secondary", "primary"],
            ]
        ],
        "day_keys": [
            {
                "district_type": district_type,
                "accommodation_key": key,
                "return_day": return_day,
                "answer": pricing.day_keys(district_type, key, return_day=return_day),
            }
            for district_type, key, return_day in product(
                ["primary", "secondary"], _ACCOMMODATION_KEYS, [False, True]
            )
        ],
        "compute_daily_pool": [
            {
                "rates": rates,
                "district_type": district_type,
                "accommodation_key": key,
                "return_day": return_day,
                **_pool(rates, district_type, key, return_day),
            }
            for rates, district_type, key, return_day in product(
                _RATE_CARDS,
                ["primary", "secondary"],
                _ACCOMMODATION_KEYS,
                [False, True],
            )
        ],
        "allocate_pool": [
            {"pool": pool, "n": n, "answer": pricing.allocate_pool(pool, n)}
            for pool, n in product(
                [
                    {"primary_transport_per_day": 50000, "lunch_per_day": 12001},
                    {"secondary_transport_per_day": 7, "lunch_per_day": 0},
                ],
                range(0, 8),
            )
        ],
        "accommodation_key_for_user": [
            {
                **person,
                "answer": districts.accommodation_key_for_user(
                    SimpleNamespace(**person)
                ),
            }
            for person in people
        ],
        "holds_field_role": [
            {
                **person,
                "answer": districts.holds_field_role(SimpleNamespace(**person)),
            }
            for person in people
        ],
    }


def rendered_rules() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


def rendered_vectors() -> str:
    return json.dumps(vectors(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write a day's costing rules, and their answers, for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        RULES_PATH.write_text(rendered_rules(), encoding="utf-8")
        VECTORS_PATH.write_text(rendered_vectors(), encoding="utf-8")
        self.stdout.write(f"Wrote {RULES_PATH} and {VECTORS_PATH}")
