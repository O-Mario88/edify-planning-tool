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

VISIT_TYPES = {
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "core_visit",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
    "core_assessment_visit",
}
TRAINING_TYPES = {
    "training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
    "cluster_training_ssa_collection",
    "cluster_meeting_ssa_review",
}


def _participants_of(a: dict, default_n: int) -> int:
    counted = (
        (a.get("teachersAttended") or 0)
        + (a.get("leadersAttended") or 0)
        + (a.get("otherParticipants") or 0)
    )
    if counted > 0:
        return counted
    expected = a.get("expectedParticipants") or 0
    return expected if expected > 0 else default_n


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

    is_partner = a.get("deliveryType") == "partner"
    activity_type = a.get("activityType")
    is_secondary = a.get("districtType") == "secondary"

    if is_partner:
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
        # Baseline SSA Visit uses separate SSA Visit rate if configured
        add("Baseline SSA Visit", "ssa_visit_rate")

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
                add("Transport (secondary)", "staff_visit_transport_secondary")
                add("Breakfast", "breakfast")
                add("Lunch", "lunch")
                add("Dinner", "dinner")
                nights = max(0, a.get("nights") or 0)
                if nights > 0:
                    add("Accommodation", "accommodation", nights)
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
                add("Transport (primary)", "staff_visit_transport_primary")
                add("Lunch", "lunch")
    elif activity_type in TRAINING_TYPES:
        n = _participants_of(a, DEFAULT_TRAINING_PARTICIPANTS)
        if (
            "group_training_facilitation_fee" in rates
            or "group_training_venue_cost" in rates
            or "group_training_participant_meal_cost_per_head" in rates
        ):
            add("Facilitation", "group_training_facilitation_fee")
            add("Venue", "group_training_venue_cost")
            add("Meals", "group_training_participant_meal_cost_per_head", n)
        else:
            add("Training session", "training_session_fee")
            add("Venue", "venue")
            add("Meals", "meals_per_participant", n)
            add("Mobilisation", "mobilisation_per_participant", n)
    elif activity_type == "cluster_meeting":
        n = _participants_of(a, DEFAULT_CLUSTER_MEETING_PARTICIPANTS)
        if "cluster_meeting_participant_meal_cost_per_head" in rates:
            add(
                "Cluster meeting participant meals",
                "cluster_meeting_participant_meal_cost_per_head",
                n,
            )
        else:
            add("Cluster meeting (per participant)", "cluster_meeting_cost", n)
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
        add("Transport", "staff_visit_transport_primary")
        add("Lunch", "lunch")

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
                label=line["label"],
                key=line["costSettingKey"],
                unit=line["unitCost"],
                qty=line["quantity"],
                amount=line["amount"],
                missing=False,
            )
            for line in snapshot_lines
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
    "cost_for_activity",
    "resolve_activity_cost",
]
