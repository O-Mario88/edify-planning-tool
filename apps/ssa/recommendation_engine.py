"""Analytics-backed SSA recommendation engine — the single canonical source.

Turns a school's *confirmed* SSA history plus peer context into a defensible,
deterministic per-intervention priority ranking. Support is targeted at the
interventions that are genuinely most urgent — not merely the two lowest
scores on the newest assessment (the old naive rule, which ignored trend,
peer context, and whether a weakness is chronic or a one-off dip).

Boundary (mirrors apps.analytics.platform_engine): the Django ORM does the
role-scoped filtering/aggregation; this module does the statistical
interpretation (trend regression, peer z-score, persistence) on the bounded,
per-school result set. Peers are scoped to the school's cluster, which keeps
every query bounded regardless of the 15k-school directory size.

Guarantees:
  • Verified-only. Every score fed to the engine comes from a
    ``verification_status="confirmed"`` record — an unverified upload must
    never rank, justify, or gate money-bearing work (see
    apps.ssa.services.latest_applicable_record).
  • min-N honesty. A component (trend, peer gap, persistence) that cannot be
    measured from the available data is marked ``measurable=False`` and drops
    out of the composite — its weight is redistributed across the components
    that *were* measurable. Nothing is fabricated; a school with no confirmed
    SSA yields an empty ranking, never an invented "need".
  • Deterministic. Ties break alphabetically by intervention key, so the same
    data always yields the same ranking. With only a single confirmed record
    and no measurable peers/trend the ranking reduces *exactly* to ascending
    score + alphabetical tie-break — identical to the legacy canonical helper
    it replaces, so existing single-assessment behaviour is preserved.
"""

from __future__ import annotations

from typing import Any

from apps.analytics.platform_engine import engine_metadata, trend_analysis
from apps.core.enums import SsaIntervention, ssa_score_band

# A score at or below this is treated as a "weak" intervention for the
# persistence signal — matches the < 5.5 below-count already used by the
# cluster SSA services.
WEAKNESS_THRESHOLD = 5.5

# How many of the school's most recent confirmed assessments the persistence
# signal looks back over.
PERSISTENCE_WINDOW = 4

# Minimum cluster peers with a confirmed score on an intervention before the
# peer-gap component is considered measurable (below this a z-score is noise).
MIN_PEERS = 4

# Composite weights. Severity (where the school is *now*) is the anchor;
# trend (direction of travel), peer gap (relative context) and persistence
# (chronic vs transient) refine it. Weights are renormalised over whichever
# components are measurable, so a data-poor school still gets a severity-only
# ranking rather than a diluted one.
_WEIGHTS = {
    "severity": 0.45,
    "trend": 0.25,
    "peer_gap": 0.20,
    "persistence": 0.10,
}

_LABELS = dict(SsaIntervention.choices)
_ALL_INTERVENTIONS = [choice[0] for choice in SsaIntervention.choices]


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _confidence(record_count: int) -> str:
    if record_count >= 3:
        return "high"
    if record_count == 2:
        return "moderate"
    return "low"


