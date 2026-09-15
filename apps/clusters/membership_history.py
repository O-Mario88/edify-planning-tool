"""Keep the cluster membership history in step with ``School.cluster_id``.

``School.cluster_id`` is the current membership every reader uses. Two writers
change it: the canonical service ``set_school_cluster_membership`` (a person
adding, changing or removing a cluster) and ``School.save`` (membership
re-derived because the school's geography changed). Both call
``sync_membership_history`` afterwards, which closes the open row when the
cluster changed and opens one for the new cluster. At most one row per school
is open; the database enforces it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import CatchmentRelationship, Cluster, SchoolClusterMembership


def _correlation_id() -> str:
    try:
        from apps.core.request_context import get_correlation_id

        value = get_correlation_id()
        return "" if value == "unknown" else value
    except Exception:  # noqa: BLE001 - history never fails a write
        return ""


def open_membership(school_id: str):
    return (
        SchoolClusterMembership.objects.filter(
            school_id=school_id, ended_at__isnull=True
        )
        .select_related("cluster")
        .first()
    )


@transaction.atomic
def sync_membership_history(
    school,
    *,
    actor_id: str = "",
    actor_role: str = "",
    reason: str = "",
    end_reason: str = "",
) -> SchoolClusterMembership | None:
    """Close and open history rows so they match the school's current cluster.

    Returns the open row after the sync (None for an unclustered school).
    Idempotent: a school whose open row already names its cluster is left
    untouched, so retries and re-saves never duplicate history.
    """
    from .catchment import serving_match

    now = timezone.now()
    current = (
        SchoolClusterMembership.objects.select_for_update()
        .filter(school_id=school.id, ended_at__isnull=True)
        .first()
    )
    target_id = school.cluster_id or None
    if current is not None and current.cluster_id == target_id:
        return current
    if current is not None:
        current.ended_at = now
        current.ended_by = actor_id or ""
        current.end_reason = end_reason or reason or ""
        current.save(update_fields=["ended_at", "ended_by", "end_reason", "updated_at"])
    if not target_id:
        return None
    cluster = Cluster.objects.filter(id=target_id).first()
    if cluster is None:
        return None
    match = serving_match(cluster, school.district_id)
    return SchoolClusterMembership.objects.create(
        school_id=school.id,
        cluster=cluster,
        started_at=now,
        started_by=actor_id or "",
        started_by_role=actor_role or "",
        start_reason=reason or "",
        school_district_id=school.district_id,
        cluster_district_id=cluster.district_id,
        relationship_type=(match.relationship_type if match else ""),
        catchment=match.catchment if match else None,
        correlation_id=_correlation_id(),
    )


def membership_history(school_id: str) -> list[SchoolClusterMembership]:
    """Every membership a school has had, newest first, for School 360."""
    return list(
        SchoolClusterMembership.objects.filter(school_id=school_id)
        .select_related("cluster", "school_district", "cluster_district")
        .order_by("-started_at")
    )


__all__ = [
    "CatchmentRelationship",
    "membership_history",
    "open_membership",
    "sync_membership_history",
]
