"""The follow-up a cluster's attendance asks of the person who holds it.

Owner brief, 2026-10-08 (Cluster Management, "The cluster system should
automatically generate follow-up"): "School missed 3 consecutive meetings →
Create CCEO follow-up."

One To-Do per cluster, for the officer responsible for it, naming how many of
its schools have missed three or more sessions in a row and opening the list
(owner brief, 2026-09-15: one workflow-derived row per responsible person, not
one notification per school). It is derived from the session register on
every read (``profile_insights.attendance_by_cluster``): nothing is stored,
nobody ticks it off, and it goes when the schools attend again — or when the
count changes, the same row says the new count.

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Most clusters a queue lists; an officer holding more sees the worst first.
MAX_ROWS = 10


def absent_school_clusters(principal, today) -> list[dict]:
    """The principal's own clusters with schools absent three or more times
    in a row, worst first: {cluster, schools (rows), count}."""
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import owner_ids

    from . import profile_insights as insights
    from .models import Cluster

    mine = owner_ids(principal)
    if not mine:
        return []
    clusters = list(
        Cluster.objects.filter(
            responsible_staff_id__in=mine, deleted_at__isnull=True
        ).only("id", "name")
    )
    if not clusters:
        return []
    attendance = insights.attendance_by_cluster(
        [c.id for c in clusters], fy=get_operational_fy(today)
    )
    found = [
        {
            "cluster": cluster,
            "schools": attendance[cluster.id]["drifting"],
            "count": len(attendance[cluster.id]["drifting"]),
        }
        for cluster in clusters
        if attendance[cluster.id]["drifting"]
    ]
    found.sort(key=lambda row: (-row["count"], row["cluster"].name))
    return found


def attendance_todos(principal, role, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row

    from .profile_insights import MISSED_IN_A_ROW_ALERT

    try:
        rows = []
        for entry in absent_school_clusters(principal, today)[:MAX_ROWS]:
            cluster, schools, count = entry["cluster"], entry["schools"], entry["count"]
            named = ", ".join(s.name for s in schools[:3])
            more = f" and {count - 3} more" if count > 3 else ""
            rows.append(
                todo_row(
                    f"cluster-absent-{cluster.id}",
                    title="Follow Up Schools Missing Cluster Sessions",
                    description=(
                        f"{count} school{'s' if count != 1 else ''} of "
                        f"{cluster.name} {'have' if count != 1 else 'has'} missed "
                        f"{MISSED_IN_A_ROW_ALERT} or more sessions in a row: "
                        f"{named}{more}."
                    ),
                    category="Programme Implementation"
                    if role == "Program Lead"
                    else "Planning",
                    priority="high",
                    url=f"/clusters/{cluster.id}?tab=attendance&show=missing",
                    action="Open Schools",
                    linked=cluster.name,
                    today=today,
                    source="Cluster attendance",
                )
            )
        return rows
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Cluster attendance To-Dos failed")
        return []


__all__ = ["MAX_ROWS", "absent_school_clusters", "attendance_todos"]
