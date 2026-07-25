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

CANONICAL_RATES = DAILY_BATCH_RATES + CLUSTER_ACTIVITY_RATES


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


def ensure_cost_reference() -> int:
    """Create any missing canonical rate. Returns how many were created."""
    from apps.budget.models import CostSetting

    catalogue = ensure_active_catalogue()
    created = 0
    for key, label, default_cost in CANONICAL_RATES:
        _, was_created = CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": default_cost,
                "fy": catalogue.fy,
                "version": 1,
                "catalogue": catalogue,
            },
        )
        created += int(was_created)
    return created
