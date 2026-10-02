"""The partner a cluster is assigned to facilitate (owner, 2026-10-02).

"Assigning a cluster to the partner ONLY means they facilitate the cluster
activity NOT assigned to them to do school visit … once the staff has assigned
the cluster to the partner, the rest of the logistics will be calculated when
a meeting or training is planned. And it should go to the partner as clusters
they will facilitate … staff handles meals, and everything. partner is only
paid facilitation fee."

So assigning a cluster to a partner is a standing choice on the cluster:

* It has no date and no cost, and it hands over no school: no
  PartnerAssignment, no partner allowance, nothing for planning support or
  the visit gate to read (apps.activities.facilitation says the same of one
  facilitated training).
* The partner sees the cluster in "Clusters you facilitate".
* Each group training or cluster meeting staff later plan for the cluster
  names this partner in "Facilitated by" without being asked; the planner may
  still choose Staff or another partner for one session. That session is the
  officer's work, priced when it is planned: meals, venue, materials and the
  officer's day are staff money, and the facilitation fee alone is the
  partner's.
* Sessions already planned keep the facilitator they have; one is changed
  from its own Edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from .models import Cluster


def facilitator_of(cluster):
    """The active partner this cluster is assigned to, or None."""
    partner_id = getattr(cluster, "facilitating_partner_id", None)
    if not partner_id:
        return None
    from apps.partners.models import Partner

    return Partner.objects.filter(
        id=partner_id, deleted_at__isnull=True, active_status=True
    ).first()


def default_facilitator_id(cluster_id, *, activity_type, data, principal):
    """Who facilitates a new cluster session nobody named a facilitator for.

    The cluster's assigned partner, when the session is one staff run: a
    partner scheduling its own work, or work booked for partner delivery,
    has no separate facilitator.
    """
    if not cluster_id:
        return None
    from apps.activities.facilitation import facilitates
    from apps.core.scoping import resolve_partner_ids

    if not facilitates(activity_type):
        return None
    if (data.get("deliveryType") or "staff") != "staff" or data.get(
        "assignedPartnerId"
    ):
        return None
    if resolve_partner_ids(principal):
        return None
    cluster = (
        Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True)
        .only("id", "facilitating_partner_id")
        .first()
    )
    partner = facilitator_of(cluster) if cluster else None
    return partner.id if partner else None


def assign_facilitator(cluster, partner_id, principal) -> Cluster:
    """Assign ``cluster`` to a partner to facilitate; blank returns it to
    staff. The caller has already resolved the cluster within the reader's
    scope."""
    from apps.core.permissions import RolePermissionService
    from apps.core.scoping import resolve_partner_ids

    if resolve_partner_ids(
        principal
    ) or not RolePermissionService.can_assign_to_partner(principal):
        raise Forbidden("Edify staff choose who facilitates a cluster.")
    partner_id = (partner_id or "").strip() or None
    partner = None
    if partner_id:
        from apps.partners.models import Partner

        partner = Partner.objects.filter(
            id=partner_id, deleted_at__isnull=True, active_status=True
        ).first()
        if partner is None:
            raise BadRequest("Select an active Partner organisation to facilitate.")

    with transaction.atomic():
        cluster = Cluster.objects.select_for_update().get(pk=cluster.pk)
        previous = cluster.facilitating_partner_id or None
        if previous == partner_id:
            return cluster
        cluster.facilitating_partner_id = partner_id
        cluster.facilitator_assigned_by = (
            str(
                getattr(principal, "staff_profile_id", None)
                or getattr(principal, "id", "")
                or ""
            )
            or None
            if partner_id
            else None
        )
        cluster.facilitator_assigned_at = timezone.now() if partner_id else None
        cluster.save(
            update_fields=[
                "facilitating_partner_id",
                "facilitator_assigned_by",
                "facilitator_assigned_at",
                "updated_at",
            ]
        )
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="cluster.facilitator_changed",
                subject_kind="Cluster",
                subject_id=cluster.id,
                actor_id=str(getattr(principal, "id", "") or "system"),
                actor_role=getattr(principal, "active_role", ""),
                success=True,
                payload={"from": previous or "", "to": partner_id or ""},
            )
        except Exception:  # pragma: no cover — audit must never block the save
            pass
    if partner is not None:
        _tell_partner(cluster, partner)
    return cluster


def _tell_partner(cluster, partner) -> None:
    """Tell the partner it now facilitates this cluster. Best-effort."""

    def _send():
        try:
            from apps.notifications.services import WorkflowNotificationService

            user_id = getattr(partner, "user_id", None)
            if not user_id:
                return
            WorkflowNotificationService.trigger(
                event_type="partner_cluster_facilitation_assigned",
                category="partner",
                priority="normal",
                title="You are assigned a cluster to facilitate",
                body=(
                    f"Edify assigned {cluster.name} to your organisation to "
                    "facilitate. Its trainings and meetings appear on your "
                    "plan as Edify staff schedule them, each with its "
                    "facilitation fee."
                ),
                context_type="Partner",
                context_id=partner.id,
                recipients=[user_id],
            )
        except Exception:  # noqa: BLE001 — never block the assignment
            pass

    transaction.on_commit(_send)


def upcoming_sessions(cluster) -> int:
    """Dated, still-planned sessions of this cluster, for the drawer's note
    that they keep the facilitator they have."""
    from apps.activities.editing import EDITABLE_STATUSES
    from apps.activities.models import Activity

    return Activity.objects.filter(
        cluster_id=cluster.id,
        school__isnull=True,
        deleted_at__isnull=True,
        status__in=EDITABLE_STATUSES,
    ).count()


@dataclass
class FacilitatedCluster:
    cluster_id: str
    name: str
    district: str = ""
    schools: int = 0
    edify_officer: str = ""
    assigned_on: date | None = None
    sessions_planned: int = 0
    next_session: date | None = None


def facilitated_clusters(principal) -> list[FacilitatedCluster]:
    """The clusters the signed-in partner is assigned to facilitate, with
    what is planned at each so far."""
    from django.db.models import Count, Min, Q

    from apps.accounts.models import StaffProfile
    from apps.activities.editing import EDITABLE_STATUSES
    from apps.activities.models import Activity
    from apps.core.clock import local_day
    from apps.core.scoping import resolve_partner_ids
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        return []
    clusters = list(
        Cluster.objects.filter(
            deleted_at__isnull=True, facilitating_partner_id__in=partner_ids
        )
        .select_related("district")
        .order_by("name")
    )
    if not clusters:
        return []
    ids = [cluster.id for cluster in clusters]
    school_counts = dict(
        School.objects.filter(
            cluster_id__in=ids,
            deleted_at__isnull=True,
            operational_status__in=OPERATING_STATUSES,
        )
        .values_list("cluster_id")
        .annotate(n=Count("id"))
    )
    planned = {
        row["cluster_id"]: row
        for row in Activity.objects.filter(
            cluster_id__in=ids,
            school__isnull=True,
            deleted_at__isnull=True,
            facilitating_partner_id__in=partner_ids,
            status__in=EDITABLE_STATUSES,
        )
        .values("cluster_id")
        .annotate(n=Count("id"), first=Min("planned_date"))
    }
    owners = {cluster.responsible_staff_id for cluster in clusters} | {
        cluster.facilitator_assigned_by for cluster in clusters
    }
    owners.discard(None)
    names: dict[str, str] = {}
    for profile in StaffProfile.objects.filter(
        Q(id__in=owners) | Q(user_id__in=owners)
    ).select_related("user"):
        name = profile.user.name if profile.user_id else ""
        names.setdefault(profile.id, name)
        if profile.user_id:
            names.setdefault(str(profile.user_id), name)
    return [
        FacilitatedCluster(
            cluster_id=cluster.id,
            name=cluster.name,
            district=cluster.district.name if cluster.district_id else "",
            schools=school_counts.get(cluster.id, 0),
            edify_officer=names.get(cluster.responsible_staff_id or "", "")
            or names.get(cluster.facilitator_assigned_by or "", ""),
            assigned_on=local_day(cluster.facilitator_assigned_at),
            sessions_planned=(planned.get(cluster.id) or {}).get("n", 0),
            next_session=(planned.get(cluster.id) or {}).get("first"),
        )
        for cluster in clusters
    ]


__all__ = [
    "FacilitatedCluster",
    "assign_facilitator",
    "default_facilitator_id",
    "facilitated_clusters",
    "facilitator_of",
    "upcoming_sessions",
]
