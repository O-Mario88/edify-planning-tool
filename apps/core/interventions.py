"""The eight SSA interventions: one label and ONE abbreviation each.

Owner, 2026-09-12: "abbreviate the intervention names inside the KPIs —
'Exposure to the Word of God' could be 'WOG' — and do it in all the KPIs and
stats strips in the entire platform."

Three modules had grown their own abbreviation tables and disagreed
(Leadership was "L" in one and "Lship" in two; Enrolment was "ENR", "Enrol."
and "Erlm't"). This is the one table; the others import it. A KPI tile shows
the abbreviation and carries the full name in its title, so nothing is lost
to a hover or a screen reader.
"""

from __future__ import annotations

import re

from apps.core.enums import SsaIntervention

INTERVENTION_LABELS: dict[str, str] = dict(SsaIntervention.choices)

INTERVENTION_ABBREVIATIONS: dict[str, str] = {
    SsaIntervention.CHRISTLIKE_BEHAVIOUR.value: "CB",
    SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value: "WOG",
    SsaIntervention.FINANCIAL_HEALTH.value: "FH",
    SsaIntervention.LEADERSHIP.value: "LSHIP",
    SsaIntervention.GOVERNMENT_REQUIREMENT.value: "GR",
    SsaIntervention.LEARNING_ENVIRONMENT.value: "LE",
    SsaIntervention.TEACHING_ENVIRONMENT.value: "TE",
    SsaIntervention.ENROLMENT.value: "ENR",
}

#: Full label → abbreviation, longest label first so a label that contains
#: another ("Learning Environment" / "Teacher's Environment") is matched whole.
_LABEL_TO_ABBR: list[tuple[str, str]] = sorted(
    (
        (label, INTERVENTION_ABBREVIATIONS[code])
        for code, label in INTERVENTION_LABELS.items()
    ),
    key=lambda pair: -len(pair[0]),
)
_LABEL_PATTERN = re.compile(
    "|".join(re.escape(label) for label, _ in _LABEL_TO_ABBR), re.IGNORECASE
)
_ABBR_BY_LOWER = {label.lower(): abbr for label, abbr in _LABEL_TO_ABBR}


def intervention_abbr(code: str) -> str:
    """The abbreviation for a stored intervention value; the value itself
    when it is not one of the eight."""
    return INTERVENTION_ABBREVIATIONS.get(str(code or ""), str(code or ""))


def abbreviate_interventions(text) -> str:
    """Replace every full intervention name inside `text` with its
    abbreviation. Non-strings pass through untouched."""
    if not isinstance(text, str) or not text:
        return text
    return _LABEL_PATTERN.sub(lambda m: _ABBR_BY_LOWER[m.group(0).lower()], text)


def mentions_intervention(text) -> bool:
    return isinstance(text, str) and bool(_LABEL_PATTERN.search(text))
