"""Cluster catchments — which districts' schools a cluster may take.

Owner, 2026-09-15: "A school may join a cluster located in another district
when that cluster legitimately serves nearby border communities. Do not allow
users to select any cluster anywhere in the country."

The absolute rule "a school joins a cluster in its own district" is replaced by
one governed question, answered here and nowhere else:

    Does this cluster, on this date, serve this school's canonical district?

A cluster serves its PRIMARY district — its own, always — and any NEIGHBOURING
district a Country Director or Admin approved for it, with a reason, inside
the approval's effective window, and only within the same country. Joining a
cluster never changes a school's district, sub-county, parish or village.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

from .models import CatchmentRelationship, Cluster, ClusterServiceDistrict

#: Shown when a cluster does not serve the school's district. The brief's
#: honest empty state, reused by the drawer and the service refusal.
NOT_IN_CATCHMENT = (
    "{cluster} does not serve {district}. A school joins a cluster in its own "
    "district, or in a neighbouring district the cluster is approved to serve."
)


@dataclass(frozen=True)
class CatchmentMatch:
    """How a cluster serves one district."""

    catchment: ClusterServiceDistrict | None
    relationship_type: str

    @property
    def is_cross_district(self) -> bool:
        return self.relationship_type == CatchmentRelationship.NEIGHBOURING


def _today() -> date:
    return timezone.localdate()


def active_on(on_date: date | None = None) -> Q:
    """Catchment rows in force on a date."""
    on_date = on_date or _today()
    return Q(active=True, effective_from__lte=on_date) & (
        Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
    )


def country_of_district(district) -> str:
    region = getattr(district, "region", None)
    return (getattr(region, "country", None) or "Uganda").strip()


def serving_match(
    cluster: Cluster, district_id: str | None, on_date: date | None = None
) -> CatchmentMatch | None:
    """How ``cluster`` serves ``district_id`` on ``on_date``, or None.

    The cluster's own district always counts, even before its PRIMARY row is
    written (a cluster created this second), so the rule can never refuse a
    same-district membership that has always been allowed.
    """
    if cluster is None or not district_id:
        return None
    rows = list(
        ClusterServiceDistrict.objects.filter(
            active_on(on_date), cluster_id=cluster.id, district_id=district_id
        ).order_by("relationship_type")
    )
    if rows:
        row = rows[0]
        return CatchmentMatch(row, row.relationship_type)
    if cluster.district_id == district_id:
        return CatchmentMatch(None, CatchmentRelationship.PRIMARY)
    return None


def clusters_serving_district_q(district_id: str, on_date: date | None = None) -> Q:
    """A Cluster filter for the clusters serving one district."""
    served = ClusterServiceDistrict.objects.filter(
        active_on(on_date), district_id=district_id
    ).values("cluster_id")
    return Q(district_id=district_id) | Q(id__in=served)


def service_districts_by_cluster(cluster_ids, on_date: date | None = None) -> dict:
    """{cluster_id: [ClusterServiceDistrict, ...]} in force, one query."""
    out: dict[str, list] = {}
    for row in (
        ClusterServiceDistrict.objects.filter(
            active_on(on_date), cluster_id__in=list(cluster_ids)
        )
        .select_related("district")
        .order_by("relationship_type", "district__name")
    ):
        out.setdefault(row.cluster_id, []).append(row)
    return out


# ── Governance writes ────────────────────────────────────────────────────────
def _actor_id(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def may_manage_catchments(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.CLUSTER_CATCHMENT_MANAGE.value)
    )


def ensure_primary_catchment(cluster: Cluster, actor_id: str = "system") -> None:
    """Keep the PRIMARY row equal to the cluster's own district.

    Called whenever a cluster is created or its district changes. A change of
    district ends the old PRIMARY row (history kept) and opens a new one.
    """
    if cluster is None or not cluster.district_id:
        return
    today = _today()
    with transaction.atomic():
        current = (
            ClusterServiceDistrict.objects.select_for_update()
            .filter(
                cluster=cluster,
                active=True,
                relationship_type=CatchmentRelationship.PRIMARY,
            )
            .first()
        )
        if current is not None and current.district_id == cluster.district_id:
            return
        if current is not None:
            current.active = False
            current.effective_to = max(today, current.effective_from)
            current.ended_by = actor_id
            current.ended_reason = "The cluster moved to another district."
            current.save(
                update_fields=[
                    "active",
                    "effective_to",
                    "ended_by",
                    "ended_reason",
                    "updated_at",
                ]
            )
        # The new primary district may have been an approved neighbour; the
        # primary relationship replaces it rather than colliding with it.
        ClusterServiceDistrict.objects.filter(
            cluster=cluster, district_id=cluster.district_id, active=True
        ).update(
            active=False,
            effective_to=today,
            ended_by=actor_id,
            ended_reason="Became the cluster's primary district.",
            updated_at=timezone.now(),
        )
        ClusterServiceDistrict.objects.create(
            cluster=cluster,
            district_id=cluster.district_id,
            relationship_type=CatchmentRelationship.PRIMARY,
            reason="The cluster's own district.",
            effective_from=today,
            created_by=actor_id,
            approved_by=actor_id,
            approved_at=timezone.now(),
        )


@transaction.atomic
def approve_neighbouring_district(
    cluster_id: str,
    district_id: str,
    principal,
    *,
    reason: str,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> ClusterServiceDistrict:
    """Approve one neighbouring district for one cluster."""
    from apps.geography.models import District

    if not may_manage_catchments(principal):
        raise Forbidden(
            "Only a Country Director or Admin approves the districts a cluster serves."
        )
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise BadRequest(
            "Give the reason this cluster serves the neighbouring district "
            "(at least 10 characters)."
        )
    cluster = (
        Cluster.objects.select_for_update()
        .select_related("district__region")
        .filter(id=cluster_id, deleted_at__isnull=True)
        .first()
    )
    if cluster is None:
        raise NotFoundError("Cluster not found.")
    district = District.objects.select_related("region").filter(id=district_id).first()
    if district is None:
        raise BadRequest("Choose a district.")
    if district.id == cluster.district_id:
        raise BadRequest(f"{district.name} is already {cluster.name}'s own district.")
    if country_of_district(district) != country_of_district(cluster.district):
        raise BadRequest(
            f"{district.name} is in {country_of_district(district)}; {cluster.name} "
            f"serves {country_of_district(cluster.district)}. A cluster never serves "
            "another country."
        )
    from apps.core.scoping import country_bound, resolve_user_scope

    scope = resolve_user_scope(principal)
    if country_bound(scope) and scope.country != country_of_district(cluster.district):
        raise Forbidden("That cluster is outside your country.")
    effective_from = effective_from or _today()
    if effective_to and effective_to < effective_from:
        raise BadRequest("The end date cannot be before the start date.")
    if ClusterServiceDistrict.objects.filter(
        cluster=cluster, district=district, active=True
    ).exists():
        raise BadRequest(f"{cluster.name} already serves {district.name}.")

    ensure_primary_catchment(cluster, _actor_id(principal))
    row = ClusterServiceDistrict.objects.create(
        cluster=cluster,
        district=district,
        relationship_type=CatchmentRelationship.NEIGHBOURING,
        reason=reason,
        effective_from=effective_from,
        effective_to=effective_to,
        created_by=_actor_id(principal),
        approved_by=_actor_id(principal),
        approved_at=timezone.now(),
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="cluster.catchment_approved",
        subject_kind="cluster",
        subject_id=cluster.id,
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "previous": None,
            "new": {
                "catchmentId": row.id,
                "districtId": district.id,
                "districtName": district.name,
                "relationship": row.relationship_type,
                "effectiveFrom": row.effective_from.isoformat(),
                "effectiveTo": (
                    row.effective_to.isoformat() if row.effective_to else None
                ),
            },
        },
    )
    return row


@transaction.atomic
def end_catchment(
    catchment_id: str, principal, *, reason: str
) -> ClusterServiceDistrict:
    """End an approved neighbouring district. Existing members stay where they
    are and appear on the review list; nobody is moved out silently."""
    if not may_manage_catchments(principal):
        raise Forbidden(
            "Only a Country Director or Admin changes the districts a cluster serves."
        )
    row = (
        ClusterServiceDistrict.objects.select_for_update()
        .select_related("cluster", "district")
        .filter(id=catchment_id, active=True)
        .first()
    )
    if row is None:
        raise NotFoundError("Approved district not found.")
    if row.relationship_type == CatchmentRelationship.PRIMARY:
        raise BadRequest("A cluster always serves its own district.")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("Give the reason the approval ends.")
    row.active = False
    row.effective_to = max(_today(), row.effective_from)
    row.ended_by = _actor_id(principal)
    row.ended_reason = reason
    row.save(
        update_fields=[
            "active",
            "effective_to",
            "ended_by",
            "ended_reason",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="cluster.catchment_ended",
        subject_kind="cluster",
        subject_id=row.cluster_id,
        actor_id=_actor_id(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "previous": {"catchmentId": row.id, "districtId": row.district_id},
            "new": None,
        },
    )
    return row


def memberships_outside_catchment(limit: int = 500) -> list:
    """Current memberships whose school district the cluster does not serve.

    The review list the backfill promised: a cross-district membership that
    predates catchments, or one whose approval has since ended. Listed for a
    person to approve the district or move the school — never changed here.
    """
    from apps.schools.models import School

    served = {
        (row.cluster_id, row.district_id)
        for row in ClusterServiceDistrict.objects.filter(active_on()).only(
            "cluster_id", "district_id"
        )
    }
    clusters = {
        c.id: c
        for c in Cluster.objects.filter(deleted_at__isnull=True).select_related(
            "district"
        )
    }
    rows = []
    for school in (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .select_related("district")
        .only("id", "name", "school_id", "cluster_id", "district_id", "district__name")
        .iterator(chunk_size=1000)
    ):
        cluster = clusters.get(school.cluster_id)
        if cluster is None or not school.district_id:
            continue
        if school.district_id == cluster.district_id:
            continue
        if (cluster.id, school.district_id) in served:
            continue
        rows.append({"school": school, "cluster": cluster})
        if len(rows) >= limit:
            break
    return rows


__all__ = [
    "CatchmentMatch",
    "NOT_IN_CATCHMENT",
    "active_on",
    "approve_neighbouring_district",
    "clusters_serving_district_q",
    "country_of_district",
    "end_catchment",
    "ensure_primary_catchment",
    "may_manage_catchments",
    "memberships_outside_catchment",
    "service_districts_by_cluster",
    "serving_match",
]
