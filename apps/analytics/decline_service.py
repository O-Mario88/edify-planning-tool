"""Declining schools — the question leadership could not previously answer.

"Which schools are getting worse, and which interventions are failing?" was
unanswerable. The data existed: `impact_engine.improvement_frame` produces
per-(school, intervention) FY-over-FY deltas, and `ssa_score_band` classifies
every score. But nothing ranked decliners: the only school-identified queue
(`urgent_schools`) sorts by *absolute low score*, which surfaces schools that
have always been weak while missing a strong school in freefall — exactly the
one a decision-maker needs to catch early.

Scope follows the platform's one rule (`scoped_school_queryset`): the CD sees
named schools country-wide, the RVP sees the same analysis aggregated to
district level with identities withheld, since it is a summary-only role.
"""

from __future__ import annotations

from apps.core.enums import ssa_score_band
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, scoped_school_queryset


# A drop worth a leader's attention. Below this, normal assessment noise
# dominates and a queue full of -0.1s would train people to ignore it.
MATERIAL_DROP = 0.5

# A school whose overall average fell by at least this much is in freefall
# regardless of where it started.
SEVERE_DROP = 1.5


def declining_schools(principal, query: dict | None = None) -> dict:
    """Schools whose confirmed SSA fell year over year, worst first."""
    import pandas as pd

    from apps.analytics.impact_engine import improvement_frame

    query = query or {}
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    if schools is None:
        return _empty(fy, scope)

    school_rows = list(
        schools.values("id", "name", "school_id", "district_id", "region_id")
    )
    if not school_rows:
        return _empty(fy, scope)

    frame = improvement_frame([s["id"] for s in school_rows], fy)
    if frame.empty:
        return _empty(fy, scope, no_pairs=True)

    meta = {s["id"]: s for s in school_rows}
    district_names = _district_names({s["district_id"] for s in school_rows})

    # Per-school overall movement, plus its worst single intervention.
    overall = (
        frame.groupby("school_id")
        .agg(
            prev=("prev_score", "mean"),
            curr=("curr_score", "mean"),
            delta=("delta", "mean"),
        )
        .reset_index()
    )
    worst_idx = frame.groupby("school_id")["delta"].idxmin()
    worst = frame.loc[worst_idx].set_index("school_id")

    declining = overall[overall["delta"] <= -MATERIAL_DROP].sort_values("delta")

    rows = []
    for record in declining.to_dict("records"):
        sid = record["school_id"]
        info = meta.get(sid, {})
        worst_row = worst.loc[sid] if sid in worst.index else None
        # ssa_score_band returns (label, hex, tone) — take the label; rendering
        # the tuple puts raw Python in front of a director.
        prev_band = ssa_score_band(record["prev"])[0]
        curr_band = ssa_score_band(record["curr"])[0]
        rows.append(
            {
                "schoolId": sid,
                "name": info.get("name", "—"),
                "code": info.get("school_id"),
                "districtId": info.get("district_id"),
                "district": district_names.get(info.get("district_id"), "—"),
                "prevScore": round(float(record["prev"]), 2),
                "currScore": round(float(record["curr"]), 2),
                "delta": round(float(record["delta"]), 2),
                "prevBand": prev_band,
                "currBand": curr_band,
                # A band drop is the signal that survives being explained away
                # as measurement noise.
                "bandDropped": prev_band != curr_band,
                "severe": float(record["delta"]) <= -SEVERE_DROP,
                "worstIntervention": (
                    worst_row["intervention"] if worst_row is not None else None
                ),
                "worstDelta": (
                    round(float(worst_row["delta"]), 2)
                    if worst_row is not None
                    else None
                ),
            }
        )

    # Which interventions are failing across the whole scope — the second half
    # of the question, and the part that tells a CD what to actually change.
    by_intervention = (
        frame.groupby("intervention")
        .agg(avg_delta=("delta", "mean"), declining=("delta", lambda s: int((s < 0).sum())), n=("delta", "size"))
        .reset_index()
        .sort_values("avg_delta")
    )
    intervention_rows = [
        {
            "intervention": r["intervention"],
            "avgDelta": round(float(r["avg_delta"]), 2),
            "decliningCount": int(r["declining"]),
            "assessedCount": int(r["n"]),
            "decliningPct": (
                round(100 * float(r["declining"]) / float(r["n"]), 1) if r["n"] else 0.0
            ),
        }
        for r in by_intervention.to_dict("records")
    ]

    # District rollup — the RVP's view, and a useful lens for the CD too.
    district_rollup = _district_rollup(rows)

    show_identity = scope.can_view_school_level_detail
    return {
        "fy": fy,
        "prevFy": str(int(fy) - 1),
        "canViewSchoolDetail": show_identity,
        "schools": rows if show_identity else [],
        "districts": district_rollup,
        "interventions": intervention_rows,
        "totalDeclining": len(rows),
        "severeCount": sum(1 for r in rows if r["severe"]),
        "bandDropCount": sum(1 for r in rows if r["bandDropped"]),
        "assessedPairs": int(frame["school_id"].nunique()),
        "weakestIntervention": (
            intervention_rows[0]["intervention"] if intervention_rows else None
        ),
        "empty": False,
    }


def _district_rollup(rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for r in rows:
        key = r["districtId"] or "unassigned"
        bucket = buckets.setdefault(
            key,
            {
                "districtId": r["districtId"],
                "district": r["district"],
                "decliningCount": 0,
                "severeCount": 0,
                "bandDropCount": 0,
                "worstDelta": 0.0,
            },
        )
        bucket["decliningCount"] += 1
        bucket["severeCount"] += 1 if r["severe"] else 0
        bucket["bandDropCount"] += 1 if r["bandDropped"] else 0
        bucket["worstDelta"] = min(bucket["worstDelta"], r["delta"])
    return sorted(buckets.values(), key=lambda b: b["worstDelta"])


def _district_names(district_ids) -> dict[str, str]:
    ids = [d for d in district_ids if d]
    if not ids:
        return {}
    try:
        from apps.geography.models import District

        return {
            d["id"]: d["name"]
            for d in District.objects.filter(id__in=ids).values("id", "name")
        }
    except Exception:  # noqa: BLE001 - geography may be unavailable in some contexts
        return {}


def _empty(fy: str, scope, no_pairs: bool = False) -> dict:
    """An honest empty state — never a fabricated trend.

    `no_pairs` distinguishes "nothing declined" from "not enough consecutive
    confirmed assessments to compare", which are very different answers.
    """
    return {
        "fy": fy,
        "prevFy": str(int(fy) - 1),
        "canViewSchoolDetail": scope.can_view_school_level_detail,
        "schools": [],
        "districts": [],
        "interventions": [],
        "totalDeclining": 0,
        "severeCount": 0,
        "bandDropCount": 0,
        "assessedPairs": 0,
        "weakestIntervention": None,
        "empty": True,
        "noPairedCycles": no_pairs,
    }


__all__ = ["declining_schools", "MATERIAL_DROP", "SEVERE_DROP"]
