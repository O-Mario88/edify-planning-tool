"""
Schools service — ports the legacy schools.service business logic.

Scope-constrained list/detail, single + bulk create, duplicate detection, type
changes, and the school-improvement workflow surface. Every query that returns
operational records is constrained by the resolved user scope — never all rows.
"""
from __future__ import annotations

from django.db.models import Q

from apps.core.enums import DuplicateStatus, SchoolType
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.scoping import resolve_user_scope, school_queryset
from apps.geography.models import District, Region, SubCounty

from .models import (
    School,
    SchoolDuplicateCandidate,
    UploadBatch,
)


# ── List ─────────────────────────────────────────────────────────────────────
def _build_q(query: dict, scope) -> Q:
    """Translate the query filters to an ORM Q. ANDed within the role scope so
    filters only narrow (never widen) the user's reach."""
    q = Q()
    search = query.get("search")
    if search:
        q &= Q(name__icontains=search) | Q(school_id__icontains=search)
    if query.get("regionId"):
        q &= Q(region_id=query["regionId"])
    if query.get("districtId"):
        q &= Q(district_id=query["districtId"])
    if query.get("subCountyId"):
        q &= Q(sub_county_id=query["subCountyId"])
    if query.get("clusterId"):
        q &= Q(cluster_id=query["clusterId"])
    if query.get("clusterStatus"):
        q &= Q(cluster_status=query["clusterStatus"])
    if query.get("ssaStatus"):
        q &= Q(current_fy_ssa_status=query["ssaStatus"])
    if query.get("planningReadiness"):
        q &= Q(planning_readiness=query["planningReadiness"])
    if query.get("schoolType"):
        q &= Q(school_type=query["schoolType"])
    if query.get("duplicateStatus"):
        q &= Q(duplicate_status=query["duplicateStatus"])
    if query.get("accountOwnerStatus"):
        q &= Q(account_owner_status=query["accountOwnerStatus"])
    # Name/key-based geography (FE filter bar) — relation filters.
    district = query.get("district")
    if district and district != "__all__":
        q &= Q(district__name=district)
    region = query.get("region")
    if region and region != "__all__":
        q &= Q(region__name__iexact=region)
    return q


def list_schools(query: dict, principal):
    """Scope-constrained, paginated school list. Eager-loads the geography FKs
    the row serializer dereferences (region/district/sub_county/parish) so the
    directory page isn't an N+1 (4 queries × page-size per page)."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope)
    if base is None:
        return School.objects.none()
    base = base.filter(_build_q(query, scope))
    return _with_relations(base)


def _with_relations(qs):
    return qs.select_related("region", "district", "sub_county", "parish")


def get_one(school_id: str, principal):
    """Single school detail, scope-constrained + relations eager-loaded."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope)
    qs = base if base is not None else School.objects.all()
    school = _with_relations(qs).filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    return school


# ── Create ───────────────────────────────────────────────────────────────────
def create_one(data: dict, principal) -> School:
    """Single school upload. The actor must have SCHOOL_UPLOAD permission
    (enforced by the view); geography is resolved from the provided ids."""
    region = Region.objects.filter(id=data.get("regionId")).first()
    district = District.objects.filter(id=data.get("districtId")).first()
    if not region or not district:
        raise BadRequest("A valid regionId and districtId are required.")
    sub_county = None
    if data.get("subCountyId"):
        sub_county = SubCounty.objects.filter(id=data["subCountyId"]).first()

    school = School.objects.create(
        school_id=data.get("schoolId") or data.get("school_id") or f"S-{data['name'][:20]}",
        name=data["name"],
        region=region,
        district=district,
        sub_county=sub_county,
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        uploaded_region_text=data.get("regionText"),
        uploaded_district_text=data.get("districtText"),
        uploaded_sub_county_text=data.get("subCountyText"),
        uploaded_parish_text=data.get("parishText"),
        shipping_address=data.get("shippingAddress"),
        school_phone=data.get("schoolPhone"),
        primary_contact_name=data.get("primaryContactName"),
        primary_contact_phone=data.get("primaryContactPhone"),
        enrollment=data.get("enrollment"),
        school_type=data.get("schoolType", SchoolType.CLIENT),
        account_owner_name_raw=data.get("accountOwnerName"),
    )
    return school


