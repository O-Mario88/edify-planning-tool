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
from django.db.models import Q

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
        return pd.DataFrame(
            columns=["district_id", "district", "subregion", "region"]
        )
    return frame.rename(
        columns={
            "id": "district_id",
            "name": "district",
            "sub_region__name": "subregion",
            "sub_region__region__name": "region",
        }
    )


def _counts(model, district_field: str, label: str) -> pd.DataFrame:
    """Count `model` rows per district id.

    Counting in the database rather than pulling rows: these tables run to
    thousands of schools, and only the per-district total reaches the frame.
    """
    from django.db.models import Count

    rows = list(
        model.objects.filter(**{f"{district_field}__isnull": False})
        .values(district_field)
        .annotate(n=Count("id"))
    )
    frame = pd.DataFrame.from_records(rows)
    if frame.empty:
        return pd.DataFrame(columns=["district_id", label])
    return frame.rename(columns={district_field: "district_id", "n": label})


def _ssa_frame(fy: str | None) -> pd.DataFrame:
    """Confirmed SSA scores per district: mean and sample size."""
    from django.db.models import Avg, Count

    from apps.ssa.models import SsaRecord

    qs = SsaRecord.objects.filter(
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


def district_frame(fy: str | None = None) -> pd.DataFrame:
    """District-level frame: schools, clusters and SSA, one row per district.

    This is the join everything else groups. Counts are filled to 0 because a
    district genuinely has zero schools if none reference it; ``ssa_avg`` is
    left as NaN because "no confirmed assessment" is not a score of zero.
    """
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    base = _frame()
    if base.empty:
        return base

    schools = _counts(School, "district_id", "schools")
    clusters = _counts(Cluster, "district_id", "clusters")
    ssa = _ssa_frame(fy)

    for part in (schools, clusters, ssa):
        if not part.empty:
            base = base.merge(part, on="district_id", how="left")

    for col in ("schools", "clusters", "ssa_n"):
        if col not in base:
            base[col] = 0
        base[col] = base[col].fillna(0).astype(int)
    if "ssa_avg" not in base:
        base["ssa_avg"] = pd.NA
    return base


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


def subregion_performance(fy: str | None = None) -> dict[str, Any]:
    """Everything the Performance by Sub-Region card and its map need."""
    frame = district_frame(fy)

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
