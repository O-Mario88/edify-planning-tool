"""Which of my clusters have a group training and a cluster meeting planned.

Owner, 2026-09-28: "CCEOs don't have the cluster group training planned table
like cluster meeting. can you add that to make sure they can know which
cluster has been planned and which ones have not been planned."

One row per cluster the reader is responsible for, with the next group
training and the next cluster meeting planned for it in the year, what has
already been delivered, and "Not planned" where there is nothing — the list a
CCEO works down to be sure no cluster is left out. The year reads forward
through the planning horizon (``fy_policy.planning_horizon``), as every other
"what has been planned" read does, so a September plan dated in October is
not reported as missing.

Two queries: the clusters, and their sessions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Q

TRAINING_SESSION_TYPES = ("cluster_training", "cluster_training_ssa_collection")


@dataclass
class SessionState:
    next_date: date | None = None
    planned: int = 0
    delivered: int = 0
    last_delivered: date | None = None

    @property
    def label(self) -> str:
        if self.next_date:
            return f"Planned · {self.next_date:%-d %b %Y}"
        if self.planned:
            return "Planned · not dated"
        if self.delivered:
            day = f" · {self.last_delivered:%-d %b %Y}" if self.last_delivered else ""
            return f"Delivered{day}"
        return "Not planned"

    @property
    def tone(self) -> str:
        if self.planned:
            return "info"
        if self.delivered:
            return "success"
        return "danger"

    @property
    def is_planned(self) -> bool:
        return bool(self.planned or self.delivered)


@dataclass
class ClusterPlanningRow:
    id: str
    name: str
    district: str
    schools: int
    training: SessionState
    meeting: SessionState

    @property
    def url(self) -> str:
        return f"/clusters/{self.id}"


def cluster_planning_status(principal, *, fy: str) -> dict:
    """The reader's clusters and whether each has its sessions planned."""
    from apps.activities.models import Activity
    from apps.clusters.models import Cluster
    from apps.core.activity_types import CLUSTER_MEETING_TYPES
    from apps.core.scoping import owner_ids
    from apps.planning.fy_policy import planning_horizon
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        PLANNED_STATUSES,
        VERIFIED_STATUSES,
    )
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    mine = [i for i in owner_ids(principal) if i]
    empty = {"rows": [], "trainings_missing": 0, "meetings_missing": 0, "fys": ()}
    if not mine:
        return empty
    clusters = list(
        Cluster.objects.filter(responsible_staff_id__in=mine, deleted_at__isnull=True)
        .select_related("district")
        .order_by("name")
    )
    if not clusters:
        return empty

    from apps.schools.models import School

    members = dict(
        School.objects.filter(
            cluster_id__in=[c.id for c in clusters],
            cluster_status="clustered",
            deleted_at__isnull=True,
            operational_status__in=OPERATING_STATUSES,
        )
        .values("cluster_id")
        .annotate(n=Count("id"))
        .values_list("cluster_id", "n")
    )
    fys = planning_horizon(fy)
    meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
    delivered = AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES
    states: dict[tuple[str, str], SessionState] = {}
    for cluster_id, activity_type, status, planned_date in (
        Activity.objects.filter(
            cluster_id__in=[c.id for c in clusters],
            fy__in=fys,
            deleted_at__isnull=True,
            status__in=PLANNED_STATUSES | delivered,
        )
        .filter(
            Q(activity_type__in=TRAINING_SESSION_TYPES)
            | Q(activity_type__in=meeting_types)
        )
        .values_list("cluster_id", "activity_type", "status", "planned_date")
    ):
        kind = "meeting" if activity_type in meeting_types else "training"
        state = states.setdefault((cluster_id, kind), SessionState())
        if status in delivered:
            state.delivered += 1
            if planned_date and (
                state.last_delivered is None or planned_date > state.last_delivered
            ):
                state.last_delivered = planned_date
        else:
            state.planned += 1
            if planned_date and (
                state.next_date is None or planned_date < state.next_date
            ):
                state.next_date = planned_date

    rows = [
        ClusterPlanningRow(
            id=cluster.id,
            name=cluster.name,
            district=cluster.district.name if cluster.district_id else "",
            schools=members.get(cluster.id, 0),
            training=states.get((cluster.id, "training"), SessionState()),
            meeting=states.get((cluster.id, "meeting"), SessionState()),
        )
        for cluster in clusters
    ]
    # Clusters with nothing planned first: they are the work.
    rows.sort(
        key=lambda r: (
            int(r.training.is_planned) + int(r.meeting.is_planned),
            r.training.is_planned,
            r.name.casefold(),
        )
    )
    return {
        "rows": rows,
        "trainings_missing": sum(1 for r in rows if not r.training.is_planned),
        "meetings_missing": sum(1 for r in rows if not r.meeting.is_planned),
        "fys": fys,
    }


__all__ = ["ClusterPlanningRow", "SessionState", "cluster_planning_status"]
