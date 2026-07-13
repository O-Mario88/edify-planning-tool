"""
Pure cost-splitting math for Daily Visit Batch pricing. No DB writes, no
imports of models from this app — apps/daily_visit_batches/services.py is the
only writer.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

# Activity types eligible for Daily Visit Batch grouping. Deliberately equal to
# apps.activities.services.SCHOOL_VISIT_TYPES minus "core_visit" (which has its
# own separate flat-rate costing lane tied to Core Schools/Salesforce tracking
# and must not be pooled here).
DAILY_BATCH_ELIGIBLE_TYPES = {
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
}

REQUIRED_KEYS = {
    "primary": ["primary_transport_per_day", "primary_lunch_per_day"],
    "secondary": [
        "secondary_transport_per_day",
        "secondary_lunch_per_day",
        "secondary_accommodation_per_night",
        "secondary_overnight_dinner_per_day",
    ],
}
OPTIONAL_KEYS = {
    "primary": [],
    "secondary": ["secondary_breakfast_per_day", "secondary_incidentals_per_day"],
}

# Human labels for the new cost-component keys, used on ActivityScheduleCostLine.label.
KEY_LABELS = {
    "primary_transport_per_day": "Transport (shared, primary district)",
    "primary_lunch_per_day": "Lunch (shared, primary district)",
    "secondary_transport_per_day": "Transport (shared, secondary district)",
    "secondary_lunch_per_day": "Lunch (shared, secondary district)",
    "secondary_accommodation_per_night": "Accommodation (shared, secondary district)",
    "secondary_overnight_dinner_per_day": "Overnight dinner (shared, secondary district)",
    "secondary_breakfast_per_day": "Breakfast (shared, secondary district)",
    "secondary_incidentals_per_day": "Incidentals (shared, secondary district)",
}


def compute_daily_pool(rates: dict[str, int], district_type: str) -> dict[str, int]:
    """Return {key: unit_rate} for every required key, plus optional keys the
    CD has configured. Raises BadRequest naming the exact missing key(s) if
    any REQUIRED key is absent from the active Cost Catalogue."""
    missing = [k for k in REQUIRED_KEYS[district_type] if k not in rates]
    if missing:
        raise BadRequest(
            f"Cost Catalogue is missing required rate(s) for {district_type} district "
            f"visits: {', '.join(missing)}. Ask the CD to add them in Cost Settings."
        )
    pool = {k: rates[k] for k in REQUIRED_KEYS[district_type]}
    for k in OPTIONAL_KEYS[district_type]:
        if k in rates:
            pool[k] = rates[k]
    return pool


def allocate_component(total: int, n: int) -> list[int]:
    """Split an integer amount across n schools so the sum stays EXACT (no
    lost shillings to rounding). Remainder shillings go to the first
    `remainder` schools in the caller's ordering — deterministic, stable."""
    if n <= 0:
        return []
    base, remainder = divmod(total, n)
    return [base + 1 if i < remainder else base for i in range(n)]


def allocate_pool(pool: dict[str, int], n: int) -> list[dict[str, int]]:
    """Return a list of n dicts {key: allocated_amount}, index i corresponding
    to the i-th school in the caller's stable ordering. Every cost component
    is divided independently (not the pool total), so Transport, Lunch,
    Accommodation, and Dinner each show their own fair per-school share."""
    per_key_allocations = {k: allocate_component(v, n) for k, v in pool.items()}
    return [{k: per_key_allocations[k][i] for k in pool} for i in range(n)]
