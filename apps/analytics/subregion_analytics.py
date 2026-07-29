"""Sub-region analytics: school, cluster and SSA distribution.

Everything reaches the sub-region through ``district__sub_region``, so a
sub-county rolls up without any denormalised column: SubCounty -> District ->
SubRegion -> Region.

The aggregation runs in pandas rather than as four separate ORM aggregates
because the same frame answers every cut -- district, sub-region and region
come from grouping one frame on different keys, and the derived measures
(schools per district, share of the parent region, SSA coverage) are ratios
between columns of that frame rather than further queries.

Absent measures stay absent. A sub-region with no confirmed SSA gets
``ssa_avg = None``, never 0.0 -- a zero here would read as "scored zero" and
be indistinguishable from a real floor score.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from apps.analytics.platform_engine import engine_metadata

# SSA rows only count once a reviewer has confirmed them.
SSA_CONFIRMED = "confirmed"

# One source for the sub-region colours. The table swatch and the map fill both
# read this, so they cannot drift apart the way two hand-kept copies would.
# Identity colours, not a metric ramp -- see the card template for why.
SUBREGION_COLOURS = {
    "Acholi": "#aab4e8",
    "Central": "#b5e6a8",
    "East Central": "#f4a582",
    "Elgon": "#b8ecf5",
    "Karamoja": "#f5a3dd",
    "Lango": "#f2f2b8",
    "South Western": "#f7c5e0",
    "Teso": "#a8e6cf",
    "West Nile": "#f5a3b8",
    "Western": "#a8cbe8",
}


def _frame() -> pd.DataFrame:
    """One row per district, with its sub-region and region attached.

    Districts with no sub-region (test residue, or a new district not yet in
    the mapping) are dropped rather than bucketed into an "Unknown" group that
    would then be rendered as if it were a real place.
    """
    from apps.geography.models import District

    rows = District.objects.filter(sub_region__isnull=False).values(
        "id",
        "name",
        "sub_region__name",
        "sub_region__region__name",
    )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return pd.DataFrame(columns=["district_id", "district", "subregion", "region"])
    return frame.rename(
        columns={
            "id": "district_id",
            "name": "district",
            "sub_region__name": "subregion",
            "sub_region__region__name": "region",
        }
    )


def _counts(queryset, district_field: str, label: str) -> pd.DataFrame:
    """Count scoped queryset rows per district id.

    Counting in the database rather than pulling rows: these tables run to
    thousands of schools, and only the per-district total reaches the frame.
    """
    from django.db.models import Count

    rows = list(
        queryset.filter(**{f"{district_field}__isnull": False})
        .values(district_field)
        .annotate(n=Count("id"))
    )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return pd.DataFrame(columns=["district_id", label])
    return frame.rename(columns={district_field: "district_id", "n": label})


def _ssa_frame(fy: str | None, ssa_records=None) -> pd.DataFrame:
    """Confirmed SSA scores per district: mean and sample size."""
    from django.db.models import Avg, Count

    from apps.ssa.models import SsaRecord

    qs = (ssa_records if ssa_records is not None else SsaRecord.objects.all()).filter(
        verification_status=SSA_CONFIRMED,
        school__district__sub_region__isnull=False,
        average_score__isnull=False,
    )
    if fy:
        qs = qs.filter(fy=fy)
    rows = list(
        qs.values("school__district_id").annotate(
            ssa_avg=Avg("average_score"), ssa_n=Count("id")
        )
    )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return pd.DataFrame(columns=["district_id", "ssa_avg", "ssa_n"])
    return frame.rename(columns={"school__district_id": "district_id"})


def district_frame(
    fy: str | None = None,
    *,
    schools=None,
    clusters=None,
    ssa_records=None,
) -> pd.DataFrame:
    """District-level frame: schools, clusters and SSA, one row per district.

    This is the join everything else groups. Counts are filled to 0 because a
    district genuinely has zero schools if none reference it; ``ssa_avg`` is
    left as NaN because "no confirmed assessment" is not a score of zero.

    The optional querysets are the scope boundary. The map always keeps all
    UBOS district outlines visible, while school, cluster and SSA values are
    reduced to the current role and active analytics filters.
    """
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    base = _frame()
    if base.empty:
        return base

    schools_are_scoped = schools is not None
    school_qs = (
        schools
        if schools_are_scoped
        else School.objects.filter(deleted_at__isnull=True)
    )
    if clusters is None:
        if schools_are_scoped:
            cluster_ids = (
                school_qs.exclude(cluster_id__isnull=True)
                .exclude(cluster_id="")
                .values("cluster_id")
            )
            cluster_qs = Cluster.objects.filter(id__in=cluster_ids)
        else:
            cluster_qs = Cluster.objects.all()
    else:
        cluster_qs = clusters

    school_counts = _counts(school_qs, "district_id", "schools")
    cluster_counts = _counts(cluster_qs, "district_id", "clusters")
    ssa = _ssa_frame(fy, ssa_records)

    for part in (school_counts, cluster_counts, ssa):
        if not part.empty:
            base = base.merge(part, on="district_id", how="left")

    for col in ("schools", "clusters", "ssa_n"):
        if col not in base:
            base[col] = 0
        base[col] = base[col].fillna(0).astype(int)
    if "ssa_avg" not in base:
        base["ssa_avg"] = pd.NA
    return base


def weighted_ssa_mean(rows) -> float | None:
    """The n-weighted mean SSA score across a set of district rows.

    One definition, because there were two. `_group` below weights each
    district's mean by the assessments behind it -- a district with 3 confirmed
    assessments must not move a sub-region as much as one with 200 -- and the
    regional map template re-implemented the same arithmetic in JavaScript for
    boundaries that span several districts. Section 40 permits no authoritative
    business analytic in JavaScript, and two implementations of a weighted mean
    is one more than can be kept honest.

    Returns None, never 0, when nothing has been assessed: "no confirmed
    assessment" and "an average of zero" are different facts.
    """
    measured = [
        row
        for row in rows
        if row.get("ssa_avg") is not None and (row.get("ssa_n") or 0) > 0
    ]
    weight = sum(row["ssa_n"] for row in measured)
    if not weight:
        return None
    total = sum(float(row["ssa_avg"]) * row["ssa_n"] for row in measured)
    return round(total / weight, 2)


#: Fields that simply add when several districts are combined.
_ADDITIVE_FIELDS = (
    "schools",
    "clusters",
    "core_schools",
    "ssa_done",
    "ssa_total",
    "ssa_n",
    "trained",
    "visited",
    "teachers_trained",
    "leaders_trained",
)


def combine_district_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine several district rows into one, for a map boundary spanning them.

    The counts add; the SSA average is re-weighted rather than averaged again.
    Cohort averages (cluster, core) ship no independent sample size, so when
    more than one district is combined they are left absent rather than given
    an invented weighting -- the same decision the JavaScript made, now made
    once, on the server, where it can be tested.
    """
    combined: dict[str, Any] = {field: 0 for field in _ADDITIVE_FIELDS}
    combined["matched_keys"] = [row.get("key") for row in rows if row.get("key")]
    if not rows:
        combined.update(
            ssa_avg=None,
            ssa_avg_cluster=None,
            ssa_avg_core=None,
            best=None,
            worst=None,
            subregion="",
            school_distribution={
                "core": 0,
                "client": 0,
                "champion": 0,
                "core_trained": 0,
            },
        )
        return combined

    for row in rows:
        for field in _ADDITIVE_FIELDS:
            combined[field] += row.get(field) or 0

    # School cohorts add like the other counts, but live one level down.
    distribution = {key: 0 for key in ("core", "client", "champion", "core_trained")}
    for row in rows:
        source = row.get("school_distribution") or {}
        for key in distribution:
            distribution[key] += source.get(key) or 0
    combined["school_distribution"] = distribution

    combined["ssa_avg"] = weighted_ssa_mean(rows)
    if len(rows) == 1:
        # A single district contributes its own values unchanged, including
        # the two cohort averages and its best/worst interventions.
        only = rows[0]
        combined["ssa_avg_cluster"] = only.get("ssa_avg_cluster")
        combined["ssa_avg_core"] = only.get("ssa_avg_core")
        combined["best"] = only.get("best")
        combined["worst"] = only.get("worst")
        combined["subregion"] = only.get("subregion") or ""
    else:
        # Cohort averages ship no independent sample size, and a "best
        # intervention" across combined districts would be a claim nothing
        # measured. Absent, rather than invented.
        combined["ssa_avg_cluster"] = None
        combined["ssa_avg_core"] = None
        combined["best"] = None
        combined["worst"] = None
        combined["subregion"] = next(
            (r.get("subregion") for r in rows if r.get("subregion")), ""
        )
    return combined


