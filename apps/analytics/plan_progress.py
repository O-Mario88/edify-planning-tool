"""Planned versus achieved field work, per district and per sub-county.

The Distribution by Sub-Region table (owner, 2026-09-15) reads, for every
boundary: how many school visits, cluster meetings and cluster trainings are
planned this FY, how many of each have been achieved, and how many activities
have been assigned to a partner. One definition here feeds the sub-region
roll-up, the district rows and the sub-county rows, so the three levels of
the same table cannot disagree about what "planned" means.

* Planned is every live activity in the FY -- one still to happen or one
  already delivered -- so achieved is always a subset of planned. Cancelled,
  rejected, deferred and never-planned rows are nobody's plan.
* Achieved is the completed set the rest of the dashboard uses
  (``COMPLETED_STATUSES``): the work happened, whether or not finance has
  finished with it.
* Assigned to a partner counts live activities delivered by a partner,
  whatever their type.

School work reaches its district through the school; cluster sessions through
the cluster, which has no school row of its own.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Count, Q

from apps.analytics.pl_analytics_service import COMPLETED_STATUSES, PLANNED_STATUSES
from apps.core.activity_types import CLUSTER_MEETING_TYPES, VISIT_TYPES

# Cluster trainings only: an in-school training is a school's, not a cluster's.
CLUSTER_TRAINING_TYPES: tuple[str, ...] = (
    "cluster_training",
    "cluster_training_ssa_collection",
)

#: Planned or delivered -- the activities a plan is made of.
LIVE_STATUSES: tuple[str, ...] = tuple(PLANNED_STATUSES) + tuple(COMPLETED_STATUSES)

#: The seven figures, in the table's column order. Every level carries all of
#: them, as integers, zero when nothing is planned.
PLAN_PROGRESS_FIELDS: tuple[str, ...] = (
    "visits_planned",
    "visits_achieved",
    "cluster_meetings_planned",
    "cluster_meetings_achieved",
    "cluster_trainings_planned",
    "cluster_trainings_achieved",
    "assigned_to_partner",
)


def empty_progress() -> dict[str, int]:
    return {field: 0 for field in PLAN_PROGRESS_FIELDS}


def _live_activities(activities, fy: str | None):
    from apps.activities.models import Activity

    qs = (
        activities
        if activities is not None
        else Activity.objects.filter(deleted_at__isnull=True)
    ).filter(status__in=LIVE_STATUSES)
    if fy:
        qs = qs.filter(fy=fy)
    return qs


def _count_by(qs, key: str) -> dict[Any, dict[str, int]]:
    """The seven figures per value of ``key`` (a district or sub-county id)."""
    achieved = Q(status__in=COMPLETED_STATUSES)
    visits = Q(activity_type__in=VISIT_TYPES)
    meetings = Q(activity_type__in=CLUSTER_MEETING_TYPES)
    trainings = Q(activity_type__in=CLUSTER_TRAINING_TYPES)
    rows = (
        qs.filter(**{f"{key}__isnull": False})
        .values(key)
        .annotate(
            visits_planned=Count("id", filter=visits),
            visits_achieved=Count("id", filter=visits & achieved),
            cluster_meetings_planned=Count("id", filter=meetings),
            cluster_meetings_achieved=Count("id", filter=meetings & achieved),
            cluster_trainings_planned=Count("id", filter=trainings),
            cluster_trainings_achieved=Count("id", filter=trainings & achieved),
            assigned_to_partner=Count("id", filter=Q(delivery_type="partner")),
        )
    )
    return {
        row[key]: {field: int(row[field] or 0) for field in PLAN_PROGRESS_FIELDS}
        for row in rows
    }


def _merge(*parts: dict[Any, dict[str, int]]) -> dict[Any, dict[str, int]]:
    out: dict[Any, dict[str, int]] = {}
    for part in parts:
        for key, figures in part.items():
            target = out.setdefault(key, empty_progress())
            for field in PLAN_PROGRESS_FIELDS:
                target[field] += figures[field]
    return out


def plan_progress_by_district(
    fy: str | None = None,
    *,
    schools=None,
    clusters=None,
    activities=None,
) -> dict[Any, dict[str, int]]:
    """``{district_id: {field: n}}`` -- school work through its school,
    cluster sessions through their cluster. Districts with nothing planned
    are absent; read them with :func:`empty_progress`."""
    live = _live_activities(activities, fy)
    school_work = live.filter(school__isnull=False)
    if schools is not None:
        school_work = school_work.filter(school__in=schools)
    cluster_work = live.filter(cluster__isnull=False, school__isnull=True)
    if clusters is not None:
        cluster_work = cluster_work.filter(cluster__in=clusters)
    return _merge(
        _count_by(school_work, "school__district_id"),
        _count_by(cluster_work, "cluster__district_id"),
    )


def plan_progress_by_subcounty(
    fy: str | None = None,
    *,
    schools=None,
    activities=None,
) -> dict[Any, dict[str, int]]:
    """``{sub_county_id: {field: n}}``. A cluster session counts in the
    cluster's primary sub-county, the one the cluster is filed under."""
    live = _live_activities(activities, fy)
    school_work = live.filter(school__isnull=False)
    cluster_work = live.filter(cluster__isnull=False, school__isnull=True)
    if schools is not None:
        school_work = school_work.filter(school__in=schools)
        # A cluster whose member schools are in scope is in scope.
        cluster_work = cluster_work.filter(
            cluster_id__in=schools.exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .values("cluster_id")
        )
    return _merge(
        _count_by(school_work, "school__sub_county_id"),
        _count_by(cluster_work, "cluster__sub_county_id"),
    )


def plan_progress_frame(progress: dict[Any, dict[str, int]], key: str = "district_id"):
    """The progress dict as a pandas frame keyed on ``key``, for merging."""
    import pandas as pd

    if not progress:
        return pd.DataFrame(columns=[key, *PLAN_PROGRESS_FIELDS])
    return pd.DataFrame.from_records(
        [{key: k, **figures} for k, figures in progress.items()]
    )


__all__ = [
    "CLUSTER_TRAINING_TYPES",
    "LIVE_STATUSES",
    "PLAN_PROGRESS_FIELDS",
    "empty_progress",
    "plan_progress_by_district",
    "plan_progress_by_subcounty",
    "plan_progress_frame",
]
