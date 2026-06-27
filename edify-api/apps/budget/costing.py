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
from typing import Any


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
    "school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit",
}
TRAINING_TYPES = {
    "training", "school_improvement_training", "cluster_training", "core_training",
}


def _participants_of(a: dict, default_n: int) -> int:
    counted = (a.get("teachersAttended") or 0) + (a.get("leadersAttended") or 0) + (a.get("otherParticipants") or 0)
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
        project_key = "project_partner_lump_sum" if a.get("projectId") else None
        training_key = "partner_training_lump_sum" if activity_type in TRAINING_TYPES else None
        fallback = "partner_visit_lump_sum"
        key = fallback
        if project_key and rates.get(project_key) is not None:
            key = project_key
        elif training_key and rates.get(training_key) is not None:
            key = training_key
        add("Partner lump sum", key)
    elif activity_type in VISIT_TYPES:
        if is_secondary:
            add("Transport (secondary)", "staff_visit_transport_secondary")
            add("Breakfast", "breakfast")
            add("Lunch", "lunch")
            add("Dinner", "dinner")
            nights = max(0, a.get("nights") or 0)
            if nights > 0:
                add("Accommodation", "accommodation", nights)
        else:
            add("Transport (primary)", "staff_visit_transport_primary")
            add("Lunch", "lunch")
    elif activity_type in TRAINING_TYPES:
        n = _participants_of(a, DEFAULT_TRAINING_PARTICIPANTS)
        add("Training session", "training_session_fee")
        add("Venue", "venue")
        add("Meals", "meals_per_participant", n)
        add("Mobilisation", "mobilisation_per_participant", n)
    elif activity_type == "cluster_meeting":
        n = _participants_of(a, DEFAULT_CLUSTER_MEETING_PARTICIPANTS)
        add("Cluster meeting (per participant)", "cluster_meeting_cost", n)
    elif activity_type in ("partner_activity", "project_activity"):
        project_key = "project_partner_lump_sum" if a.get("projectId") else None
        key = project_key if (project_key and rates.get(project_key) is not None) else "partner_visit_lump_sum"
        add("Partner/project lump sum", key)
    else:
        # ssa_activity and anything else default to a staff visit cost.
        add("Transport", "staff_visit_transport_primary")
        add("Lunch", "lunch")

    cost_missing = any(l.missing for l in lines)
    amount = sum(l.amount for l in lines)
    missing_items = [l.key for l in lines if l.missing]
    return ActivityCost(amount=amount, lines=lines, cost_missing=cost_missing, missing_items=missing_items)


def resolve_activity_cost(
    a: dict,
    rates: RateCard,
    snapshot_lines: list[dict] | None = None,
) -> ActivityCost:
    """Prefer schedule-time snapshot; recalc from attendance when actuals exist."""
    attended = (a.get("teachersAttended") or 0) + (a.get("leadersAttended") or 0) + (a.get("otherParticipants") or 0)
    if attended > 0:
        return cost_for_activity(a, rates)

    if snapshot_lines:
        lines = [
            CostLine(
                label=l["label"],
                key=l["costSettingKey"],
                unit=l["unitCost"],
                qty=l["quantity"],
                amount=l["amount"],
                missing=False,
            )
            for l in snapshot_lines
        ]
        est = a.get("estCostCents")
        amount = est if (est is not None and est > 0) else sum(l.amount for l in lines)
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
