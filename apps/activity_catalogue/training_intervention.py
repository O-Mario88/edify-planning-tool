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


__all__ = ["fixed_interventions", "intervention_for"]
