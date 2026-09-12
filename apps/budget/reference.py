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

# The Country Cost Catalogue (owner, 2026-09-06: "these are the list of
# activities to put in the cost catalog; remove the ones you have now").
# Twenty-two rows in four groups: the per-activity rates, the partner rates,
# the group-session components and the travel per-diems. A key is the stable
# handle the recipes read (`apps/budget/costing.py`); the label is what the
# Country Director sees. Where the owner's list renamed a rate the platform
# already priced with, the key is kept and only the label changed, so every
# saved cost line and every test that seeds the old key still reads.
# key, label, default UGX.
ACTIVITY_RATES: tuple[tuple[str, str, int], ...] = (("onetest", "OneTest", 0),)
PARTNER_RATES: tuple[tuple[str, str, int], ...] = (
    ("client_partner_visit", "Client Partner Visit", 40000),
    ("core_partner_visit", "Core Partner Visit", 40000),
    ("partner_meetings", "Partner Meetings", 40000),
)
GROUP_SESSION_RATES: tuple[tuple[str, str, int], ...] = (
    ("cluster_meetings_trainings", "Cluster Meetings/ Trainings", 0),
    ("tot_trainings", "TOT trainings", 0),
    ("tot_trainings_meals", "TOT trainings - Meals", 5000),
    ("student_conference", "Student Conference", 0),
    ("proprietor_conference", "Proprietor Conference", 0),
    ("printing_training_materials", "Printing training materials", 0),
    ("photocopying_training_materials", "Photocopying training materials", 0),
    ("group_training_venue_cost", "Venue Fee", 30000),
    ("group_training_facilitation_fee", "Facilitation Fee", 50000),
)
TRAVEL_RATES: tuple[tuple[str, str, int], ...] = (
    ("primary_transport_per_day", "Transport Primary District", 50000),
    ("secondary_transport_per_day", "Transport Secondary District", 80000),
    ("lunch_per_day", "Lunch", 12000),
    ("secondary_breakfast_per_day", "Breakfast", 8000),
    ("secondary_overnight_dinner_per_day", "Dinner", 12000),
    ("secondary_accommodation_per_night", "Accommodation", 40000),
)

# The basis each rate is charged on, shown under its label on Cost Settings.
RATE_UNITS: dict[str, str] = {
    "onetest": "per activity",
    "client_partner_visit": "per visit",
    "core_partner_visit": "per visit",
    "partner_meetings": "per meeting",
    "cluster_meetings_trainings": "per session",
    "tot_trainings": "per training",
    "tot_trainings_meals": "per participant per day",
    "student_conference": "per event",
    "proprietor_conference": "per event",
    "printing_training_materials": "per session",
    "photocopying_training_materials": "per session",
    "group_training_venue_cost": "per day",
    "group_training_facilitation_fee": "per day",
    "primary_transport_per_day": "per day",
    "secondary_transport_per_day": "per day",
    "lunch_per_day": "per day",
    "secondary_breakfast_per_day": "per day away",
    "secondary_overnight_dinner_per_day": "per day away",
    "secondary_accommodation_per_night": "per night",
}

CANONICAL_RATES = ACTIVITY_RATES + PARTNER_RATES + GROUP_SESSION_RATES + TRAVEL_RATES
CANONICAL_RATE_KEYS = frozenset(key for key, _label, _cost in CANONICAL_RATES)
RATE_LABELS: dict[str, str] = {key: label for key, label, _cost in CANONICAL_RATES}

# Rates the owner's list ADDED. A recipe adds one of these only when the rate
# card carries it: a card seeded before the list (a test's, an older
# catalogue's) prices exactly as it did, and the live catalogue, which
# always carries them, adds them at whatever the Country Director set.
OPTIONAL_RATE_KEYS = frozenset(
    {
        "onetest",
        "cluster_meetings_trainings",
        "tot_trainings",
        "student_conference",
        "proprietor_conference",
        "printing_training_materials",
        "photocopying_training_materials",
    }
)

# Keys the owner's list renamed. A rate card that still carries the old key
# (a saved snapshot's, a test's) answers for the new one.
RATE_ALIASES: dict[str, tuple[str, ...]] = {
    "lunch_per_day": ("primary_lunch_per_day", "secondary_lunch_per_day"),
    "client_partner_visit": ("partner_visit_lump_sum",),
    "core_partner_visit": ("partner_visit_lump_sum",),
    "partner_meetings": ("partner_visit_lump_sum",),
    "tot_trainings_meals": ("group_training_participant_meal_cost_per_head",),
}


def with_rate_aliases(rates):
    """A rate card that answers renamed keys from the rows it still carries."""
    if not rates:
        return rates
    resolved = dict(rates)
    for key, old_keys in RATE_ALIASES.items():
        if key in resolved:
            continue
        for old in old_keys:
            if old in rates:
                resolved[key] = rates[old]
                break
    return resolved


