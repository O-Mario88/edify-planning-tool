"""Plan Activities for Newly Added Project School (owner, 2026-09-15).

A school added to a project enters its Project Coordinator's portfolio with
nothing planned in it yet. This is the row that says so, derived from the
records: it appears when a school is enrolled with no project activity, names
the school and the project, opens the project's planning surface, and
disappears once the coordinator has planned something there.

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ROW_LIMIT = 8


def project_school_planning_todos(principal, role, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.projects.portfolio import schools_awaiting_project_planning

    try:
        if role != "ProjectCoordinator":
            return []
        staff_id = getattr(principal, "staff_profile_id", None)
        if not staff_id:
            return []
        rows = []
        for assignment in schools_awaiting_project_planning(staff_id, limit=ROW_LIMIT):
            rows.append(
                todo_row(
                    f"project-school-plan-{assignment.id}",
                    title="Plan Activities for Newly Added Project School",
                    description=(
                        f"{assignment.school.name} joined {assignment.project.name} "
                        "and has no project activity planned yet."
                    ),
                    category="Projects",
                    priority="medium",
                    url=f"/projects/planning?project={assignment.project_id}",
                    action="Plan project work",
                    linked=assignment.school.name,
                    today=today,
                    source="Special projects",
                )
            )
        return rows
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Project school planning To-Dos failed")
        return []