def _group(frame: pd.DataFrame, key: str) -> list[dict[str, Any]]:
    """Aggregate the district frame up to `key` (subregion / region)."""
    if frame.empty:
        return []
    work = frame.copy()
    # Weight each district's mean by the assessments behind it before rolling
    # up. A plain mean of district means would let a district with 3 confirmed
    # assessments move the sub-region as much as one with 200.
    work["_weighted"] = work["ssa_avg"].astype("Float64") * work["ssa_n"]
    grouped = work.groupby(key, dropna=True).agg(
        districts=("district_id", "count"),
        schools=("schools", "sum"),
        clusters=("clusters", "sum"),
        ssa_n=("ssa_n", "sum"),
        _weighted=("_weighted", "sum"),
    )
    # Guard the divide: ssa_n is 0 for a group with no confirmed assessment,
    # and that must stay absent rather than becoming NaN-as-zero.
    grouped["ssa_avg"] = grouped["_weighted"].where(grouped["ssa_n"] > 0) / grouped[
        "ssa_n"
    ].where(grouped["ssa_n"] > 0)
    total_schools = int(grouped["schools"].sum())
    out: list[dict[str, Any]] = []
    for name, row in grouped.sort_values("schools", ascending=False).iterrows():
        avg = row["ssa_avg"]
        out.append(
            {
                "name": name,
                "districts": int(row["districts"]),
                "schools": int(row["schools"]),
                "clusters": int(row["clusters"]),
                "ssa_n": int(row["ssa_n"]),
                "ssa_avg": None if pd.isna(avg) else round(float(avg), 2),
                "school_share": (
                    round(float(row["schools"]) / total_schools * 100, 1)
                    if total_schools
                    else None
                ),
                # Only meaningful when grouping by sub-region; regions fall
                # back to a neutral swatch rather than borrowing a hue.
                "colour": SUBREGION_COLOURS.get(name, "#e2e8f0"),
            }
        )
    return out


