"""The missing-cluster-training action (owner brief, 2026-09-15).

"Schools with no training planned must surface prominently for the Programme
Lead and Impact Assessment" — as ONE workflow-derived row per responsible
person and period, not one notification per school. The row counts the schools
in that person's own oversight scope, opens the filtered table, and disappears
by itself the moment the count reaches zero.

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The roles the brief names. A Country Director reads the same table on the
#: page; the queue row belongs to the two who act on it.
RESPONSIBLE_ROLES = ("Program Lead", "ImpactAssessment")

COVERAGE_URL = "/team-planning-oversight/?view=coverage"


def missing_training_todos(principal, role, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.core.fy import get_operational_fy
    from apps.planning.coverage_service import missing_training_count

    try:
        if role not in RESPONSIBLE_ROLES:
            return []
        fy = get_operational_fy(today)
        missing = missing_training_count(principal, fy=fy)
        if not missing:
            return []
        return [
            todo_row(
                f"coverage-missing-training-{fy}",
                title="Review Schools with No Cluster Training or Meeting Planned",
                description=(
                    f"{missing} school{'s' if missing != 1 else ''} in your scope "
                    f"have no cluster training or meeting planned for FY{fy}."
                ),
                category="Programme Implementation"
                if role == "Program Lead"
                else "School Progress",
                priority="high",
                url=COVERAGE_URL,
                action="Open Schools & Coverage",
                linked=f"{missing} school{'s' if missing != 1 else ''}",
                today=today,
                source="School coverage",
            )
        ]
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Missing-training To-Dos failed")
        return []
