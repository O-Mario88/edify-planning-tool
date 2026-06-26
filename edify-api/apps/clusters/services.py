"""
Clusters service — ports the legacy clusters.service business logic.

Scope-constrained list, sub-county-unique create, school assignment, eligibility,
recommendations, and per-cluster intelligence. Sub-county uniqueness (§10): one
active cluster per sub-county by default — a 2nd requires CLUSTER_OVERRIDE.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q

from apps.core.enums import ClusterRecordStatus
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.geography.models import District, SubCounty
from apps.schools.models import School

from .models import Cluster, ClusterSubCounty, SchoolClusterAssignment


def _scope_filter(principal):
    """Returns a Q to constrain clusters to the user's districts (unless country
    scope). Mirrors the legacy `where.districtId = { in: scope.districtIds }`."""
    scope = resolve_user_scope(principal)
    if scope.country_scope or scope.can_view_summary_only:
        return Q(), scope
    if scope.district_ids:
        return Q(district_id__in=scope.district_ids), scope
    return Q(district_id__in=["__none__"]), scope


def list_clusters(principal) -> list[dict]:
    """List active/needs_review clusters within scope, with school counts + SSA."""
    scope_q, scope = _scope_filter(principal)
    qs = (
        Cluster.objects.filter(scope_q, deleted_at__isnull=True, status__in=["active", "needs_review"])
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
        .annotate(school_count=Count("assignments", filter=Q(assignments__school__deleted_at__isnull=True)))
        .order_by("name")[:1000]  # safety bound
    )
    out = []
    for c in qs:
        ssa_done = c.assignments.filter(school__deleted_at__isnull=True, school__current_fy_ssa_status="done").count()
        out.append(
            {
                "id": c.id,
                "name": c.name,
                "clusterType": c.cluster_type,
                "status": c.status,
                "district": {"name": c.district.name} if c.district_id else None,
                "subCounty": {"name": c.sub_county.name} if c.sub_county_id else None,
                "subCountyName": c.sub_county_name,
                "responsibleStaffId": c.responsible_staff_id,
                "clusterLeaderName": c.cluster_leader_name,
                "clusterLeaderPhone": c.cluster_leader_phone,
                "subCounties": [x.sub_county.name for x in c.covered_sub_counties.all()],
                "subCountyIds": [x.sub_county_id for x in c.covered_sub_counties.all()],
                "schoolCount": c.school_count,
                "schoolsWithSsa": ssa_done,
            }
        )
    return out


def _cluster_card(c: Cluster) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "district": c.district.name if c.district_id else None,
        "status": c.status,
        "clusterType": c.cluster_type,
        "subCounty": (c.sub_county.name if c.sub_county_id else None) or c.sub_county_name,
        "subCounties": [x.sub_county.name for x in c.covered_sub_counties.all()],
        "clusterLeaderName": c.cluster_leader_name,
        "clusterLeaderPhone": c.cluster_leader_phone,
        "schoolCount": getattr(c, "school_count", 0),
    }


def recommendations(school_id: str, principal) -> dict:
    """Cluster recommendations for a school (same sub-county + district)."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope)
    qs = base if base is not None else School.objects.all()
    school = qs.filter(school_id=school_id).select_related("sub_county").first()
    if not school:
        raise NotFoundError("School not found or outside scope")

    active = Q(deleted_at__isnull=True, status="active")
    same_sub: list[Cluster] = []
    if school.sub_county_id:
        same_sub = list(
            Cluster.objects.filter(active)
            .filter(Q(sub_county_id=school.sub_county_id) | Q(covered_sub_counties__sub_county_id=school.sub_county_id))
            .distinct()
            .select_related("district", "sub_county")
            .prefetch_related("covered_sub_counties__sub_county")
            .annotate(school_count=Count("assignments"))
        )
    same_sub_ids = {c.id for c in same_sub}
    same_district = [
        c
        for c in Cluster.objects.filter(active, district_id=school.district_id)
        .exclude(id__in=same_sub_ids)
        .select_related("district", "sub_county")
        .prefetch_related("covered_sub_counties__sub_county")
        .annotate(school_count=Count("assignments"))
    ]

    return {
        "schoolId": school_id,
        "district": school.district_id,
        "subCounty": school.sub_county.name if school.sub_county_id else None,
        "sameSubCounty": [_cluster_card(c) for c in same_sub],
        "sameDistrict": [_cluster_card(c) for c in same_district],
        "canCreate": Permission.CLUSTER_ASSIGN.value in scope.permissions,
        "hint": (
            f"No eligible cluster exists for this school's sub-county ({school.sub_county.name}). Create one."
            if not same_sub and school.sub_county_id
            else None
        ),
    }