def _confirmed_history(school) -> list:
    """Every confirmed, non-deleted SSA record for the school, oldest first,
    with its scores prefetched. Bounded — one school has a handful of SSAs."""
    from apps.ssa.models import SsaRecord

    return list(
        SsaRecord.objects.filter(
            school=school,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        .order_by("date_of_ssa", "created_at")
        .prefetch_related("scores")
    )


def _series_by_intervention(records: list) -> dict[str, list[float]]:
    """Chronological score series per intervention across the confirmed
    records (a record missing an intervention simply contributes no point
    for it — never a fabricated zero)."""
    series: dict[str, list[float]] = {code: [] for code in _ALL_INTERVENTIONS}
    for record in records:
        for score in record.scores.all():
            if score.intervention in series and score.score is not None:
                series[score.intervention].append(float(score.score))
    return series


def _peer_stats(school) -> dict[str, dict[str, float]]:
    """Per-intervention peer mean/std from each cluster peer's *latest*
    confirmed SSA. Cluster-scoped, so bounded. Returns {} when the school is
    unclustered — peer gap is then simply not measurable, never guessed."""
    cluster_id = getattr(school, "cluster_id", None)
    if not cluster_id:
        return {}

    from apps.schools.models import School
    from apps.ssa.models import SsaRecord, SsaScore

    peer_ids = list(
        School.objects.filter(cluster_id=cluster_id, deleted_at__isnull=True)
        .exclude(id=school.id)
        .values_list("id", flat=True)
    )
    if not peer_ids:
        return {}

    # Latest confirmed record per peer school (one query + Python dedup on an
    # already cluster-bounded row set).
    latest_by_peer: dict[str, str] = {}
    for row in (
        SsaRecord.objects.filter(
            school_id__in=peer_ids,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        .order_by("school_id", "-date_of_ssa", "-created_at")
        .values("id", "school_id")
    ):
        latest_by_peer.setdefault(row["school_id"], row["id"])

    if not latest_by_peer:
        return {}

    import numpy as np

    grouped: dict[str, list[float]] = {code: [] for code in _ALL_INTERVENTIONS}
    for row in SsaScore.objects.filter(
        ssa_record_id__in=list(latest_by_peer.values())
    ).values("intervention", "score"):
        code, value = row["intervention"], row["score"]
        if code in grouped and value is not None:
            grouped[code].append(float(value))

    stats: dict[str, dict[str, float]] = {}
    for code, values in grouped.items():
        if len(values) >= MIN_PEERS:
            arr = np.asarray(values, dtype=float)
            std = float(arr.std(ddof=1))
            stats[code] = {
                "mean": float(arr.mean()),
                "std": std,
                "count": len(values),
            }
    return stats


def _prior_support_counts(school) -> dict[str, int]:
    """Per-intervention count of the school's completed/verified activities —
    pure context ("supported 3× already"), deliberately NOT a priority weight
    (we must not deprioritise an intervention just because it has resisted
    improvement). One grouped query, not one-per-intervention."""
    from django.db.models import Count

    from apps.activities.models import Activity

    rows = (
        Activity.objects.filter(
            school=school,
            deleted_at__isnull=True,
            status__in=[
                "completed",
                "ia_verified",
                "accountant_confirmed",
                "closed",
            ],
        )
        .values("focus_intervention")
        .annotate(n=Count("id"))
    )
    return {
        row["focus_intervention"]: row["n"] for row in rows if row["focus_intervention"]
    }


def _component_severity(latest_score: float) -> dict[str, Any]:
    return {
        "measurable": True,
        "urgency": _clip01((10.0 - latest_score) / 10.0),
    }


def _component_trend(series: list[float]) -> dict[str, Any]:
    if len(series) < 2:
        return {"measurable": False}
    trend = trend_analysis(series)
    slope = trend.get("slope")
    if slope is None:
        return {"measurable": False}
    # Map per-assessment slope to urgency around a neutral 0.5: a full point
    # lost per assessment (-1.0) is maximally urgent; a full point gained is
    # minimally urgent.
    urgency = _clip01(0.5 - slope / 2.0)
    return {
        "measurable": True,
        "urgency": urgency,
        "slope": slope,
        "direction": trend.get("direction"),
        "r_squared": trend.get("r_squared"),
    }


def _component_peer_gap(
    latest_score: float, stats: dict[str, float] | None
) -> dict[str, Any]:
    if not stats or stats.get("std", 0.0) <= 0.0:
        return {"measurable": False}
    z = (latest_score - stats["mean"]) / stats["std"]
    # 2 SDs below peers → maximal urgency; 2 SDs above → minimal.
    urgency = _clip01(0.5 - z / 4.0)
    return {
        "measurable": True,
        "urgency": urgency,
        "z_score": round(z, 2),
        "peer_mean": round(stats["mean"], 2),
        "peer_count": int(stats["count"]),
    }


def _component_persistence(series: list[float]) -> dict[str, Any]:
    if len(series) < 2:
        return {"measurable": False}
    window = series[-PERSISTENCE_WINDOW:]
    below = sum(1 for v in window if v <= WEAKNESS_THRESHOLD)
    return {
        "measurable": True,
        "urgency": _clip01(below / len(window)),
        "below_count": below,
        "considered": len(window),
    }


def _composite_priority(components: dict[str, dict[str, Any]]) -> float:
    """Weighted mean of the measurable components' urgencies, weights
    renormalised over whichever components were measurable (min-N honesty)."""
    num = 0.0
    denom = 0.0
    for name, weight in _WEIGHTS.items():
        comp = components.get(name, {})
        if comp.get("measurable") and comp.get("urgency") is not None:
            num += weight * float(comp["urgency"])
            denom += weight
    if denom == 0.0:
        return 0.0
    return round(num / denom * 100.0, 1)


def prioritized_interventions(school, *, n: int | None = None) -> list[dict[str, Any]]:
    """Analytically-ranked interventions for a school, most urgent first.

    Returns [] when the school has no confirmed SSA — never a fabricated
    ranking. Deterministic: sorted by descending priority then ascending
    intervention key.
    """
    records = _confirmed_history(school)
    if not records:
        return []

    series = _series_by_intervention(records)
    latest = records[-1]
    latest_scores = {
        s.intervention: float(s.score)
        for s in latest.scores.all()
        if s.score is not None
    }
    peer_stats = _peer_stats(school)
    prior_support = _prior_support_counts(school)
    confidence = _confidence(len(records))

    ranked: list[dict[str, Any]] = []
    for code in _ALL_INTERVENTIONS:
        if code not in latest_scores:
            # No confirmed current score for this intervention → not a
            # rankable weakness (never invent one).
            continue
        latest_score = latest_scores[code]
        components = {
            "severity": _component_severity(latest_score),
            "trend": _component_trend(series[code]),
            "peer_gap": _component_peer_gap(latest_score, peer_stats.get(code)),
            "persistence": _component_persistence(series[code]),
        }
        band_label, band_hex, band_tone = ssa_score_band(latest_score)
        ranked.append(
            {
                "intervention": code,
                "label": _LABELS.get(code, code),
                "score": round(latest_score, 1),
                "band": band_label,
                "band_hex": band_hex,
                "band_tone": band_tone,
                "priority": _composite_priority(components),
                "components": components,
                "prior_support_count": prior_support.get(code, 0),
                "confidence": confidence,
            }
        )

    ranked.sort(key=lambda r: (-r["priority"], r["intervention"]))
    return ranked[:n] if n is not None else ranked


def school_recommendation(school, *, n: int = 2) -> dict[str, Any]:
    """High-level, analytics-backed recommendation for one school.

    The canonical shape every recommendation surface should consume. Bands
    come from ssa_score_band (never a locally hand-rolled scheme); the weakest
    list is the top-n analytically-prioritised interventions.
    """
    records = _confirmed_history(school)
    if not records:
        return {
            "schoolId": school.school_id,
            "hasSsa": False,
            "fy": None,
            "averageScore": None,
            "severity": "none",
            "weakest": [],
            "prioritized": [],
            "engine": engine_metadata(
                "ssa_recommendation", record_count=0, confirmed_only=True
            ),
        }

    latest = records[-1]
    ranked = prioritized_interventions(school)
    band_label, _hex, _tone = ssa_score_band(latest.average_score)
    return {
        "schoolId": school.school_id,
        "hasSsa": True,
        "fy": latest.fy,
        "averageScore": latest.average_score,
        "severity": band_label,
        "weakest": [
            {"intervention": r["intervention"], "score": r["score"]} for r in ranked[:n]
        ],
        "prioritized": ranked,
        "engine": engine_metadata(
            "ssa_recommendation", record_count=len(records), confirmed_only=True
        ),
    }


__all__ = [
    "prioritized_interventions",
    "school_recommendation",
    "WEAKNESS_THRESHOLD",
]
