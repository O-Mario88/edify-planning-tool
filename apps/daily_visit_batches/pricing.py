"""
Pure cost-splitting math for Daily Visit Batch pricing. No DB writes, no
imports of models from this app — apps/daily_visit_batches/services.py is the
only writer.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

# Staff school visits share one daily travel pool, including core visits.
DAILY_BATCH_ELIGIBLE_TYPES = {
    "school_visit",
    "core_visit",
    "baseline_ssa_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "donor_visit",
    "story_gathering_visit",
    "school_invitation",
    "social_visit",
    "training_follow_up_visit",
    "in_school_coaching_visit",
    "school_visit_ssa_collection",
    "core_assessment_visit",
    "partner_ssa_collection",
}

# The staff member's day carries ONE mission cost — transport and personal
# per-diems accrue per DAY, never per activity (owner rule, 2026-08-19). So
# trainings, cluster sessions and single-day field events join the same day
# pool as visits. In-school training uses the visit recipe; other training adds
# participant meals and venue costs, while cluster training also adds
# facilitation. An in-school training scheduled with its School Visit costs
# nothing: the visit is the journey (apps.activities.pair_costing). Multi-day
# field events stay on their standalone per-day recipe — they own their whole
# away-days by definition.
DAY_POOL_EXTRA_TYPES = {
    "training",
    "core_training",
    "programme_event",
    "in_school_training",
    "school_improvement_training",
    "cluster_training",
    "cluster_training_ssa_collection",
    "cluster_meeting",
    "cluster_meeting_ssa_review",
    "field_event",
}

# Members whose activity-specific recipe is written ON TOP of the pool share
# (a field event has no activity-specific components — its whole cost is the
# per-diem pool share).
POOL_PLUS_RECIPE_TYPES = DAY_POOL_EXTRA_TYPES - {"field_event", "in_school_training"}

# The 2026-09-06 catalogue: transport by district, one Lunch, and in a
# secondary district the overnight set — Dinner, Accommodation per night and
# Breakfast. (Incidentals left the catalogue with the owner's list.)
REQUIRED_KEYS = {
    "primary": ["primary_transport_per_day", "lunch_per_day"],
    # Owner, 2026-09-12: "transport for secondary district + Lunch +
    # breakfast + Dinner + Accommodation then divide by the number of
    # schools planned for that day". Breakfast used to be optional.
    "secondary": [
        "secondary_transport_per_day",
        "lunch_per_day",
        "secondary_breakfast_per_day",
        "secondary_overnight_dinner_per_day",
        "secondary_accommodation_per_night",
    ],
}
OPTIONAL_KEYS: dict[str, list[str]] = {
    "primary": [],
    "secondary": [],
}

# The night away is paid at one of two rates, by who travels (owner,
# 2026-10-05): a CCEO's, which REQUIRED_KEYS names, or the one set for the
# Program Lead, the Country Director, Impact Assessment and the Accountant.
# apps.daily_visit_batches.districts.accommodation_key_for_staff picks it.
ACCOMMODATION_KEY = "secondary_accommodation_per_night"
MANAGEMENT_ACCOMMODATION_KEY = "management_accommodation_per_night"
ACCOMMODATION_KEYS = frozenset({ACCOMMODATION_KEY, MANAGEMENT_ACCOMMODATION_KEY})

# Human labels for the cost-component keys, used on ActivityScheduleCostLine.label.
KEY_LABELS = {
    "primary_transport_per_day": "Transport Primary District",
    "secondary_transport_per_day": "Transport Secondary District",
    "lunch_per_day": "Lunch",
    ACCOMMODATION_KEY: "Accommodation",
    MANAGEMENT_ACCOMMODATION_KEY: "Accommodation",
    "secondary_overnight_dinner_per_day": "Dinner",
    "secondary_breakfast_per_day": "Breakfast",
}


# What the day a traveller comes home does not carry (owner, 2026-10-05:
# "the fifth day they travel back and sleep and eat dinner from home. But
# transport, breakfast and lunch remains"). Which day that is, is
# apps.daily_visit_batches.return_day.
DINNER_KEY = "secondary_overnight_dinner_per_day"
RETURN_DAY_DROPPED_KEYS = ACCOMMODATION_KEYS | {DINNER_KEY}


def day_keys(
    district_type: str,
    accommodation_key: str | None = None,
    *,
    return_day: bool = False,
) -> list[str]:
    """The rates one day away fetches, with the traveller's accommodation.

    An accommodation key that is not one of the two is ignored rather than
    priced: the day then fetches the CCEO's, as it did before the split. The
    day the traveller comes home (`return_day`) fetches neither a night nor a
    dinner."""
    if accommodation_key not in ACCOMMODATION_KEYS:
        accommodation_key = ACCOMMODATION_KEY
    keys = [
        accommodation_key if key == ACCOMMODATION_KEY else key
        for key in REQUIRED_KEYS[district_type]
    ]
    if return_day:
        keys = [key for key in keys if key not in RETURN_DAY_DROPPED_KEYS]
    return keys


def compute_daily_pool(
    rates: dict[str, int],
    district_type: str,
    accommodation_key: str | None = None,
    *,
    return_day: bool = False,
) -> dict[str, int]:
    """Return {key: unit_rate} for every required key, plus optional keys the
    CD has configured. Raises BadRequest naming the exact missing key(s) if
    any REQUIRED key is absent from the active Cost Catalogue.

    `accommodation_key` is the traveller's accommodation rate; left out, the
    night is the CCEO's. `return_day` is the day they come home, which has
    no night and no dinner."""
    from apps.budget.reference import with_rate_aliases

    rates = with_rate_aliases(rates)
    required = day_keys(district_type, accommodation_key, return_day=return_day)
    missing = [k for k in required if k not in rates]
    if missing:
        raise BadRequest(
            f"Cost Catalogue is missing required rate(s) for {district_type} district "
            f"visits: {', '.join(missing)}. Ask the CD to add them in Cost Settings."
        )
    pool = {k: rates[k] for k in required}
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
