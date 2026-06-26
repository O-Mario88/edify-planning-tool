"""
Analytics service — role-scoped summaries + SSA performance + impact +
correlation + contribution. Aggregates over the schools/SSA/activities models,
scope-constrained. Ports the legacy analytics.service aggregation logic.
"""
from __future__ import annotations

from django.db.models import Avg, Count, Q, Sum

from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, school_queryset, aggregate_school_filter
from apps.schools.models import School


def _scoped_schools(principal):
    scope = resolve_user_scope(principal)
    qs = School.objects.filter(deleted_at__isnull=True)
    if scope.country_scope or scope.can_view_summary_only:
        return qs, scope
    if scope.school_ids:
        return qs.filter(id__in=scope.school_ids), scope
    return qs.none(), scope


def dashboard_summary(principal, query: dict) -> dict:
    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    return {
        "fy": fy,
        "schoolsTotal": schools.count(),
        "coreSchools": schools.filter(school_type="core").count(),
        "championSchools": schools.filter(school_type="champion").count(),
        "clientSchools": schools.filter(school_type="client").count(),
        "ssaDone": schools.filter(current_fy_ssa_status="done").count(),
        "ssaMissing": schools.exclude(current_fy_ssa_status="done").count(),
        "clustered": schools.filter(cluster_status="clustered").count(),
        "planningReady": schools.filter(planning_readiness="ready").count(),
        "countryScope": scope.country_scope,
        "summaryOnly": scope.can_view_summary_only,
    }


def leadership_summary(principal, query: dict) -> dict:
    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    return {
        "fy": fy,
        "coverage": round((ssa_done / total * 100), 1) if total else 0,
        "schoolsTotal": total,
        "coreSchools": schools.filter(school_type__in=["core", "champion"]).count(),
        "readySchools": schools.filter(planning_readiness="ready").count(),
        "avgEnrollment": schools.aggregate(a=Avg("enrollment"))["a"] or 0,
    }


def district_rollups(principal, query: dict) -> list[dict]:
    schools, scope = _scoped_schools(principal)
    rows = (
        schools.values("district__name")
        .annotate(
            total=Count("id"),
            ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
            core=Count("id", filter=Q(school_type__in=["core", "champion"])),
        )
        .order_by("district__name")
    )
    return [
        {
            "district": r["district__name"],
            "total": r["total"],
            "ssaDone": r["ssa_done"],
            "coverage": round((r["ssa_done"] / r["total"] * 100), 1) if r["total"] else 0,
            "core": r["core"],
        }
        for r in rows
    ]


def coverage_summary(principal, query: dict) -> dict:
    schools, scope = _scoped_schools(principal)
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    clustered = schools.filter(cluster_status="clustered").count()
    return {
        "ssaCoverage": round((ssa_done / total * 100), 1) if total else 0,
        "clusterCoverage": round((clustered / total * 100), 1) if total else 0,
        "schoolsTotal": total,
    }


def geo_map_districts(principal, query: dict) -> list[dict]:
    return district_rollups(principal, query)


def geo_map_district_detail(principal, district_id: str) -> dict:
    schools, scope = _scoped_schools(principal)
    qs = schools.filter(district_id=district_id)
    return {
        "districtId": district_id,
        "schoolCount": qs.count(),
        "schools": [
            {"id": s.id, "schoolId": s.school_id, "name": s.name,
             "schoolType": s.school_type, "latitude": s.latitude, "longitude": s.longitude}
            for s in qs[:500]
        ],
    }


def school_directory_summary(principal, query: dict) -> dict:
    return dashboard_summary(principal, query)


def ssa_performance(principal, query: dict) -> dict:
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    school_ids = list(schools.values_list("id", flat=True))
    records = SsaRecord.objects.filter(school_id__in=school_ids, fy=fy, deleted_at__isnull=True)
    avg = records.aggregate(a=Avg("average_score"))["a"]
    return {
        "fy": fy,
        "recordsCount": records.count(),
        "averageScore": round(avg, 2) if avg else None,
    }


def ssa_performance_grouped(principal, query: dict) -> list[dict]:
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    group_by = query.get("groupBy", "district")
    relation = {"region": "school__region__name", "district": "school__district__name",
                "cluster": "school__cluster_id", "subCounty": "school__sub_county__name"}.get(group_by, "school__district__name")
    records = SsaRecord.objects.filter(school__in=schools, fy=fy, deleted_at__isnull=True)
    rows = records.values(relation).annotate(avg=Avg("average_score"), count=Count("id")).order_by(relation)
    return [{"group": r[relation], "averageScore": round(r["avg"], 2), "count": r["count"]} for r in rows]