def subregion_performance(
    fy: str | None = None,
    *,
    schools=None,
    clusters=None,
    ssa_records=None,
) -> dict[str, Any]:
    """Everything the Performance by Sub-Region card and its map need."""
    frame = district_frame(
        fy,
        schools=schools,
        clusters=clusters,
        ssa_records=ssa_records,
    )

    districts: list[dict[str, Any]] = []
    if not frame.empty:
        for _i, r in frame.iterrows():
            avg = r["ssa_avg"]
            districts.append(
                {
                    "district": r["district"],
                    "subregion": r["subregion"],
                    "region": r["region"],
                    "schools": int(r["schools"]),
                    "clusters": int(r["clusters"]),
                    "ssa_n": int(r["ssa_n"]),
                    "ssa_avg": None if pd.isna(avg) else round(float(avg), 2),
                }
            )

    subregions = _group(frame, "subregion")
    regions = _group(frame, "region")
    covered = sum(1 for d in districts if d["ssa_n"] > 0)

    return {
        "fy": fy,
        # Shipped to the map so the fills come from the same dict as the table
        # swatches instead of a second copy living in JavaScript.
        "colours": SUBREGION_COLOURS,
        "subregions": subregions,
        "regions": regions,
        "districts": districts,
        "totals": {
            "districts": len(districts),
            "subregions": len(subregions),
            "schools": sum(d["schools"] for d in districts),
            "clusters": sum(d["clusters"] for d in districts),
            "districts_with_ssa": covered,
            "ssa_coverage_pct": (
                round(covered / len(districts) * 100, 1) if districts else None
            ),
        },
        "engine": engine_metadata(
            "subregion_distribution", record_count=len(districts)
        ),
    }
