"""Write costing_oracle.json: activities priced by the existing engine
(apps.budget.costing.cost_for_activity and facilitation_fee_cost), for Go's
port to price the same way.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    ORACLE_OUT=/path/to/costing_oracle.json ORACLE_CASES=20000 \\
    python manage.py shell < platform/backend/internal/costing/testdata/oracle.py

Only against a database whose name ends in "_test", and it writes nothing
there: it reads the live operational rate card inside a transaction it rolls
back. From that card it makes variants (the card itself, the card with rates
dropped, a card that still carries only the renamed keys, a card of ones, an
empty card) and prices seeded random activities over every activity type,
delivery, district, night rate, return day, costing kind, headcount, nights,
days, materials and linked rates on each. internal/costing/oracle_test.go
(EDIFY_COSTING_ORACLE=path) prices the same cases and compares every line.
"""

import json
import os
import random

from django.conf import settings
from django.db import transaction

from apps.budget import costing
from apps.budget.costing_service import _read_rate_card, active_catalogue
from apps.budget.reference import CANONICAL_RATE_KEYS, RATE_ALIASES
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

name = settings.DATABASES["default"]["NAME"]
if not name.endswith("_test"):
    raise SystemExit(
        f"refusing to run against {name}: the oracle runs on a _test database"
    )

out_path = os.environ["ORACLE_OUT"]
cases = int(os.environ.get("ORACLE_CASES", "20000"))
rng = random.Random(20261114)

with transaction.atomic():
    catalogue = active_catalogue()
    live = {}
    if catalogue is not None:
        live, _settings = _read_rate_card(catalogue)
        live = {key: int(value) for key, value in live.items()}
    transaction.set_rollback(True)

if not live:
    raise SystemExit("no live operational rate card on this database")

canonical = sorted(CANONICAL_RATE_KEYS)
renamed_only = {}
for key, olds in RATE_ALIASES.items():
    for old in olds:
        if key in live:
            renamed_only[old] = live[key] + 7
for key in canonical:
    if key not in RATE_ALIASES and key in live:
        renamed_only[key] = live[key]
first_alias = next(iter(RATE_ALIASES))


def dropped(card, share):
    return {k: v for k, v in card.items() if rng.random() > share}


cards = {
    "live": live,
    "live_dropped_10": dropped(live, 0.1),
    "live_dropped_40": dropped(live, 0.4),
    "renamed_only": renamed_only,
    "renamed_and_new": {**renamed_only, first_alias: live.get(first_alias, 0) + 3},
    "ones": dict.fromkeys(canonical, 1),
    "empty": {},
}

types = sorted(
    set(CLUSTER_MEETING_TYPES)
    | set(costing.CLUSTER_TRAINING_TYPES)
    | set(TRAINING_TYPES)
    | set(VISIT_TYPES)
    | set(costing.SSA_WORK_TYPES)
    | set(costing.CORE_WORK_TYPES)
    | {
        "field_event",
        "programme_event",
        "partner_activity",
        "project_activity",
        "ssa_activity",
        "other_work",
        "",
    }
)
kinds = [
    "",
    "core",
    "onetest",
    "tot",
    "student_conference",
    "proprietor_conference",
    "other",
]
accommodations = [
    None,
    "",
    "secondary_accommodation_per_night",
    "management_accommodation_per_night",
    "lunch_per_day",
]


def maybe(value, chance=0.5):
    return value if rng.random() < chance else None


def count():
    return rng.choice([-2, 0, 0, 1, 3, 12, 40])


def activity():
    a = {
        "activityType": rng.choice(types),
        "deliveryType": rng.choice(["staff", "partner", "", "group"]),
        "districtType": rng.choice(["primary", "secondary", "", "mixed"]),
        "accommodationKey": rng.choice(accommodations),
        "returnDay": rng.random() < 0.3,
        "costingKind": rng.choice(kinds),
        "facilitated": rng.random() < 0.3,
        "expectedParticipants": maybe(count(), 0.6),
        "teachersAttended": count(),
        "leadersAttended": count(),
        "otherParticipants": count(),
        "nights": maybe(rng.choice([-1, 0, 1, 2, 3]), 0.5),
        "days": rng.choice([0, 1, 1, 1, 2, 3, 5]),
        "printingPages": rng.choice([0, 0, 4, 25]),
        "photocopyPages": rng.choice([0, 0, 3, 10]),
        "photocopyCopies": rng.choice([0, 2, 30]),
    }
    if rng.random() < 0.15:
        a["linkedRates"] = [
            (
                rng.choice(["activity:x1:snacks", "lunch_per_day", "unknown_rate"]),
                f"Linked {i}",
            )
            for i in range(rng.randint(1, 2))
        ]
    return a


def priced(cost):
    return {
        "amount": cost.amount,
        "cost_missing": cost.cost_missing,
        "missing_items": list(cost.missing_items),
        "lines": [
            {
                "label": line.label,
                "key": line.key,
                "unit": line.unit,
                "qty": line.qty,
                "amount": line.amount,
                "missing": line.missing,
            }
            for line in cost.lines
        ],
    }


rows = []
card_names = sorted(cards)
for i in range(cases):
    card_name = card_names[i % len(card_names)]
    a = activity()
    card = cards[card_name]
    rows.append(
        {
            "card": card_name,
            "activity": {
                **a,
                "linkedRates": [list(p) for p in a.get("linkedRates") or ()],
            },
            "cost": priced(costing.cost_for_activity(a, card)),
            "facilitation_fee": priced(costing.facilitation_fee_cost(a, card)),
        }
    )

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump({"cards": cards, "cases": rows}, fh, ensure_ascii=False)
print(f"wrote {len(rows)} cases over {len(cards)} cards to {out_path}")
