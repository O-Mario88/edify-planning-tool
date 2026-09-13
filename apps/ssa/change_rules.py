"""One definition of "improved" and "declined" for SSA change (IA review, 2026-09-13).

Seven engines answered the same question with seven rules (any movement,
±0.05, ±0.3, ±0.5, unpaired averages). A school could be improved on one
page and unchanged on the next. Every surface that says a school improved or
declined asks this module.

The rule, in order:
  1. The published measurement rule for the intervention (ActivityIntervention
     Mapping, status PUBLISHED) — the school's country first, then the
     deployment-wide rule. Its expected direction and meaningful-change
     threshold decide.
  2. With no approved threshold, movement is movement (apps.projects.ssa_impact's
     honesty rule): inventing one would reclassify a real gain as nothing.
  3. Two readings closer together than MIN_INTERVAL_DAYS are not a change —
     they are the same assessment period read twice.

Owner: IA-F refines this module; the signatures are the contract.
"""

from __future__ import annotations

from datetime import date, datetime

#: Readings closer than this are one assessment period, not a before and after.
MIN_INTERVAL_DAYS = 120

IMPROVED = "improved"
DECLINED = "declined"
NO_CHANGE = "no_change"
MAINTAINED_STRONG = "maintained_strong"
NOT_COMPARABLE = "not_comparable"

MEASURED = (IMPROVED, DECLINED, NO_CHANGE, MAINTAINED_STRONG)

STRONG_SCORE = 8.0


def _published_rule(intervention: str, country: str = ""):
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )

    rows = ActivityInterventionMapping.objects.filter(
        intervention=intervention, status=MappingStatus.PUBLISHED, active=True
    ).order_by("-is_primary", "-version")
    if country:
        rule = rows.filter(country=country).first()
        if rule is not None:
            return rule
    return rows.filter(country="").first()


def threshold_for(intervention: str, *, country: str = "") -> dict:
    """The rule in force: {"threshold": float | None, "direction": str,
    "rule_label": str, "mapping_id": str | None, "version": int | None}."""

    rule = _published_rule(intervention, country)
    if rule is None:
        return {
            "threshold": None,
            "direction": "improve",
            "rule_label": "Any change (no approved threshold)",
            "mapping_id": None,
            "version": None,
        }
    threshold = (
        abs(float(rule.min_meaningful_change))
        if rule.min_meaningful_change is not None
        else None
    )
    label = (
        f"±{threshold:g} (approved rule v{rule.version})"
        if threshold is not None
        else f"Any change (rule v{rule.version}, no threshold)"
    )
    return {
        "threshold": threshold,
        "direction": rule.expected_direction or "improve",
        "rule_label": label,
        "mapping_id": rule.id,
        "version": rule.version,
    }


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def change_between(
    before: float | None,
    after: float | None,
    intervention: str,
    *,
    rule: dict | None = None,
    country: str = "",
    before_on=None,
    after_on=None,
) -> dict:
    """Classify the move from `before` to `after` on one intervention.

    Returns {"classification", "delta", "threshold", "rule_label"}. A missing
    reading or readings too close together are NOT_COMPARABLE, never zero.
    """

    rule = rule or threshold_for(intervention, country=country)
    base = {
        "delta": None,
        "threshold": rule["threshold"],
        "rule_label": rule["rule_label"],
    }
    if before is None or after is None:
        return {**base, "classification": NOT_COMPARABLE}
    start, end = _as_date(before_on), _as_date(after_on)
    if start and end and (end - start).days < MIN_INTERVAL_DAYS:
        return {**base, "classification": NOT_COMPARABLE}
    delta = round(float(after) - float(before), 2)
    base["delta"] = delta
    if rule["direction"] == "maintain_strong":
        if float(after) >= STRONG_SCORE:
            return {**base, "classification": MAINTAINED_STRONG}
        return {**base, "classification": DECLINED}
    threshold = rule["threshold"]
    if threshold is not None:
        if delta >= threshold:
            return {**base, "classification": IMPROVED}
        if delta <= -threshold:
            return {**base, "classification": DECLINED}
        return {**base, "classification": NO_CHANGE}
    if delta > 0:
        return {**base, "classification": IMPROVED}
    if delta < 0:
        return {**base, "classification": DECLINED}
    return {**base, "classification": NO_CHANGE}
