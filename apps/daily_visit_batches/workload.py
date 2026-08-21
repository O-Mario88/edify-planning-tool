"""§5 Activity Workload Weights — the analytical allocation layer.

One day, one mission cost; many activities of different sizes. Weights say
how much of the day each activity consumed so the Daily Field Cost (School
Visit) reflects visits only, never the cluster meeting that shared the car.

Weights are configuration (CD/Admin, versioned in ActivityWorkloadWeight);
the defaults below seed anything not yet configured. All arithmetic is
integer (weights in hundredths) and never touches funding lines.
"""

from __future__ import annotations

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES as _MEETINGS,
    TRAINING_TYPES as _TRAININGS,
    VISIT_TYPES as _VISITS,
)

# Spec defaults (×100). Anything unlisted weighs 1.0.
DEFAULT_WEIGHT_HUNDREDTHS: dict[str, int] = {
    **{t: 100 for t in _VISITS},
    "baseline_ssa_visit": 150,
    "school_visit_ssa_collection": 150,
    "ssa_activity": 150,
    "core_assessment_visit": 150,
    **{t: 250 for t in _TRAININGS},
    "cluster_training": 400,
    "cluster_training_ssa_collection": 400,
    **{t: 200 for t in _MEETINGS},
    "field_event": 150,
    "partner_activity": 100,
}
FALLBACK_WEIGHT = 100


def live_weights() -> dict[str, int]:
    """Configured weights (highest active version per type) over defaults."""
    from .models import ActivityWorkloadWeight

    weights = dict(DEFAULT_WEIGHT_HUNDREDTHS)
    rows = (
        ActivityWorkloadWeight.objects.filter(active=True)
        .order_by("activity_type", "version")
        .values_list("activity_type", "weight_hundredths")
    )
    for activity_type, hundredths in rows:  # later versions overwrite earlier
        weights[activity_type] = hundredths
    return weights


def set_weight(activity_type: str, weight: float, principal, reason: str = ""):
    """CD/Admin sets a weight — appends a version row (auditable)."""
    from apps.core.exceptions import BadRequest, Forbidden

    from .models import ActivityWorkloadWeight

    if getattr(principal, "active_role", "") not in ("CountryDirector", "Admin"):
        raise Forbidden("Only the Country Director can configure workload weights.")
    hundredths = int(round(float(weight) * 100))
    if hundredths <= 0:
        raise BadRequest("A workload weight must be positive.")
    last = (
        ActivityWorkloadWeight.objects.filter(activity_type=activity_type)
        .order_by("-version")
        .first()
    )
    return ActivityWorkloadWeight.objects.create(
        activity_type=activity_type,
        weight_hundredths=hundredths,
        version=(last.version + 1) if last else 1,
        changed_by_user_id=principal.user_id,
        reason=reason,
    )


def allocate_mission_cost(activities, mission_cost: int, weights=None) -> dict:
    """§5 mixed-mission formula, integer-exact.

    Returns {school_visit_allocation, planned_field_cost_per_school,
    total_units, visit_units, visit_count, weights_used} — analytics only.
    """
    weights = weights or live_weights()
    visit_count = 0
    visit_units = 0
    total_units = 0
    weights_used: dict[str, int] = {}
    for a in activities:
        w = weights.get(a.activity_type, FALLBACK_WEIGHT)
        weights_used[a.activity_type] = w
        total_units += w
        if a.activity_type in _VISITS:
            visit_count += 1
            visit_units += w
    if total_units <= 0 or visit_count == 0:
        return {
            "school_visit_allocation": None,
            "planned_field_cost_per_school": None,
            "total_units": total_units,
            "visit_units": visit_units,
            "visit_count": visit_count,
            "weights_used": weights_used,
        }
    allocation = round(mission_cost * visit_units / total_units)
    return {
        "school_visit_allocation": allocation,
        "planned_field_cost_per_school": round(allocation / visit_count),
        "total_units": total_units,
        "visit_units": visit_units,
        "visit_count": visit_count,
        "weights_used": weights_used,
    }


def actual_field_cost_per_school(batch) -> int | None:
    """§4/§11 — actual = school-visit allocation ÷ COMPLETED visits.

    None when nothing completed (Not Calculable — never divide by zero);
    the mission keeps its legitimate cost either way.
    """
    from apps.core.activity_types import COMPLETED_WORK_STATUSES

    completed_visits = [
        a
        for a in batch.activities.filter(deleted_at__isnull=True)
        if a.activity_type in _VISITS and a.status in COMPLETED_WORK_STATUSES
    ]
    if not completed_visits or not batch.school_visit_allocation:
        return None
    return round(batch.school_visit_allocation / len(completed_visits))
