"""Role-scoped sub-county snapshots for the regional map drill-down.

The district map is the national overview. This module supplies the next level
only: one aggregate per *assigned* ``School.sub_county``. Boundary geometry is
kept in static, district-sized GeoJSON assets and is never used to infer or
rewrite a school's geography. The School Directory remains authoritative.

The query shape is constant with respect to the number of sub-counties. Every
measure is grouped in the database and merged in memory; zooming into a
district therefore does not introduce an N+1 query path.
"""

from __future__ import annotations

import re
from typing import Any

from django.db.models import Avg, Count, Q, Sum

from apps.analytics.district_insight import (
    INTERVENTION_LABELS,
    MIN_SCORES_FOR_INTERVENTION_CALL,
    SSA_CONFIRMED,
    _active_core_school_ids,
)
from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)


def boundary_name(value: str | None) -> str:
    """Stable key shared with the browser boundary matcher.

    This intentionally performs only punctuation/case normalisation. More
    permissive historical-name matching happens against an explicit alias set
    embedded in each generated boundary asset, where ambiguity can be detected
    instead of silently guessed.
    """

    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def boundary_key(district: str | None, sub_county: str | None) -> str:
    return f"{boundary_name(district)}::{boundary_name(sub_county)}"


def subcounty_insight(
    fy: str | None = None,
    *,
    schools=None,
    ssa_records=None,
    activities=None,
) -> dict[str, Any]:
    """Return detailed, role-scoped map metrics for assigned sub-counties.

    Only sub-counties referenced by the scoped school queryset are returned.
    Zero-school official boundaries are still rendered by the client and use
    an explicit zero/absent fallback. Schools without a sub-county remain in
    ``unassigned_by_district`` so the drill-down can disclose them rather than
    losing them between the district and sub-county views.
    """

    from apps.activities.models import Activity
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord, SsaScore

    school_qs = (
        schools
        if schools is not None
        else School.objects.filter(deleted_at__isnull=True)
    )
    core_ids = _active_core_school_ids()

    identity_fields = (
        "district_id",
        "district__name",
        "district__sub_region__name",
        "sub_county_id",
        "sub_county__name",
        "sub_county__pcode",
    )
    school_rows = list(
        school_qs.filter(sub_county__isnull=False)
        .values(*identity_fields)
        .annotate(
            schools=Count("id", distinct=True),
            type_core=Count("id", filter=Q(school_type="core"), distinct=True),
            type_client=Count("id", filter=Q(school_type="client"), distinct=True),
            type_champion=Count("id", filter=Q(school_type="champion"), distinct=True),
            core_schools=Count("id", filter=Q(school_id__in=core_ids), distinct=True),
            clusters=Count(
                "cluster_id",
                filter=Q(cluster_id__isnull=False) & ~Q(cluster_id=""),
                distinct=True,
            ),
        )
    )

    entries: dict[str, dict[str, Any]] = {}
    id_to_key: dict[str, str] = {}
    for row in school_rows:
        key = boundary_key(row["district__name"], row["sub_county__name"])
        sub_county_id = str(row["sub_county_id"])
        id_to_key[sub_county_id] = key
        entries[key] = {
            "key": key,
            "district_id": str(row["district_id"]),
            "district": row["district__name"],
            "subregion": row["district__sub_region__name"] or "",
            "sub_county_id": sub_county_id,
            "subcounty": row["sub_county__name"],
            "boundary_code": row["sub_county__pcode"] or None,
            "schools": int(row["schools"]),
            "school_distribution": {
                "core": int(row["type_core"]),
                "client": int(row["type_client"]),
                "champion": int(row["type_champion"]),
                "core_trained": 0,
            },
            "clusters": int(row["clusters"]),
            "core_schools": int(row["core_schools"]),
            "ssa_done": 0,
            "ssa_total": int(row["schools"]),
            "ssa_n": 0,
            "ssa_avg": None,
            "ssa_avg_cluster": None,
            "ssa_avg_core": None,
            "best": None,
            "worst": None,
            "trained": 0,
            "visited": 0,
            "teachers_trained": 0,
            "leaders_trained": 0,
        }

    ssa_qs = (
        ssa_records if ssa_records is not None else SsaRecord.objects.all()
    ).filter(
        verification_status=SSA_CONFIRMED,
        school__sub_county__isnull=False,
        average_score__isnull=False,
    )
    if fy:
        ssa_qs = ssa_qs.filter(fy=fy)

    for row in ssa_qs.values("school__sub_county_id").annotate(
        avg=Avg("average_score"),
        n=Count("id", distinct=True),
        assessed=Count("school_id", distinct=True),
    ):
        entry = entries.get(id_to_key.get(str(row["school__sub_county_id"]), ""))
        if entry:
            entry["ssa_avg"] = round(float(row["avg"]), 2)
            entry["ssa_n"] = int(row["n"])
            entry["ssa_done"] = int(row["assessed"])

    for row in (
        ssa_qs.exclude(school__cluster_id__isnull=True)
        .exclude(school__cluster_id="")
        .values("school__sub_county_id")
        .annotate(avg=Avg("average_score"))
    ):
        entry = entries.get(id_to_key.get(str(row["school__sub_county_id"]), ""))
        if entry:
            entry["ssa_avg_cluster"] = round(float(row["avg"]), 2)

    for row in (
        ssa_qs.filter(school__school_id__in=core_ids)
        .values("school__sub_county_id")
        .annotate(avg=Avg("average_score"))
    ):
        entry = entries.get(id_to_key.get(str(row["school__sub_county_id"]), ""))
        if entry:
            entry["ssa_avg_core"] = round(float(row["avg"]), 2)

    delivered_activity_qs = (
        activities
        if activities is not None
        else Activity.objects.filter(deleted_at__isnull=True)
    ).filter(status__in=COMPLETED_STATUSES)
    if fy:
        delivered_activity_qs = delivered_activity_qs.filter(fy=fy)
    unassigned_core_trained: dict[str, int] = {}
    for row in delivered_activity_qs.values(
        "school__sub_county_id",
        "school__district__name",
    ).annotate(
        trained=Count(
            "school_id",
            filter=Q(activity_type__in=TRAINING_TYPES),
            distinct=True,
        ),
        visited=Count(
            "school_id",
            filter=Q(activity_type__in=VISIT_TYPES),
            distinct=True,
        ),
        core_trained=Count(
            "school_id",
            filter=Q(
                activity_type__in=TRAINING_TYPES,
                school__school_id__in=core_ids,
            ),
            distinct=True,
        ),
        teachers=Sum("teachers_attended"),
        leaders=Sum("leaders_attended"),
    ):
        if row["school__sub_county_id"] is None:
            unassigned_core_trained[row["school__district__name"]] = int(
                row["core_trained"] or 0
            )
            continue
        entry = entries.get(id_to_key.get(str(row["school__sub_county_id"]), ""))
        if entry:
            entry["trained"] = int(row["trained"] or 0)
            entry["visited"] = int(row["visited"] or 0)
            entry["school_distribution"]["core_trained"] = int(row["core_trained"] or 0)
            entry["teachers_trained"] = int(row["teachers"] or 0)
            entry["leaders_trained"] = int(row["leaders"] or 0)

    score_rows = list(
        SsaScore.objects.filter(ssa_record_id__in=ssa_qs.values("id"))
        .values("ssa_record__school__sub_county_id", "intervention")
        .annotate(avg=Avg("score"), n=Count("id"))
    )
    score_groups: dict[str, list[dict[str, Any]]] = {}
    for row in score_rows:
        sub_county_id = str(row["ssa_record__school__sub_county_id"])
        score_groups.setdefault(sub_county_id, []).append(row)

    for sub_county_id, rows in score_groups.items():
        if sum(int(row["n"]) for row in rows) < MIN_SCORES_FOR_INTERVENTION_CALL:
            continue
        top = max(rows, key=lambda row: float(row["avg"]))
        bottom = min(rows, key=lambda row: float(row["avg"]))
        if top["intervention"] == bottom["intervention"]:
            continue
        entry = entries.get(id_to_key.get(sub_county_id, ""))
        if not entry:
            continue
        entry["best"] = {
            "name": INTERVENTION_LABELS.get(top["intervention"], top["intervention"]),
            "score": round(float(top["avg"]), 2),
        }
        entry["worst"] = {
            "name": INTERVENTION_LABELS.get(
                bottom["intervention"], bottom["intervention"]
            ),
            "score": round(float(bottom["avg"]), 2),
        }

    unassigned_by_district = {
        row["district__name"]: {
            "schools": int(row["schools"]),
            "school_distribution": {
                "core": int(row["type_core"]),
                "client": int(row["type_client"]),
                "champion": int(row["type_champion"]),
                "core_trained": 0,
            },
        }
        for row in school_qs.filter(sub_county__isnull=True)
        .values("district__name")
        .annotate(
            schools=Count("id", distinct=True),
            type_core=Count("id", filter=Q(school_type="core"), distinct=True),
            type_client=Count("id", filter=Q(school_type="client"), distinct=True),
            type_champion=Count("id", filter=Q(school_type="champion"), distinct=True),
        )
    }
    for district_name, trained_count in unassigned_core_trained.items():
        district = unassigned_by_district.get(district_name)
        if district:
            district["school_distribution"]["core_trained"] = trained_count
    values = sorted(
        entries.values(),
        key=lambda entry: (entry["district"].upper(), entry["subcounty"].upper()),
    )
    return {
        "entries": values,
        "unassigned_by_district": unassigned_by_district,
        "totals": {
            "subcounties_with_schools": len(values),
            "assigned_schools": sum(entry["schools"] for entry in values),
            "unassigned_schools": sum(
                item["schools"] for item in unassigned_by_district.values()
            ),
        },
    }


__all__ = ["boundary_key", "boundary_name", "subcounty_insight"]
