"""Cost reference data: the active catalogue and the canonical rate keys.

Nothing in the platform can cost an activity without these. Planning resolves a
rate by key, the weekly request sums those rates, the budget snapshots them —
and every one of those paths treats a missing key as "no cost", not as an
error, so an empty rate card produces a plan that silently costs nothing.

Like the target areas, these rows arrived through data migrations, which a
flushed database never replays. `ensure_cost_reference` runs on `post_migrate`
— emitted after `flush` as well as after `migrate` — so they come back the
moment they are removed.

It only ever creates. A rate the Country Director has changed is their
decision, and a deploy must not quietly reset it to the default.
"""

from __future__ import annotations

# Daily Visit Batch pools (migration 0005). key, label, default UGX.
DAILY_BATCH_RATES: tuple[tuple[str, str, int], ...] = (
    ("primary_transport_per_day", "Primary district daily transport pool", 50000),
    ("primary_lunch_per_day", "Primary district daily lunch pool", 12000),
    ("secondary_transport_per_day", "Secondary district daily transport pool", 80000),
    ("secondary_lunch_per_day", "Secondary district daily lunch pool", 12000),
    (
        "secondary_accommodation_per_night",
        "Secondary district accommodation per night",
        40000,
    ),
    (
        "secondary_overnight_dinner_per_day",
        "Secondary district overnight dinner",
        12000,
    ),
    ("secondary_breakfast_per_day", "Secondary district breakfast (optional)", 8000),
    (
        "secondary_incidentals_per_day",
        "Secondary district incidentals (optional)",
        5000,
    ),
)

# Cluster meeting and group training recipe (migration 0007).
CLUSTER_ACTIVITY_RATES: tuple[tuple[str, str, int], ...] = (
    ("cluster_meeting_participant_meal_cost_per_head", "Participant snacks", 10000),
    ("group_training_participant_meal_cost_per_head", "Participant meals", 5000),
    ("group_training_facilitation_fee", "Facilitation fee", 50000),
    ("group_training_venue_cost", "Venue fee", 30000),
)

# Activity-specific rates that do not overlap the visit-day pools or the
# cluster/training recipe.  Keeping these in the same registry means the
# catalogue initializer, post-migrate restore, API and management page all
# agree on the exact editable surface.
DIRECT_ACTIVITY_RATES: tuple[tuple[str, str, int], ...] = (
    (
        "partner_training_lump_sum",
        "Partner training/facilitation rate",
        16000,
    ),
    ("partner_visit_lump_sum", "Partner visit rate", 40000),
    ("core_school_visit", "Core school visit cost", 50000),
    ("core_school_training", "Core school training cost", 250000),
    ("ssa_visit_rate", "SSA visit cost", 50000),
    (
        "project_partner_lump_sum",
        "Special project partner activity rate",
        40000,
    ),
)

# Non-school programme event recipe (conferences, camps, exhibitions,
# launches, workshops). Venue + participant meals are the demanded core; the
# optional components price only when the CD keeps a rate for them.
PROGRAMME_EVENT_RATES: tuple[tuple[str, str, int], ...] = (
    ("programme_venue_per_day", "Programme event venue (per day)", 300000),
    (
        "programme_participant_meal_cost_per_head",
        "Programme participant meals (per head per day)",
        15000,
    ),
    ("programme_facilitation_per_day", "Programme facilitation (per day)", 100000),
    ("programme_transport_per_day", "Programme transport (per day)", 100000),
    (
        "programme_materials_per_participant",
        "Programme materials (per participant)",
        5000,
    ),
    (
        "programme_accommodation_per_night",
        "Programme accommodation (per night)",
        80000,
    ),
)

CANONICAL_RATES = (
    DAILY_BATCH_RATES
    + CLUSTER_ACTIVITY_RATES
    + DIRECT_ACTIVITY_RATES
    + PROGRAMME_EVENT_RATES
)
CANONICAL_RATE_KEYS = frozenset(key for key, _label, _cost in CANONICAL_RATES)

# These keys remain in old schedule snapshots and, on upgraded installations,
# may remain as CostSetting rows for audit.  They are not editable or used for
# new costing.  Each visit allowance now has one source of truth in the
# district-specific Daily Visit Batch rates above.
LEGACY_VISIT_COST_KEYS = frozenset(
    {
        "staff_visit_transport_primary",
        "staff_visit_transport_secondary",
        "breakfast",
        "lunch",
        "dinner",
        "accommodation",
    }
)
LEGACY_CLUSTER_ACTIVITY_COST_KEYS = frozenset(
    {
        "cluster_meeting_cost",
        "meals_per_participant",
        "mobilisation_per_participant",
        "training_session_fee",
        "venue",
    }
)
RETIRED_COST_SETTING_KEYS = LEGACY_VISIT_COST_KEYS | LEGACY_CLUSTER_ACTIVITY_COST_KEYS


def ensure_active_catalogue():
    """Return the active CostCatalogue, creating one for the operational FY.

    A rate with no catalogue cannot be snapshotted, and a snapshot is what
    makes a costed activity auditable after the rate changes.
    """
    from django.conf import settings

    from apps.budget.models import CostCatalogue

    active = (
        CostCatalogue.objects.filter(is_active=True).order_by("-fy", "-version").first()
    )
    if active is not None:
        return active

    fy = getattr(settings, "OPERATIONAL_FY", None)
    if not fy:
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
    country = getattr(settings, "COUNTRY", "Uganda")
    return CostCatalogue.objects.create(
        country=country,
        fy=str(fy),
        version=1,
        is_active=True,
        label=f"{country} FY{fy} Country Cost Catalogue",
    )


def ensure_cost_reference(catalogue=None) -> int:
    """Create any missing canonical rate. Returns how many were created."""
    from apps.budget.models import CostSetting

    catalogue = catalogue or ensure_active_catalogue()
    created = 0
    for key, label, default_cost in CANONICAL_RATES:
        rate, was_created = CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": default_cost,
                "fy": catalogue.fy,
                "version": 1,
                "catalogue": catalogue,
            },
        )
        if not was_created and rate.catalogue_id is None:
            rate.catalogue = catalogue
            rate.fy = rate.fy or catalogue.fy
            rate.save(update_fields=["catalogue", "fy", "updated_at"])
        created += int(was_created)
    return created


def cost_reference_is_complete() -> bool:
    """Read-only counterpart to ``ensure_cost_reference``."""
    from apps.budget.models import CostCatalogue, CostSetting

    if not CostCatalogue.objects.filter(is_active=True).exists():
        return False
    present = set(
        CostSetting.objects.filter(key__in=CANONICAL_RATE_KEYS).values_list(
            "key", flat=True
        )
    )
    return present == CANONICAL_RATE_KEYS
