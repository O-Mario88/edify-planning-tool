"""
The automatic costing engine — faithful port of costing.ts.

Every scheduled activity is costed from the CD-owned rate card (CostSetting,
keyed by a stable string). No staff invents a cost. If a required rate is
missing, the activity is flagged costMissing and must not enter a budget / fund
request until the CD resolves it (spec §10).

This is the SINGLE source of truth for activity cost on the backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES
from apps.budget.reference import (
    LEGACY_CLUSTER_ACTIVITY_COST_KEYS,
    RETIRED_COST_SETTING_KEYS,
)


RateCard = dict  # CostSetting.key -> unitCost


@dataclass
class CostLine:
    label: str
    key: str
    unit: int | None  # None = rate missing; integer UGX when present
    qty: int
    amount: int  # integer UGX (0 when the rate is missing)
    missing: bool
    allocation_count: int | None = None
    allocation_index: int | None = None


@dataclass
class ActivityCost:
    amount: int = 0  # integer UGX
    lines: list[CostLine] = field(default_factory=list)
    cost_missing: bool = False
    missing_items: list[str] = field(default_factory=list)


DEFAULT_TRAINING_PARTICIPANTS = 25


# A cluster session has a deliberately small, predictable cost recipe.  These
# stable keys are shared by the catalogue, planning preview, saved schedule
# lines, fund requests and budget reports.  Do not add ad-hoc cluster costs in
# a caller: ``cost_for_activity`` is the one place that defines the recipe.
CLUSTER_TRAINING_TYPES = {
    "cluster_training",
    "cluster_training_ssa_collection",
}
GROUP_TRAINING_RATE_KEYS = (
    "group_training_participant_meal_cost_per_head",
    "group_training_facilitation_fee",
    "group_training_venue_cost",
)
CLUSTER_MEETING_SNACK_RATE_KEY = "cluster_meeting_participant_meal_cost_per_head"


def _nonnegative_count(raw) -> int:
    """Normalize a participant count from an API or HTML form payload.

    Django's request payloads keep number inputs as strings.  Costing is also
    called by JSON clients and by persisted-model serializers, so this pure
    engine deliberately accepts either representation.  Invalid or negative
    values contribute zero here; the scheduling/completion services remain
    responsible for returning their field-specific validation errors.
    """
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _participants_of(a: dict, default_n: int) -> int:
    """Participant quantity for per-head pricing.

    The PLANNED count drives the budget (2026-07-30 audit §32: participant
    rate × planned participant count) — attendance actuals are a completion
    record, and preferring them here meant a post-completion reschedule
    silently converted a planned estimate into an actuals-based figure.
    Actuals are used only when no plan was ever captured, ahead of the
    hardcoded default."""
    if a.get("expectedParticipants") is not None:
        return _nonnegative_count(a["expectedParticipants"])
    counted = sum(
        _nonnegative_count(a.get(key))
        for key in (
            "teachersAttended",
            "leadersAttended",
            "otherParticipants",
        )
    )
    return counted if counted > 0 else default_n


def _days_of(a: dict) -> int:
    """Service days an activity spans (1 unless it carries a date range).

    A Group-delivered camp or conference planned centrally from the Work Plan
    runs for several days, and its per-day components must be priced per day.
    Everything scheduled through school/cluster planning has no end date and
    therefore prices exactly as before."""
    try:
        return max(1, int(a.get("days") or 1))
    except (TypeError, ValueError):
        return 1


def cost_for_activity(a: dict, rates: RateCard) -> ActivityCost:
    """Compute the cost of an activity from the rate card.

    `a` keys: activityType, deliveryType, districtType ('primary'|'secondary'),
    teachersAttended, leadersAttended, otherParticipants, expectedParticipants,
    nights, projectId.
    """
    lines: list[CostLine] = []

    def add(label: str, key: str, qty: int = 1) -> None:
        unit = rates.get(key)
        missing = unit is None
        lines.append(
            CostLine(
                label=label,
                key=key,
                unit=None if missing else unit,
                qty=qty,
                amount=0 if missing else unit * qty,
                missing=missing,
            )
        )

    def add_staff_day(days: int = 1) -> None:
        if is_partner:
            return
        from apps.daily_visit_batches.pricing import (
            KEY_LABELS,
            OPTIONAL_KEYS,
            REQUIRED_KEYS,
        )

        profile = "secondary" if is_secondary else "primary"
        for key in REQUIRED_KEYS[profile]:
            add(KEY_LABELS[key].replace("shared, ", ""), key, days)
        for key in OPTIONAL_KEYS[profile]:
            if key in rates:
                add(KEY_LABELS[key].replace("shared, ", ""), key, days)

    is_partner = a.get("deliveryType") == "partner"
    activity_type = a.get("activityType")
    is_secondary = a.get("districtType") == "secondary"
    # An in-school training is delivered during the same school mission as a
    # school visit. Its Training record describes the programme result, not a
    # second journey or a venue-based group training. Price it from the visit
    # recipe for both staff and partner delivery.
    is_in_school_training = activity_type == "in_school_training"

    # Non-school programme events (conferences, camps, exhibitions, launches)
    # price from the configurable programme component keys. Days come from the
    # activity's date range; participants from the PLANNED count. A component
    # is included only when the CD has configured its rate, except the two
    # core components (venue + participant meals) which are always demanded so
    # a missing rate blocks funded scheduling rather than under-costing.
    # Attendee-side field events (district meetings, boot camps, workshops)
    # price from the MOU travel per-diems. The profile derives from the
    # owner's PRIMARY (home) district vs the destination: same district — or
    # a same-day return — draws transport + lunch; a different district with
    # an overnight adds accommodation, dinner and breakfast per night.
    if activity_type == "field_event":
        days = _days_of(a)
        # Transport accrues PER DAY for every day away — moving between the
        # venue, lodging and home leg happens daily, not once per trip — in
        # both the primary and secondary profiles (owner rule, 2026-08-19).
        if is_secondary:
            add("Transport (secondary)", "secondary_transport_per_day", days)
            add("Lunch", "secondary_lunch_per_day", days)
            # Every secondary away-day carries the full per-diem set —
            # breakfast, dinner and a night's accommodation PER DAY (owner
            # rule, 2026-08-19) — matching the secondary visit-day policy.
            add("Accommodation", "secondary_accommodation_per_night", days)
            add("Dinner", "secondary_overnight_dinner_per_day", days)
            add("Breakfast", "secondary_breakfast_per_day", days)
        else:
            add("Transport (primary)", "primary_transport_per_day", days)
            add("Lunch", "primary_lunch_per_day", days)

    elif activity_type == "programme_event":
        days = _days_of(a)
        n = _participants_of(a, DEFAULT_TRAINING_PARTICIPANTS)
        add("Venue", "programme_venue_per_day", days)
        add("Participant meals", "programme_participant_meal_cost_per_head", n * days)
        if "programme_facilitation_per_day" in rates:
            add("Facilitation", "programme_facilitation_per_day", days)
        if "programme_transport_per_day" in rates:
            add("Transport", "programme_transport_per_day", days)
        if "programme_materials_per_participant" in rates:
            add("Materials", "programme_materials_per_participant", n)
        if days > 1 and "programme_accommodation_per_night" in rates:
            add("Accommodation", "programme_accommodation_per_night", days - 1)

    # Cluster meetings and cluster trainings use their fixed recipe even when
    # a partner delivers the session.  The programme budget needs the same
    # transparent snack/meal/facilitation/venue breakdown in every workflow.
    elif activity_type in CLUSTER_MEETING_TYPES:
        n = _participants_of(a, 0)
        days = _days_of(a)
        add("Participant snacks", CLUSTER_MEETING_SNACK_RATE_KEY, n * days)
        add("Venue fee", "group_training_venue_cost", days)
        add_staff_day(days)

    elif activity_type in CLUSTER_TRAINING_TYPES:
        n = _participants_of(a, 0)
        days = _days_of(a)
        add(
            "Participant meals",
            "group_training_participant_meal_cost_per_head",
            n * days,
        )
        add("Facilitation fee", "group_training_facilitation_fee", days)
        add("Venue fee", "group_training_venue_cost", days)
        add_staff_day(days)

    elif is_partner:
        # Each partner workflow has one canonical, CD-visible rate. Do not
        # substitute a different activity's rate merely because the required
        # row is missing; `add` will mark that exact item as a blocker.
        if is_in_school_training:
            key = "partner_visit_lump_sum"
            basis = "per school mission"
            label = "Partner visit rate"
        elif activity_type in TRAINING_TYPES:
            key = "partner_training_lump_sum"
            basis = "per training"
            label = "Partner training rate"
        elif a.get("projectId"):
            key = "project_partner_lump_sum"
            basis = "project-specific"
            label = "Project partner rate"
        else:
            key = "partner_visit_lump_sum"
            basis = "per activity"
            label = "Partner visit lump sum"

        label_with_basis = f"{label} [Rate basis: {basis}]"
        add(label_with_basis, key)

    elif activity_type == "baseline_ssa_visit":
        add("SSA Visit", "ssa_visit_rate")

    elif activity_type == "core_visit":
        add("Core School Visit", "core_school_visit")

    elif activity_type == "core_training":
        add("Core School Training", "core_school_training")

    elif activity_type in VISIT_TYPES or is_in_school_training:
        if is_secondary:
            add("Transport (secondary)", "secondary_transport_per_day")
            add("Breakfast", "secondary_breakfast_per_day")
            add("Lunch", "secondary_lunch_per_day")
            add("Dinner", "secondary_overnight_dinner_per_day")
            # A secondary-district visit day is an overnight by policy — the
            # Daily Visit Batch pool always carries one night's accommodation.
            nights = a.get("nights")
            try:
                nights = 1 if nights is None else max(0, int(nights))
            except (TypeError, ValueError):
                nights = 1
            if nights > 0:
                add(
                    "Accommodation",
                    "secondary_accommodation_per_night",
                    nights,
                )
        else:
            add("Transport (primary)", "primary_transport_per_day")
            add("Lunch", "primary_lunch_per_day")
    elif activity_type in TRAINING_TYPES:
        n = _participants_of(a, 0)
        days = _days_of(a)
        add(
            "Participant meals",
            "group_training_participant_meal_cost_per_head",
            n * days,
        )
        add("Venue fee", "group_training_venue_cost", days)
        add_staff_day(days)
    elif activity_type in ("partner_activity", "project_activity"):
        project_key = "project_partner_lump_sum" if a.get("projectId") else None
        key = project_key or "partner_visit_lump_sum"
        add("Partner/project lump sum", key)
    else:
        # ssa_activity and anything else default to a staff visit cost.
        add("Transport", "primary_transport_per_day")
        add("Lunch", "primary_lunch_per_day")

    cost_missing = any(line.missing for line in lines)
    amount = sum(line.amount for line in lines)
    missing_items = [line.key for line in lines if line.missing]
    if any(
        line.qty == 0
        and line.key
        in {
            "group_training_participant_meal_cost_per_head",
            CLUSTER_MEETING_SNACK_RATE_KEY,
        }
        for line in lines
    ):
        missing_items.append("expectedParticipants")
        cost_missing = True
    return ActivityCost(
        amount=amount,
        lines=lines,
        cost_missing=cost_missing,
        missing_items=missing_items,
    )


# NOTE: a `resolve_activity_cost` helper used to live here ("prefer the
# snapshot; recalc when actuals exist"). It had no callers, and its recalc
# branch would have re-priced completed work at CURRENT rates — the exact
# snapshot-vs-live desync the persisted cost lines exist to prevent — so it
# was removed rather than left as an attractive nuisance (2026-08-12 audit L-1).

__all__ = [
    "RateCard",
    "CostLine",
    "ActivityCost",
    "CLUSTER_MEETING_SNACK_RATE_KEY",
    "CLUSTER_MEETING_TYPES",
    "CLUSTER_TRAINING_TYPES",
    "GROUP_TRAINING_RATE_KEYS",
    "LEGACY_CLUSTER_ACTIVITY_COST_KEYS",
    "RETIRED_COST_SETTING_KEYS",
    "cost_for_activity",
]
