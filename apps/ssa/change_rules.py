"""One definition of "improved" and "declined" for SSA change (IA review, 2026-09-13).

Seven engines answered the same question with seven rules (any movement,
±0.05, ±0.3, ±0.5, unpaired averages). A school could be improved on one
page and unchanged on the next. Every surface that says a school improved or
declined asks this module.

The rule, in order:
  1. The published measurement rule for the intervention (ActivityIntervention
     Mapping, status PUBLISHED, active) — the school's country first, then the
     deployment-wide rule. Its expected direction and meaningful-change
     threshold decide. Where several activities carry a published rule for the
     same intervention, the most recently published one speaks for the
     intervention; an enrolment measured through one activity uses that
     activity's own rule instead (`rule_for_activity`).
  2. THE ONE FALLBACK. With no approved threshold, movement is movement
     (apps.projects.ssa_impact's honesty rule): inventing a number would
     reclassify a real gain as nothing. The label says so wherever the figure
     is shown — "Any change (no approved threshold)".
  3. Two readings closer together than MIN_INTERVAL_DAYS are not a change —
     they are the same assessment period read twice. They are NOT_COMPARABLE,
     never "no change", and never counted in a denominator.

A school's overall movement (the mean across its SSA domains) is judged
against the mean of the thresholds in force for those domains, a domain with
no approved threshold contributing 0 — so where every domain has the same
approved threshold the school uses exactly it, and where none has one the
fallback applies unchanged. Direction rules (maintain a Strong score) are
per-domain decisions and do not apply to an average.

Pages resolve rules through a RuleBook: one query for every published rule,
whatever the number of schools, so no engine pays a query per pair.
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

#: The label of the one fallback, shown beside every figure it produced.
FALLBACK_LABEL = "Any change (no approved threshold)"

#: A plain sentence for method notes and registry definitions.
RULE_SENTENCE = (
    "Improved and declined follow the published IA measurement rule for each "
    "SSA domain (the school's country first, then the deployment rule); where "
    "no threshold is approved any movement counts, and readings less than "
    f"{MIN_INTERVAL_DAYS} days apart are not compared."
)

_FALLBACK = {
    "threshold": None,
    "direction": "improve",
    "rule_label": FALLBACK_LABEL,
    "mapping_id": None,
    "version": None,
}


def _rule_dict(row) -> dict:
    threshold = (
        abs(float(row.min_meaningful_change))
        if row.min_meaningful_change is not None
        else None
    )
    scope = row.country or "all countries"
    label = (
        f"±{threshold:g} (approved rule v{row.version}, {scope})"
        if threshold is not None
        else f"Any change (rule v{row.version}, {scope}, no threshold)"
    )
    return {
        "threshold": threshold,
        "direction": row.expected_direction or "improve",
        "rule_label": label,
        "mapping_id": row.id,
        "version": row.version,
    }


def _published_rows(**filters):
    from apps.activity_catalogue.models import (
        ActivityInterventionMapping,
        MappingStatus,
    )

    return ActivityInterventionMapping.objects.filter(
        status=MappingStatus.PUBLISHED, active=True, **filters
    ).order_by("-effective_from", "-version", "-updated_at")


class RuleBook:
    """Every published rule, loaded once, resolved in memory."""

    def __init__(self, rows=None):
        rows = list(
            rows
            if rows is not None
            else _published_rows(intervention__isnull=False).only(
                "id",
                "intervention",
                "country",
                "version",
                "expected_direction",
                "min_meaningful_change",
                "effective_from",
                "updated_at",
            )
        )
        self._by_key: dict[tuple[str, str], dict] = {}
        # Rows arrive newest first, so the first seen for a key speaks for it.
        for row in rows:
            if not row.intervention:
                continue
            key = (row.intervention, (row.country or "").strip())
            self._by_key.setdefault(key, _rule_dict(row))

    def rule(self, intervention: str, country: str = "") -> dict:
        country = (country or "").strip()
        if country and (intervention, country) in self._by_key:
            return self._by_key[(intervention, country)]
        return self._by_key.get((intervention, ""), _FALLBACK)

    def school_rule(self, interventions, country: str = "") -> dict:
        """The rule a school's mean across `interventions` is judged by."""
        interventions = [i for i in interventions if i]
        if not interventions:
            return _FALLBACK
        rules = [self.rule(i, country) for i in interventions]
        thresholds = [r["threshold"] for r in rules]
        if all(t is None for t in thresholds):
            return _FALLBACK
        mean = round(sum(t or 0.0 for t in thresholds) / len(thresholds), 2)
        return {
            "threshold": mean,
            "direction": "improve",
            "rule_label": f"±{mean:g} (mean of the approved domain rules)",
            "mapping_id": None,
            "version": None,
        }


def threshold_for(intervention: str, *, country: str = "") -> dict:
    """The rule in force: {"threshold": float | None, "direction": str,
    "rule_label": str, "mapping_id": str | None, "version": int | None}."""

    rows = _published_rows(intervention=intervention)
    return RuleBook(rows).rule(intervention, country)


def rule_for_activity(catalogue_item_id, intervention: str, *, country: str = ""):
    """The published mapping row that governs one activity's measurement.

    Rules belong to the activity that was delivered, not to "any mapping with
    the same intervention": a Leadership training and a Leadership visit may
    be judged on different windows. A fixed row names the intervention; a
    planner-selects, inherit or prerequisite row carries no intervention and
    its rules apply to whichever intervention the planner chose. The school's
    country first, then the deployment-wide rule. Returns the row or None.
    """

    from django.db.models import Q

    if not catalogue_item_id:
        return None
    rows = list(
        _published_rows(catalogue_item_id=catalogue_item_id)
        .filter(Q(intervention=intervention) | Q(intervention__isnull=True))
        .exclude(not_ssa_measured_reason__gt="")
    )
    country = (country or "").strip()

    def _pick(pool):
        fixed = [r for r in pool if r.intervention == intervention]
        return (fixed or pool or [None])[0]

    if country:
        chosen = _pick([r for r in rows if (r.country or "") == country])
        if chosen is not None:
            return chosen
    return _pick([r for r in rows if not (r.country or "")])