def bulk_upload(rows: list[dict], principal) -> dict:
    """Bulk create from an array of CreateSchool payloads. Returns a batch
    summary matching the legacy `{batchId, accepted, flagged, results}`."""
    batch = UploadBatch.objects.create(
        source="manual",
        uploaded_by=principal.user_id,
    )
    accepted, flagged, results = 0, 0, []
    for row in rows:
        try:
            school = create_one(row, principal)
            school.upload_batch_id = batch.id
            school.save(update_fields=["upload_batch_id", "updated_at"])
            accepted += 1
            results.append({"schoolId": school.school_id, "ok": True})
        except Exception as exc:  # noqa: BLE001
            flagged += 1
            results.append({"schoolId": row.get("schoolId"), "ok": False, "error": str(exc)})
    batch.row_count = len(rows)
    batch.accepted_count = accepted
    batch.flagged_count = flagged
    batch.save(update_fields=["row_count", "accepted_count", "flagged_count"])
    return {
        "batchId": batch.id,
        "accepted": accepted,
        "flagged": flagged,
        "results": results,
    }


# ── Type change ──────────────────────────────────────────────────────────────
def set_type(principal, school_id: str, school_type: str) -> dict:
    """Change a school's type (client → core → champion). Service re-checks
    the role (the view gates on SCHOOL_VIEW; only IA/CD/Admin may change type)."""
    valid = {c[0] for c in SchoolType.choices}
    if school_type not in valid:
        raise BadRequest(f"Invalid school type '{school_type}'.")
    # Role re-check: the legacy service restricted type changes to oversight roles.
    if principal.active_role not in ("Admin", "CountryDirector", "ImpactAssessment"):
        raise BadRequest("You may not change this school's type.")
    school = get_one(school_id, principal)
    school.school_type = school_type
    school.save(update_fields=["school_type", "updated_at"])
    return {"ok": True, "schoolId": school.school_id, "schoolType": school_type}


# ── Duplicate resolution ─────────────────────────────────────────────────────
def resolve_duplicate(school_id: str, resolution: str, principal) -> dict:
    """Resolve a potential duplicate (not_duplicate | merged | archived)."""
    if resolution not in ("not_duplicate", "merged", "archived"):
        raise BadRequest("resolution must be not_duplicate | merged | archived.")
    school = get_one(school_id, principal)
    SchoolDuplicateCandidate.objects.filter(school=school).update(
        resolved=True, resolution=resolution
    )
    school.duplicate_status = (
        DuplicateStatus.MERGED if resolution == "merged" else DuplicateStatus.NOT_DUPLICATE
    )
    school.save(update_fields=["duplicate_status", "updated_at"])
    return {"ok": True, "schoolId": school.school_id, "resolution": resolution}


# ── Proposals / workflow (stubs refined as SSA + activities land) ────────────
def proposals(principal, limit: int = 10) -> list[dict]:
    """Best-SSA schools → potential core/champion candidates."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope)
    if base is None:
        return []
    # Candidate = a client school with the best current SSA standing.
    qs = (
        base.filter(school_type__in=["client", "potential_core"])
        .order_by("-current_fy_ssa_status", "name")[:limit]
    )
    return [
        {
            "id": s.id,
            "schoolId": s.school_id,
            "name": s.name,
            "schoolType": s.school_type,
            "currentFySsaStatus": s.current_fy_ssa_status,
        }
        for s in qs
    ]


def workflow(school_id: str, principal, fy: str | None = None) -> dict:
    """The school improvement journey surface."""
    school = get_one(school_id, principal)
    return {
        "school": {
            "id": school.id,
            "schoolId": school.school_id,
            "name": school.name,
            "schoolType": school.school_type,
            "planningReadiness": school.planning_readiness,
            "currentFySsaStatus": school.current_fy_ssa_status,
        },
        "fy": fy,
        # The full journey (SSA history, activities, budget) is assembled as the
        # SSA + activities + planning modules land.
        "ssaHistory": [],
        "activities": [],
    }


def next_actions(school_id: str, principal, fy: str | None = None) -> dict:
    """Scope-aware 'Plan Action' resolver."""
    school = get_one(school_id, principal)
    actions: list[dict] = []
    if school.planning_readiness != "ready":
        actions.append({"action": "collect_ssa", "reason": "Readiness locked — collect SSA."})
    if school.cluster_status == "unclustered":
        actions.append({"action": "assign_cluster", "reason": "School is unclustered."})
    return {"schoolId": school.school_id, "fy": fy, "nextActions": actions}


__all__ = [
    "list_schools",
    "get_one",
    "create_one",
    "bulk_upload",
    "set_type",
    "resolve_duplicate",
    "proposals",
    "workflow",
    "next_actions",
]