# Keys the 2026-09-06 list replaced. `secondary_lunch_per_day` was a second
# lunch; `secondary_incidentals_per_day` and the cluster snack rate have no
# row in the owner's list; the partner lumps became the partner rates; the
# group meal rate became the TOT meals rate.
RENAMED_COST_SETTING_KEYS = frozenset(
    {
        "primary_lunch_per_day",
        "secondary_lunch_per_day",
        "secondary_incidentals_per_day",
        "cluster_meeting_participant_meal_cost_per_head",
        "group_training_participant_meal_cost_per_head",
        "partner_visit_lump_sum",
        "partner_training_lump_sum",
    }
)

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
# Rates that named a recipe the platform already had (owner, 2026-09-04:
# "remove all duplicate costs").
#
#   core_school_visit / ssa_visit_rate  a core school visit and an SSA visit
#       are school visits: one staff visit day, priced by district. The flat
#       50,000 ignored the district and was 12,000 short in a primary one and
#       102,000 short in a secondary one.
#   core_school_training                a core training is a group training.
#       No catalogue item even produced the type, and the seeded default
#       (250,000) and the live rate (55,000) had drifted 195,000 apart.
#   project_partner_lump_sum            the same 40,000 as the partner visit
#       rate: a second name for one number.
#   programme_*                         a six-key mirror of the group-training
#       recipe at ten times the venue and double the facilitation, for a type
#       no catalogue item produced. Conferences and camps are catalogued as
#       trainings and always priced on the group recipe.
DUPLICATE_COST_SETTING_KEYS = frozenset(
    {
        "core_school_visit",
        "core_school_training",
        "ssa_visit_rate",
        "project_partner_lump_sum",
        "programme_venue_per_day",
        "programme_participant_meal_cost_per_head",
        "programme_facilitation_per_day",
        "programme_transport_per_day",
        "programme_materials_per_participant",
        "programme_accommodation_per_night",
    }
)
# The owner retired three visit rates on 2026-09-12. A staff visit costs its
# share of the day's transport and meals (the Daily Visit Batch pool divided
# by the schools planned that day) and nothing else, so Client and Core
# Staff Visit are gone. SSA Support is partner work priced as any partner
# school visit, so it is gone too. The partner visit rates and OneTest stay.
RETIRED_VISIT_RATE_KEYS = frozenset(
    {"client_staff_visit", "core_staff_visit", "ssa_support"}
)

RETIRED_COST_SETTING_KEYS = (
    LEGACY_VISIT_COST_KEYS
    | LEGACY_CLUSTER_ACTIVITY_COST_KEYS
    | DUPLICATE_COST_SETTING_KEYS
    | RENAMED_COST_SETTING_KEYS
    | RETIRED_VISIT_RATE_KEYS
)


def ensure_active_catalogue():
    """Return the active CostCatalogue, creating one for the operational FY.

    A rate with no catalogue cannot be snapshotted, and a snapshot is what
    makes a costed activity auditable after the rate changes.
    """
    from django.conf import settings

    from apps.budget.models import (
        CostCatalogue,
        RateCardKind,
        RateCardStatus,
    )

    fy = getattr(settings, "OPERATIONAL_FY", None)
    if not fy:
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
    country = getattr(settings, "COUNTRY", "Uganda")
    active = (
        CostCatalogue.objects.filter(
            country=country,
            fy=str(fy),
            kind=RateCardKind.OPERATIONAL,
            status=RateCardStatus.PUBLISHED,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )
    if active is not None:
        return active

    return CostCatalogue.objects.create(
        country=country,
        fy=str(fy),
        version=1,
        is_active=True,
        label=f"{country} FY{fy} Country Cost Catalogue",
    )


def ensure_cost_reference(catalogue=None) -> int:
    """Create any missing canonical rate. Returns how many were created."""
    from apps.budget.models import (
        CostCatalogue,
        CostSetting,
        RateCardKind,
        RateCardStatus,
    )

    catalogue = catalogue or ensure_active_catalogue()
    CostCatalogue.objects.get_or_create(
        country=catalogue.country,
        fy=catalogue.fy,
        kind=RateCardKind.REFERENCE,
        version=0,
        defaults={
            "status": RateCardStatus.DRAFT,
            "is_active": False,
            "currency": "UGX",
            "label": "Regional Standard Funding Rate Card — Configuration Required",
            "notes": (
                "Reference rates have not been approved. Operational values were "
                "not copied into this card."
            ),
        },
    )
    created = 0
    for key, label, default_cost in CANONICAL_RATES:
        rate, was_created = CostSetting.objects.get_or_create(
            catalogue=catalogue,
            key=key,
            defaults={
                "label": label,
                "unit_cost": default_cost,
                # A rate never arrives without a Minimum Viable Cost. The
                # planner's figure comes from this field with no fallback to
                # the operational rate, so a blank one shows the CCEO and the
                # Programme Lead a dash while the plan behind it accumulates
                # the full cost. The approved rate is its own floor until the
                # CD lowers it in Cost Settings.
                "approved_minimum": default_cost,
                "fy": catalogue.fy,
                "version": 1,
                "unit": RATE_UNITS.get(key, "unit"),
            },
        )
        created += int(was_created)
    return created


def cost_reference_is_complete() -> bool:
    """Read-only counterpart to ``ensure_cost_reference``."""
    from apps.budget.costing_service import active_catalogue
    from apps.budget.models import CostCatalogue, CostSetting, RateCardKind

    catalogue = active_catalogue()
    if catalogue is None:
        return False
    present = set(
        CostSetting.objects.filter(
            catalogue=catalogue,
            key__in=CANONICAL_RATE_KEYS,
        ).values_list("key", flat=True)
    )
    reference_structure_exists = CostCatalogue.objects.filter(
        country=catalogue.country,
        fy=catalogue.fy,
        kind=RateCardKind.REFERENCE,
    ).exists()
    return present == CANONICAL_RATE_KEYS and reference_structure_exists