def rule_from_mapping(mapping) -> dict:
    """The rule dict for a stamped or supplied mapping (None → the fallback)."""

    if mapping is None:
        return dict(_FALLBACK)
    if getattr(mapping, "id", None) is None or not hasattr(mapping, "version"):
        # A plain object carrying the rule fields (tests, previews).
        threshold = getattr(mapping, "min_meaningful_change", None)
        threshold = abs(float(threshold)) if threshold is not None else None
        return {
            "threshold": threshold,
            "direction": getattr(mapping, "expected_direction", None) or "improve",
            "rule_label": (
                f"±{threshold:g} (supplied rule)"
                if threshold is not None
                else FALLBACK_LABEL
            ),
            "mapping_id": None,
            "version": None,
        }
    return _rule_dict(mapping)


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def comparable(before_on, after_on) -> bool:
    """Whether two readings are far enough apart to be a before and after."""

    start, end = _as_date(before_on), _as_date(after_on)
    if start is None or end is None:
        return True
    return (end - start).days >= MIN_INTERVAL_DAYS


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
    if not comparable(before_on, after_on):
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


def school_change(
    mean_delta: float | None,
    interventions,
    *,
    book: RuleBook | None = None,
    country: str = "",
) -> dict:
    """Classify a school's mean movement across `interventions`.

    `mean_delta` is already the mean of comparable domain pairs; None (nothing
    comparable) is NOT_COMPARABLE. The rule is RuleBook.school_rule.
    """

    book = book or RuleBook()
    rule = book.school_rule(interventions, country)
    if mean_delta is None:
        return {
            "classification": NOT_COMPARABLE,
            "delta": None,
            "threshold": rule["threshold"],
            "rule_label": rule["rule_label"],
        }
    return change_between(0.0, float(mean_delta), "", rule=rule)


def rule_label_for(book: RuleBook, interventions=None, country: str = "") -> str:
    """One label for a page: the fallback label when no rule is approved for
    any of `interventions` (every domain by default), otherwise a note that
    approved domain rules apply."""

    from apps.core.enums import SsaIntervention

    interventions = list(interventions or SsaIntervention.values)
    rules = [book.rule(i, country) for i in interventions]
    if all(r["mapping_id"] is None for r in rules):
        return FALLBACK_LABEL
    governed = sum(1 for r in rules if r["mapping_id"] is not None)
    return (
        f"Approved IA rules for {governed} of {len(rules)} SSA domains; "
        f"any change elsewhere"
    )


def classify_pairs(rows, *, book: RuleBook, country_for=None) -> list[dict]:
    """Classify paired domain readings, in bulk.

    Each row is a dict with school_id, intervention, prev_score, curr_score
    and, where known, window_start / window_end (the two assessment dates).
    Returns the rows that are comparable, each with "classification",
    "delta" and "rule_label" added. Pairs closer than MIN_INTERVAL_DAYS are
    dropped: they are not a before and after, so they sit in no denominator.
    """

    country_for = country_for or (lambda _school_id: "")
    # A portfolio is every school's eight domains: the rule depends only on
    # (domain, country) and the interval only on the school's two dates, so
    # each is decided once rather than per row (2026-09-24 A+ audit: 160,000
    # rows on an IA dashboard at 50,000 schools). A pair whose dates are too
    # close is NOT_COMPARABLE whatever its scores, as change_between rules.
    rules: dict[tuple[str, str], dict] = {}
    spans: dict[tuple, bool] = {}
    out = []
    for row in rows:
        intervention = row.get("intervention") or ""
        country = country_for(row.get("school_id"))
        rule = rules.get((intervention, country))
        if rule is None:
            rule = rules[(intervention, country)] = book.rule(intervention, country)
        span = (row.get("window_start"), row.get("window_end"))
        try:
            far_enough = spans[span]
        except KeyError:
            far_enough = spans[span] = comparable(*span)
        except TypeError:  # an unhashable date value: decide it directly
            far_enough = comparable(*span)
        if not far_enough:
            continue
        result = change_between(
            row.get("prev_score"), row.get("curr_score"), intervention, rule=rule
        )
        if result["classification"] == NOT_COMPARABLE:
            continue
        out.append({**row, **result})
    return out


def school_verdicts(pairs, *, book: RuleBook, country_for=None) -> dict[str, dict]:
    """One verdict per school from its comparable domain pairs.

    `pairs` is the output of classify_pairs. Returns {school_id: {"mean_delta",
    "classification", "rule_label", "interventions"}}.
    """

    country_for = country_for or (lambda _school_id: "")
    grouped: dict[str, list[dict]] = {}
    for pair in pairs:
        grouped.setdefault(pair["school_id"], []).append(pair)
    verdicts = {}
    for school_id, school_pairs in grouped.items():
        deltas = [p["delta"] for p in school_pairs if p.get("delta") is not None]
        mean = round(sum(deltas) / len(deltas), 4) if deltas else None
        interventions = [p.get("intervention") for p in school_pairs]
        result = school_change(
            mean, interventions, book=book, country=country_for(school_id)
        )
        verdicts[school_id] = {
            "mean_delta": mean,
            "classification": result["classification"],
            "rule_label": result["rule_label"],
            "interventions": interventions,
        }
    return verdicts