def eligible_for_school(school_id: str, principal) -> dict:
    r = recommendations(school_id, principal)
    return {
        "schoolId": school_id,
        "subCounty": r["subCounty"],
        "eligible": r["sameSubCounty"],
        "districtAlternatives": r["sameDistrict"],
        "canCreate": r["canCreate"],
        "hint": r["hint"],
    }


def create_cluster(data: dict, principal) -> dict:
    """Create a cluster. Validates district↔region, sub-county↔district, and the
    sub-county uniqueness rule (override requires CLUSTER_OVERRIDE)."""
    region_id = data.get("regionId")
    district_id = data.get("districtId")
    district = District.objects.filter(id=district_id).first()
    if not district or district.region_id != region_id:
        raise BadRequest("district does not belong to region")

    scope = resolve_user_scope(principal)
    if not scope.country_scope and district_id not in scope.district_ids:
        raise Forbidden("District outside your scope")

    sub_ids = []
    if data.get("subCountyIds"):
        sub_ids = list(dict.fromkeys(data["subCountyIds"]))
    elif data.get("subCountyId"):
        sub_ids = [data["subCountyId"]]
    if not sub_ids:
        raise BadRequest("At least one sub-county is required")

    subs = list(SubCounty.objects.filter(id__in=sub_ids))
    if len(subs) != len(set(sub_ids)):
        raise BadRequest("Unknown sub-county")
    for sc in subs:
        if sc.district_id != district_id:
            raise BadRequest("sub-county does not belong to district")
    primary = next(s for s in subs if s.id == sub_ids[0])

    # Sub-county uniqueness: one active cluster per sub-county by default.
    needs_review = False
    taken = set(
        Cluster.objects.filter(deleted_at__isnull=True, status__in=["active", "needs_review"])
        .filter(Q(sub_county_id__in=sub_ids) | Q(covered_sub_counties__sub_county_id__in=sub_ids))
        .values_list("id", flat=True)
    )
    if taken:
        if Permission.CLUSTER_OVERRIDE.value in scope.permissions and data.get("overrideReason"):
            needs_review = True
        else:
            raise BadRequest("An active cluster already covers this sub-county.")

    with transaction.atomic():
        cluster = Cluster.objects.create(
            name=data.get("name") or f"{primary.name} Cluster",
            region_id=region_id,
            district_id=district_id,
            sub_county=primary,
            sub_county_name=primary.name,
            cluster_type=data.get("clusterType", "mixed"),
            status=ClusterRecordStatus.NEEDS_REVIEW if needs_review else ClusterRecordStatus.ACTIVE,
            override_reason=data.get("overrideReason"),
            responsible_staff_id=data.get("responsibleStaffId"),
            cluster_leader_name=data.get("clusterLeaderName"),
            cluster_leader_phone=data.get("clusterLeaderPhone"),
        )
        ClusterSubCounty.objects.bulk_create(
            [ClusterSubCounty(cluster=cluster, sub_county_id=sid) for sid in sub_ids]
        )
    return _cluster_card(cluster)


