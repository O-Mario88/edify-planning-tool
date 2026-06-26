"""Filters — shared filter-bar options + counts."""
from __future__ import annotations

from django.db.models import Count, Q

from apps.core.scoping import resolve_user_scope, school_queryset
from apps.schools.models import School


def options(principal) -> dict:
    """Distinct values for the filter bar (regions, districts, types, statuses)."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope) or School.objects.none()
    return {
        "regions": sorted(set(x for x in base.values_list("region__name", flat=True) if x)),
        "districts": sorted(set(x for x in base.values_list("district__name", flat=True) if x)),
        "schoolTypes": sorted(set(base.values_list("school_type", flat=True))),
        "clusterStatuses": sorted(set(base.values_list("cluster_status", flat=True))),
        "ssaStatuses": sorted(set(base.values_list("current_fy_ssa_status", flat=True))),
        "planningReadiness": sorted(set(base.values_list("planning_readiness", flat=True))),
    }


def counts(query: dict, principal) -> dict:
    scope = resolve_user_scope(principal)
    base = school_queryset(scope) or School.objects.none()
    q = Q()
    for f in ("school_type", "cluster_status", "current_fy_ssa_status", "planning_readiness"):
        if query.get(f):
            q &= Q(**{f: query[f]})
    return {
        "total": base.filter(q).count(),
        "bySchoolType": dict(base.filter(q).values_list("school_type").annotate(c=Count("id")).values_list("school_type", "c")),
        "byClusterStatus": dict(base.filter(q).values_list("cluster_status").annotate(c=Count("id")).values_list("cluster_status", "c")),
    }


def core_header_summary(principal) -> dict:
    scope = resolve_user_scope(principal)
    base = school_queryset(scope) or School.objects.none()
    return {
        "total": base.count(),
        "core": base.filter(school_type="core").count(),
        "champion": base.filter(school_type="champion").count(),
        "client": base.filter(school_type="client").count(),
    }
