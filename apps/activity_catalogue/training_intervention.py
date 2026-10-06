"""The SSA intervention each training course is fixed to.

A course such as Discipleship Dynamics or Literacy/Numeracy moves one SSA
intervention, recorded as its primary FIXED intervention mapping. Every
training planned for such a course carries that intervention (owner,
2026-09-29): the planning paths stamp it through
``apply_catalogue_snapshot``, ``Activity.save`` fills it on any training that
reaches the database without one (apps.activities.models), and the oversight
tables and exports read it for older rows.
"""

from __future__ import annotations

import time

_CACHE: dict = {"at": 0.0, "map": {}}
#: A mapping is edited rarely and by Impact Assessment; a minute is fresh
#: enough, and saves a query on every training built on a 74,000-row page.
_TTL_SECONDS = 60


def fixed_interventions(*, fresh: bool = False) -> dict[str, str]:
    """{catalogue item id: intervention} for items with an active primary
    FIXED mapping."""
    now = time.monotonic()
    if fresh or now - _CACHE["at"] > _TTL_SECONDS:
        from apps.activity_catalogue.models import (
            ActivityInterventionMapping,
            MappingMode,
        )

        found: dict[str, str] = {}
        for item_id, intervention in (
            ActivityInterventionMapping.objects.filter(
                active=True,
                mapping_mode=MappingMode.FIXED,
                intervention__isnull=False,
            )
            .exclude(intervention="")
            .order_by("-is_primary", "priority", "id")
            .values_list("catalogue_item_id", "intervention")
        ):
            found.setdefault(item_id, intervention)
        _CACHE.update(at=now, map=found)
    return _CACHE["map"]


def intervention_for(*, training_course_id=None, catalogue_item_id=None) -> str:
    """The fixed intervention of the course taught, else of the catalogue
    item; "" when neither is fixed to one."""
    fixed = fixed_interventions(fresh=True)
    for course_id in (training_course_id, catalogue_item_id):
        if course_id and fixed.get(course_id):
            return fixed[course_id]
    return ""


def _scheduled_course_id(activity) -> str | None:
    """The Training Catalogue entry whose link governs this plan; None for
    anything that is not a training (a cluster meeting counts only when it is
    classified Training) and for project work, which keeps the interventions
    its project is linked to."""
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.core.enums import MeetingKind

    if activity.project_id:
        return None
    if activity.activity_type not in TRAINING_TYPES and not (
        activity.activity_type in CLUSTER_MEETING_TYPES
        and activity.meeting_kind == MeetingKind.TRAINING
    ):
        return None
    if activity.training_course_id:
        return activity.training_course_id
    item = activity.catalogue_item
    if item is None or not item.is_training_course:
        return None
    return item.id


def linked_intervention(activity) -> str:
    """The SSA intervention a scheduled training is held to (owner,
    2026-10-06): the one its Training Catalogue entry is linked to. "" when
    the plan is not a training, or its training is linked to none."""
    course_id = _scheduled_course_id(activity)
    return intervention_for(training_course_id=course_id) if course_id else ""


def catalogue_sets_intervention(activity) -> bool:
    """Whether the Training Catalogue, and not the planner, decides this
    plan's SSA intervention: every training except one the catalogue maps to
    "any SSA intervention". A training that is not SSA-scored is among them —
    the catalogue's answer for it is "none"."""
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingMode,
    )

    course_id = _scheduled_course_id(activity)
    if not course_id:
        return False
    mode = (
        ActivityInterventionMapping.objects.filter(
            catalogue_item_id=course_id, active=True
        )
        .order_by("-is_primary", "priority", "id")
        .values_list("mapping_mode", flat=True)
        .first()
    )
    return mode != MappingMode.ANY_SSA_INTERVENTION


__all__ = [
    "catalogue_sets_intervention",
    "fixed_interventions",
    "intervention_for",
    "linked_intervention",
]
