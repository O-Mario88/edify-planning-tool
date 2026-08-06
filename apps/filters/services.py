"""Filters — shared filter-bar options + counts."""

from __future__ import annotations

from django.db.models import Count, Q

from apps.core.scoping import resolve_user_scope, school_queryset
from apps.schools.models import School


def _distinct(base, column: str) -> list[str]:
    """The distinct values of one column, deduplicated by the database.

    Each of these used to pull every in-scope school row into Python to build
    a set — six full scans of the directory on every filter-bar render, 90,000
    values transferred at full estate size, to produce at most a few dozen
    options. `.order_by()` clears School's default `-created_at` ordering
    first: leaving it in makes Postgres reject the DISTINCT (the ordering
    column is not in the select list) and would defeat the deduplication
    anyway, since every row's timestamp is different.
    """
    return sorted(
        x for x in base.order_by().values_list(column, flat=True).distinct() if x
    )


def options(principal) -> dict:
    """Distinct values for the filter bar (regions, districts, types, statuses)."""
    scope = resolve_user_scope(principal)
    base = school_queryset(scope) or School.objects.none()
    return {
        "regions": _distinct(base, "region__name"),
        "districts": _distinct(base, "district__name"),
        "schoolTypes": _distinct(base, "school_type"),
        "clusterStatuses": _distinct(base, "cluster_status"),
        "ssaStatuses": _distinct(base, "current_fy_ssa_status"),
        "planningReadiness": _distinct(base, "planning_readiness"),
    }


def counts(query: dict, principal) -> dict:
    scope = resolve_user_scope(principal)
    base = school_queryset(scope) or School.objects.none()
    q = Q()
    for f in (
        "school_type",
        "cluster_status",
        "current_fy_ssa_status",
        "planning_readiness",
    ):
        if query.get(f):
            q &= Q(**{f: query[f]})
    return {
        "total": base.filter(q).count(),
        "bySchoolType": dict(
            base.filter(q)
            .values_list("school_type")
            .annotate(c=Count("id"))
            .values_list("school_type", "c")
        ),
        "byClusterStatus": dict(
            base.filter(q)
            .values_list("cluster_status")
            .annotate(c=Count("id"))
            .values_list("cluster_status", "c")
        ),
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