def create_from_school(data: dict, principal) -> dict:
    """Create a cluster seeded from a school (uses the school's geography)."""
    school = School.objects.filter(school_id=data.get("schoolId")).first()
    if not school:
        raise BadRequest("Unknown school.")
    payload = {
        "name": data.get("name") or f"{school.name} Cluster",
        "regionId": school.region_id,
        "districtId": school.district_id,
        "subCountyId": school.sub_county_id,
        "clusterType": data.get("clusterType", "mixed"),
        "responsibleStaffId": data.get("responsibleStaffId"),
        "clusterLeaderName": data.get("clusterLeaderName"),
        "clusterLeaderPhone": data.get("clusterLeaderPhone"),
    }
    return create_cluster(payload, principal)


def assign_school(school_id: str, data: dict, principal) -> dict:
    """Assign a school to a cluster (POST /schools/:id/cluster + /clusters/assign)."""
    cluster_id = data.get("clusterId")
    if not cluster_id:
        raise BadRequest("clusterId is required.")
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    SchoolClusterAssignment.objects.update_or_create(
        school=school, cluster=cluster, defaults={"assigned_by": principal.user_id}
    )
    # Update the school's denormalized cluster pointer + status.
    school.cluster_id = cluster.id
    school.cluster_status = "clustered"
    school.save(update_fields=["cluster_id", "cluster_status", "updated_at"])
    return {"ok": True, "schoolId": school.school_id, "clusterId": cluster.id}


def assign(data: dict, principal) -> dict:
    """POST /clusters/assign — body {schoolId, clusterId}."""
    return assign_school(data.get("schoolId", ""), data, principal)


def cluster_schools(cluster_id: str, principal) -> list[dict]:
    """Schools in a cluster."""
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = (
        School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
        .order_by("name")
        .values("id", "school_id", "name", "school_type", "current_fy_ssa_status", "enrollment")
    )
    return [
        {
            "id": s["id"],
            "schoolId": s["school_id"],
            "name": s["name"],
            "schoolType": s["school_type"],
            "currentFySsaStatus": s["current_fy_ssa_status"],
            "enrollment": s["enrollment"],
        }
        for s in schools
    ]


def cluster_intelligence(cluster_id: str, principal) -> dict:
    """Per-cluster intelligence surface."""
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")
    schools = School.objects.filter(cluster_assignments__cluster=cluster, deleted_at__isnull=True)
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    return {
        "id": cluster.id,
        "name": cluster.name,
        "schoolCount": total,
        "coverage": round((ssa_done / total * 100), 1) if total else 0.0,
        "schoolsWithSsa": ssa_done,
        "subCounties": [x.sub_county.name for x in cluster.covered_sub_counties.all()],
        "clusterType": cluster.cluster_type,
    }


def sub_counties_without_clusters(principal) -> list[dict]:
    """Gap board: sub-counties in scope with no active cluster."""
    scope_q, scope = _scope_filter(principal)
    covered = set(
        ClusterSubCounty.objects.filter(
            cluster__deleted_at__isnull=True, cluster__status="active"
        ).values_list("sub_county_id", flat=True)
    )
    qs = SubCounty.objects.all()
    if not scope.country_scope and scope.district_ids:
        qs = qs.filter(district_id__in=scope.district_ids)
    return [
        {"id": s.id, "name": s.name, "districtId": s.district_id}
        for s in qs.exclude(id__in=covered).order_by("name")[:500]
    ]


def cluster_planning(principal) -> list[dict]:
    """Per-cluster planning intelligence (cadence, SSA, coverage)."""
    return [cluster_intelligence(c.id, principal) for c in Cluster.objects.filter(deleted_at__isnull=True, status="active")]


__all__ = [
    "list_clusters",
    "recommendations",
    "eligible_for_school",
    "create_cluster",
    "create_from_school",
    "assign_school",
    "assign",
    "cluster_schools",
    "cluster_intelligence",
    "sub_counties_without_clusters",
    "cluster_planning",
]
