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
from apps.ssa import change_rules


# Kept for importers only (IA review, 2026-09-13). A school no longer declines
# at a page-local -0.5: both columns of this page ask apps.ssa.change_rules,
# the one definition every SSA surface shares, and the payload carries the
# rule's label ("ruleLabel") for the page to show.
MATERIAL_DROP = 0.5

# A school whose overall average fell by at least this much is in freefall
# regardless of where it started.
SEVERE_DROP = 1.5


def declining_schools(principal, query: dict | None = None) -> dict:
    """Schools whose confirmed SSA fell year over year, worst first."""

    from apps.analytics.impact_engine import improvement_frame

    query = query or {}
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    if schools is None:
        return _empty(fy, scope)

    school_rows = list(
        schools.values(
            "id", "name", "school_id", "district_id", "region_id", "region__country"
        )
    )
    if not school_rows:
        return _empty(fy, scope)

    frame = improvement_frame([s["id"] for s in school_rows], fy)
    if frame.empty:
        return _empty(fy, scope, no_pairs=True)

    meta = {s["id"]: s for s in school_rows}
    district_names = _district_names({s["district_id"] for s in school_rows})

    # One definition of declined (apps.ssa.change_rules): each domain pair is
    # judged by its published rule in the school's country, pairs taken too
    # close together are not compared, and a school declines when its mean
    # movement across comparable domains classifies as declined.
    book = change_rules.RuleBook()

    def country_for(school_id):
        return (meta.get(school_id) or {}).get("region__country") or ""

    pairs = change_rules.classify_pairs(
        frame.to_dict("records"), book=book, country_for=country_for
    )
    if not pairs:
        return _empty(fy, scope, no_pairs=True)
    verdicts = change_rules.school_verdicts(pairs, book=book, country_for=country_for)
    by_school: dict[str, list[dict]] = {}
    for pair in pairs:
        by_school.setdefault(pair["school_id"], []).append(pair)

    declining = sorted(
        (
            (sid, verdict)
            for sid, verdict in verdicts.items()
            if verdict["classification"] == change_rules.DECLINED
        ),
        key=lambda item: item[1]["mean_delta"],
    )

    rows = []
    for sid, verdict in declining:
        info = meta.get(sid, {})
        school_pairs = by_school.get(sid, [])
        prev = sum(p["prev_score"] for p in school_pairs) / len(school_pairs)
        curr = sum(p["curr_score"] for p in school_pairs) / len(school_pairs)
        worst_row = min(school_pairs, key=lambda p: p["delta"])
        # ssa_score_band returns (label, hex, tone) — take the label; rendering
        # the tuple puts raw Python in front of a director.
        prev_band = ssa_score_band(prev)[0]
        curr_band = ssa_score_band(curr)[0]
        delta = float(verdict["mean_delta"])
        rows.append(
            {
                "schoolId": sid,
                "name": info.get("name", "—"),
                "code": info.get("school_id"),
                "districtId": info.get("district_id"),
                "district": district_names.get(info.get("district_id"), "—"),
                "prevScore": round(float(prev), 2),
                "currScore": round(float(curr), 2),
                "delta": round(delta, 2),
                "prevBand": prev_band,
                "currBand": curr_band,
                # A band drop is the signal that survives being explained away
                # as measurement noise.
                "bandDropped": prev_band != curr_band,
                "severe": delta <= -SEVERE_DROP,
                "worstIntervention": worst_row["intervention"],
                "worstDelta": round(float(worst_row["delta"]), 2),
                "ruleLabel": verdict["rule_label"],
            }
        )

    # Which interventions are failing across the whole scope — the second half
    # of the question, and the part that tells a CD what to actually change.
    # The same rule as the school list: a pair counts as declining when it
    # classifies as declined, not whenever its delta is below zero.
    by_intervention: dict[str, list[dict]] = {}
    for pair in pairs:
        by_intervention.setdefault(pair["intervention"], []).append(pair)
    intervention_rows = []
    for intervention, group in by_intervention.items():
        declined = sum(1 for p in group if p["classification"] == change_rules.DECLINED)
        n = len(group)
        intervention_rows.append(
            {
                "intervention": intervention,
                "avgDelta": round(sum(p["delta"] for p in group) / n, 2),
                "decliningCount": declined,
                "assessedCount": n,
                "decliningPct": round(100 * declined / n, 1) if n else 0.0,
                "ruleLabel": book.rule(intervention)["rule_label"],
            }
        )
    intervention_rows.sort(key=lambda r: r["avgDelta"])

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
        "assessedPairs": len(verdicts),
        "ruleLabel": change_rules.rule_label_for(book),
        "ruleSentence": change_rules.RULE_SENTENCE,
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
        "ruleLabel": change_rules.FALLBACK_LABEL,
        "ruleSentence": change_rules.RULE_SENTENCE,
    }


__all__ = ["declining_schools", "MATERIAL_DROP", "SEVERE_DROP"]
