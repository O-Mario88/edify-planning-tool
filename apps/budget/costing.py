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


@dataclass
class ActivityCost:
    amount: int = 0  # integer UGX
    lines: list[CostLine] = field(default_factory=list)
    cost_missing: bool = False
    missing_items: list[str] = field(default_factory=list)


DEFAULT_TRAINING_PARTICIPANTS = 25
DEFAULT_CLUSTER_MEETING_PARTICIPANTS = 10


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


def _participants_of(a: dict, default_n: int) -> int:
    """Participant quantity for per-head pricing.

    The PLANNED count drives the budget (2026-07-30 audit §32: participant
    rate × planned participant count) — attendance actuals are a completion
    record, and preferring them here meant a post-completion reschedule
    silently converted a planned estimate into an actuals-based figure.
    Actuals are used only when no plan was ever captured, ahead of the
    hardcoded default."""
    expected = a.get("expectedParticipants") or 0
    if expected > 0:
        return expected
    counted = (
        (a.get("teachersAttended") or 0)
        + (a.get("leadersAttended") or 0)
        + (a.get("otherParticipants") or 0)
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

    def current_or_legacy(canonical_key: str, legacy_key: str) -> str:
        """Prefer the unified catalogue key, with upgrade-only compatibility.

        The fallback lets historical/test databases that have not restored the
        canonical registry remain costable.  Normal application databases
        always contain the canonical key via ``ensure_cost_reference``.
        """
        return canonical_key if canonical_key in rates else legacy_key

    is_partner = a.get("deliveryType") == "partner"
    activity_type = a.get("activityType")
    is_secondary = a.get("districtType") == "secondary"

    # Non-school programme events (conferences, camps, exhibitions, launches)
    # price from the configurable programme component keys. Days come from the
    # activity's date range; participants from the PLANNED count. A component
    # is included only when the CD has configured its rate, except the two
    # core components (venue + participant meals) which are always demanded so
    # a missing rate blocks funded scheduling rather than under-costing.
    if activity_type == "programme_event":
        days = max(1, int(a.get("days") or 1))
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
        n = _participants_of(a, DEFAULT_CLUSTER_MEETING_PARTICIPANTS)
        add("Participant snacks", CLUSTER_MEETING_SNACK_RATE_KEY, n)

    elif activity_type in CLUSTER_TRAINING_TYPES:
        n = _participants_of(a, DEFAULT_TRAINING_PARTICIPANTS)
        days = _days_of(a)
        add(
            "Participant meals",
            "group_training_participant_meal_cost_per_head",
            n * days,
        )
        add("Facilitation fee", "group_training_facilitation_fee", days)
        add("Venue fee", "group_training_venue_cost", days)

    elif is_partner:
        # Determine the key, basis, and label
        if "partner_visit_rate" in rates:
            key = "partner_visit_rate"
            basis = "per visit"
            label = "Partner visit rate"
        elif "partner_school_visit_rate" in rates:
            key = "partner_school_visit_rate"
            basis = "per school"
            label = "Partner School Visit"
        elif activity_type in TRAINING_TYPES and "partner_training_lump_sum" in rates:
            key = "partner_training_lump_sum"
            basis = "per training"
            label = "Partner training rate"
        elif (
            activity_type == "cluster_meeting"
            and "partner_cluster_activity_rate" in rates
        ):
            key = "partner_cluster_activity_rate"
            basis = "per cluster activity"
            label = "Partner cluster activity rate"
        elif a.get("projectId") and "project_partner_lump_sum" in rates:
            key = "project_partner_lump_sum"
            basis = "project-specific"
            label = "Project partner rate"
        else:
            key = "partner_visit_lump_sum"
            basis = "per activity"
            label = "Partner visit lump sum"

        label_with_basis = f"{label} [Rate basis: {basis}]"
        add(label_with_basis, key)

    elif activity_type == "baseline_ssa_visit" and "ssa_visit_rate" in rates:
        # SSA Visit uses a separate rate if configured.
        add("SSA Visit", "ssa_visit_rate")

    elif activity_type == "core_visit" and "core_school_visit" in rates:
        # Core School Visit fetches from Cost Catalogue if defined
        add("Core School Visit", "core_school_visit")

    elif activity_type == "core_training" and "core_school_training" in rates:
        # Core School Training fetches from Cost Catalogue if defined
        add("Core School Training", "core_school_training")

    elif activity_type in VISIT_TYPES:
        if is_secondary:
            if (
                "school_visit_cost_per_school_secondary" in rates
                or "school_visit_cost_per_school" in rates
            ):
                key = (
                    "school_visit_cost_per_school_secondary"
                    if "school_visit_cost_per_school_secondary" in rates
                    else "school_visit_cost_per_school"
                )
                add("School visit (secondary)", key)
            else:
                add(
                    "Transport (secondary)",
                    current_or_legacy(
                        "secondary_transport_per_day",
                        "staff_visit_transport_secondary",
                    ),
                )
                add(
                    "Breakfast",
                    current_or_legacy("secondary_breakfast_per_day", "breakfast"),
                )
                add(
                    "Lunch",
                    current_or_legacy("secondary_lunch_per_day", "lunch"),
                )
                add(
                    "Dinner",
                    current_or_legacy(
                        "secondary_overnight_dinner_per_day",
                        "dinner",
                    ),
                )
                # A secondary-district visit day is an overnight by policy —
                # the Daily Visit Batch pool always carries one night's
                # accommodation, but this itemized path only added it when the
                # caller sent "nights", which no form ever does. Default to
                # one night for parity; an explicit nights=0 still means a
                # same-day return.
                nights = a.get("nights")
                try:
                    nights = 1 if nights is None else max(0, int(nights))
                except (TypeError, ValueError):
                    nights = 1
                if nights > 0:
                    add(
                        "Accommodation",
                        current_or_legacy(
                            "secondary_accommodation_per_night",
                            "accommodation",
                        ),
                        nights,
                    )
        else:
            if (
                "school_visit_cost_per_school_primary" in rates
                or "school_visit_cost_per_school" in rates
            ):
                key = (
                    "school_visit_cost_per_school_primary"
                    if "school_visit_cost_per_school_primary" in rates
                    else "school_visit_cost_per_school"
                )
                add("School visit (primary)", key)
            else:
                add(
                    "Transport (primary)",
                    current_or_legacy(
                        "primary_transport_per_day",
                        "staff_visit_transport_primary",
                    ),
                )
                add(
                    "Lunch",
                    current_or_legacy("primary_lunch_per_day", "lunch"),
                )
    elif activity_type in TRAINING_TYPES:
        n = _participants_of(a, DEFAULT_TRAINING_PARTICIPANTS)
        days = _days_of(a)
        add(
            "Participant meals",
            "group_training_participant_meal_cost_per_head",
            n * days,
        )
        add("Facilitation fee", "group_training_facilitation_fee", days)
        add("Venue fee", "group_training_venue_cost", days)
    elif activity_type in ("partner_activity", "project_activity"):
        project_key = "project_partner_lump_sum" if a.get("projectId") else None
        key = (
            project_key
            if (project_key and rates.get(project_key) is not None)
            else "partner_visit_lump_sum"
        )
        add("Partner/project lump sum", key)
    else:
        # ssa_activity and anything else default to a staff visit cost.
        add(
            "Transport",
            current_or_legacy(
                "primary_transport_per_day",
                "staff_visit_transport_primary",
            ),
        )
        add(
            "Lunch",
            current_or_legacy("primary_lunch_per_day", "lunch"),
        )

    cost_missing = any(line.missing for line in lines)
    amount = sum(line.amount for line in lines)
    missing_items = [line.key for line in lines if line.missing]
    return ActivityCost(
        amount=amount,
        lines=lines,
        cost_missing=cost_missing,
        missing_items=missing_items,
    )


def resolve_activity_cost(
    a: dict,
    rates: RateCard,
    snapshot_lines: list[dict] | None = None,
) -> ActivityCost:
    """Prefer schedule-time snapshot; recalc from attendance when actuals exist."""
    attended = (
        (a.get("teachersAttended") or 0)
        + (a.get("leadersAttended") or 0)
        + (a.get("otherParticipants") or 0)
    )
    if attended > 0:
        return cost_for_activity(a, rates)

    if snapshot_lines:
        lines = [
            CostLine(
                label=sl["label"],
                key=sl["costSettingKey"],
                unit=sl["unitCost"],
                qty=sl["quantity"],
                amount=sl["amount"],
                missing=False,
            )
            for sl in snapshot_lines
        ]
        est = a.get("estCostCents")
        amount = (
            est if (est is not None and est > 0) else sum(line.amount for line in lines)
        )
        return ActivityCost(
            amount=amount,
            lines=lines,
            cost_missing=bool(a.get("costMissing")),
            missing_items=[],
        )

    est = a.get("estCostCents")
    if est is not None and est > 0:
        return ActivityCost(
            amount=est,
            lines=[],
            cost_missing=bool(a.get("costMissing")),
            missing_items=[],
        )
    return cost_for_activity(a, rates)


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
    "resolve_activity_cost",
]
