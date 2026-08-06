"""Small, shared presentation helpers for real SSA intervention scores."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from apps.core.enums import SsaIntervention, ssa_score_band


SSA_SCORE_GROUPS = (
    (
        "urgent",
        "SSA interventions needing urgent attention",
        "danger",
    ),
    (
        "performing-well",
        "SSA interventions performing well",
        "success",
    ),
    (
        "warning",
        "SSA interventions to watch",
        "warning",
    ),
)

_INTERVENTION_LABELS = dict(SsaIntervention.choices)
_INTERVENTION_ORDER = {
    intervention: position
    for position, intervention in enumerate(SsaIntervention.values)
}


def build_ssa_score_summary(scores: Iterable[Mapping[str, object]]) -> dict:
    """Return the real 0–10 intervention scores grouped for a school record.

    The source is always the caller's selected, confirmed SSA record.  Scores
    are kept in the canonical intervention order rather than ranking or
    duplicating values, so the expanded list remains both accurate and easy to
    compare with the original SSA assessment.
    """

    groups = {
        key: {"key": key, "title": title, "tone": tone, "items": []}
        for key, title, tone in SSA_SCORE_GROUPS
    }
    normalized_scores: list[dict] = []

    for raw_score in scores:
        intervention = str(raw_score.get("intervention") or "")
        score = raw_score.get("score")
        if score is None:
            continue

        try:
            numeric_score = float(score)
        except (TypeError, ValueError):
            continue

        if numeric_score < 5:
            group_key = "urgent"
        elif numeric_score >= 7:
            group_key = "performing-well"
        else:
            group_key = "warning"

        band_label, _band_colour, band_tone = ssa_score_band(numeric_score)
        normalized_scores.append(
            {
                "code": intervention,
                "label": _INTERVENTION_LABELS.get(intervention, intervention),
                "score": numeric_score,
                "band": band_label,
                "band_tone": band_tone,
                "group": group_key,
            }
        )

    normalized_scores.sort(
        key=lambda item: (_INTERVENTION_ORDER.get(item["code"], 999), item["label"])
    )
    for score in normalized_scores:
        groups[score["group"]]["items"].append(score)

    average_score = (
        round(
            sum(item["score"] for item in normalized_scores) / len(normalized_scores), 1
        )
        if normalized_scores
        else None
    )
    _average_label, _average_colour, average_tone = ssa_score_band(average_score)

    return {
        "has_scores": bool(normalized_scores),
        "score_count": len(normalized_scores),
        "average_score": average_score,
        "average_tone": average_tone,
        "groups": [groups[key] for key, _title, _tone in SSA_SCORE_GROUPS],
    }