def intervention_improvement(principal, query: dict) -> dict:
    """Previous vs current FY SSA change per intervention."""
    from apps.ssa.models import SsaScore

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    prev_fy = str(int(fy) - 1)
    out = {}
    for intervention, _ in SsaScore._meta.get_field("intervention").choices:
        curr = SsaScore.objects.filter(
            ssa_record__school__in=schools, ssa_record__fy=fy, intervention=intervention
        ).aggregate(a=Avg("score"))["a"]
        prev = SsaScore.objects.filter(
            ssa_record__school__in=schools, ssa_record__fy=prev_fy, intervention=intervention
        ).aggregate(a=Avg("score"))["a"]
        out[intervention] = {"current": round(curr, 2) if curr else None, "previous": round(prev, 2) if prev else None}
    return out


def support_ssa_correlation(principal, query: dict) -> dict:
    """Layer-3 correlation: does support timing improve SSA?"""
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    # For each school with both support + SSA this FY, compare SSA avg.
    school_ids = list(schools.values_list("id", flat=True))
    with_support = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True,
        school__activities__deleted_at__isnull=True,
        school__activities__fy=fy,
    ).distinct().aggregate(a=Avg("average_score"))["a"]
    without_support = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True,
    ).exclude(school__activities__fy=fy).aggregate(a=Avg("average_score"))["a"]
    return {
        "fy": fy,
        "withSupportAvg": round(with_support, 2) if with_support else None,
        "withoutSupportAvg": round(without_support, 2) if without_support else None,
    }


def staff_vs_partner_correlation(principal, query: dict) -> dict:
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    staff = SsaRecord.objects.filter(
        school__in=schools, fy=fy, collector_type="staff", deleted_at__isnull=True
    ).aggregate(a=Avg("average_score"))["a"]
    partner = SsaRecord.objects.filter(
        school__in=schools, fy=fy, collector_type="partner", deleted_at__isnull=True
    ).aggregate(a=Avg("average_score"))["a"]
    return {
        "staffAvg": round(staff, 2) if staff else None,
        "partnerAvg": round(partner, 2) if partner else None,
    }


def activity_pipeline(principal, query: dict) -> dict:
    from apps.activities.models import Activity

    scope = resolve_user_scope(principal)
    fy = query.get("fy") or get_operational_fy()
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()
    return {
        "fy": fy,
        "total": qs.count(),
        "byStatus": {s: qs.filter(status=s).count() for s in ("planned", "scheduled", "completed", "awaiting_ia_verification")},
        "completed": qs.filter(status__in=["completed", "ia_verified"]).count(),
    }


def contribution_summary(principal, query: dict) -> dict:
    """Contribution by lens (own/team/combined)."""
    from apps.activities.models import Activity

    scope = resolve_user_scope(principal)
    fy = query.get("fy") or get_operational_fy()
    lens = query.get("lens", "own")
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, status__in=["completed", "ia_verified"])
    if lens == "team" and scope.supervised_staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.supervised_staff_ids)
    elif scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    else:
        qs = qs.none()
    return {
        "fy": fy, "lens": lens,
        "completedActivities": qs.count(),
        "byType": dict(qs.values_list("activity_type").annotate(c=Count("id")).values_list("activity_type", "c")),
    }


def recruitment_recommendation(principal, query: dict) -> dict:
    """Recruit-more vs focus-advisory recommendation."""
    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    coverage = (ssa_done / total * 100) if total else 0
    if coverage < 50:
        rec = "focus_advisory"
        reason = f"SSA coverage is {coverage:.0f}% — consolidate before recruiting."
    else:
        rec = "recruit_more"
        reason = f"SSA coverage is {coverage:.0f}% — capacity to recruit."
    return {"fy": fy, "recommendation": rec, "reason": reason, "coverage": round(coverage, 1)}


__all__ = [
    "dashboard_summary", "leadership_summary", "district_rollups", "coverage_summary",
    "geo_map_districts", "geo_map_district_detail", "school_directory_summary",
    "ssa_performance", "ssa_performance_grouped", "intervention_improvement",
    "support_ssa_correlation", "staff_vs_partner_correlation", "activity_pipeline",
    "contribution_summary", "recruitment_recommendation",
]
