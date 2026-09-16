"""Next fiscal year To-Dos (owner brief, 2026-09-15).

When a fiscal year opens for planning before the current one ends:

* a planner (CCEO, Programme Lead, Project Coordinator) sees "Plan FY2027
  Activities" until they have planned anything in that year;
* the Country Director sees "Prepare the FY2027 Rate Card" until that year has
  a published operational rate card — without one no FY2027 work can be
  costed.

Both are derived from the records and vanish when the work exists. Registered
in apps.command_center.todo_service.MODULE_TODO_BUILDERS.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PLANNER_ROLES = ("CCEO", "Program Lead", "ProjectCoordinator")


def fy_planning_todos(principal, role, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.planning.fy_policy import next_open_policy

    try:
        if role not in PLANNER_ROLES and role != "CountryDirector":
            return []
        policy = next_open_policy()
        if policy is None:
            return []
        fy = policy.fy
        starts = policy.execution_start
        rows: list[dict] = []
        if role in PLANNER_ROLES:
            from apps.activities.models import Activity
            from apps.core.scoping import owner_ids

            ids = [i for i in owner_ids(principal) if i]
            if (
                ids
                and not Activity.objects.filter(
                    fy=fy, deleted_at__isnull=True, responsible_staff_id__in=ids
                ).exists()
            ):
                rows.append(
                    todo_row(
                        f"fy-plan-{fy}",
                        title=f"Plan FY{fy} Activities",
                        description=(
                            f"FY{fy} is open for planning"
                            + (f" for dates from {starts:%-d %B %Y}" if starts else "")
                            + ". Nothing is planned in it yet."
                        ),
                        category="Planning",
                        priority="medium",
                        url="/planning",
                        action="Open Planning",
                        linked=f"FY{fy}",
                        today=today,
                        source="Fiscal year planning",
                        due=starts,
                    )
                )
        if role == "CountryDirector":
            if not getattr(policy, "has_operational_rate_card", False):
                rows.append(
                    todo_row(
                        f"fy-rate-card-{fy}",
                        title=f"Prepare the FY{fy} Rate Card",
                        description=(
                            f"FY{fy} is open for planning, but no FY{fy} rate card is "
                            "published, so FY"
                            f"{fy} activities cannot be costed."
                        ),
                        category="Finance",
                        priority="high",
                        url=f"/cost-settings?fy={fy}",
                        action="Open Cost Settings",
                        linked=f"FY{fy}",
                        today=today,
                        source="Fiscal year planning",
                        due=starts,
                    )
                )
        return rows
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("FY planning To-Dos failed")
        return []
