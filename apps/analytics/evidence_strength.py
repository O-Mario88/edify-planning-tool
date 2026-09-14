"""How much a figure can bear (IA review, 2026-09-13).

Minimum sample sizes differed page to page (5, 8, 10 or none) and no surface
said whether a result came from a before-and-after reading or a comparison
with similar schools. Every IA finding carries one grade from here. The
platform has no randomised design, so "causal" is never a grade.

The grades, weakest first:

  insufficient   fewer than MIN_N measured schools. The figure is shown as
                 "n too small" and never read as a result.
  descriptive    before-and-after readings only, or a comparison weakened by
                 a thin comparison group, heavy missingness, unconfirmed
                 readings or a known design flag (FLAG_TEXT). It describes
                 what happened in the measured schools.
  associational  a stratified comparison with at least MIN_COMPARISON_N
                 schools on each side, most of the population measured and
                 the readings independently confirmed. It says the change is
                 associated with the exposure — still not that the programme
                 caused it.

Callers: the Programme Learning workspace (apps.analytics.programme_effectiveness),
the Outcomes view domains (apps.analytics.ia_workflow), school evidence
summaries (apps.impact.evidence_services) and the /impact per-intervention
comparisons (apps.analytics.impact_engine).

Owner: IA-L. The signature of `grade` is the contract; the dict it returns
keeps "grade", "label", "reasons" and "min_n", and adds "design_label".
"""

from __future__ import annotations

#: Below this many measured units a figure is description, not evidence.
MIN_N = 8
#: A comparison needs at least this many units on each side.
MIN_COMPARISON_N = 8
#: More than this share of the population unmeasured weakens any finding.
MAX_MISSING_SHARE = 0.5
#: Below this share of confirmed (independently verified) readings, same.
MIN_CONFIRMED_SHARE = 0.8

INSUFFICIENT = "insufficient"
DESCRIPTIVE = "descriptive"
ASSOCIATIONAL = "associational"

GRADES = (INSUFFICIENT, DESCRIPTIVE, ASSOCIATIONAL)

LABELS = {
    INSUFFICIENT: "Insufficient evidence",
    DESCRIPTIVE: "Descriptive (before and after only)",
    ASSOCIATIONAL: "Association (compared with similar schools)",
}

#: The tone a grade is drawn with (plain text with data-tone, never a pill).
TONES = {
    INSUFFICIENT: "neutral",
    DESCRIPTIVE: "warning",
    ASSOCIATIONAL: "info",
}

PRE_POST = "pre_post"
STRATIFIED_COMPARISON = "stratified_comparison"

DESIGN_LABELS = {
    PRE_POST: "Before and after (no comparison group)",
    STRATIFIED_COMPARISON: "Compared with similar schools not exposed",
}

#: Known design weaknesses a caller may flag. Any flag caps the grade at
#: descriptive: each one is a reason a reader could explain the difference
#: without the programme. Unknown flags are shown as given and cap it too.
OVERLAP = "overlap"
NON_COMPARABLE_CYCLE = "non_comparable_cycle"
IMMATURE_COHORT = "immature_cohort"
SELF_REPORTED = "self_reported"
PROXY_MEASURE = "proxy_measure"

FLAG_TEXT = {
    OVERLAP: "Schools in the exposed group also received other programmes.",
    NON_COMPARABLE_CYCLE: (
        "The two assessment cycles used different instruments or timing; "
        "change may reflect the instrument."
    ),
    IMMATURE_COHORT: (
        "Some exposures are too recent for their follow-up window; change "
        "may not have had time to show."
    ),
    SELF_REPORTED: "The outcome is the school's own self-assessment.",
    PROXY_MEASURE: "The outcome is a school-level proxy for what the programme targets.",
}


def grade_tone(value: str) -> str:
    return TONES.get(value, "neutral")


def grade(
    n: int,
    *,
    n_comparison: int | None = None,
    confirmed_share: float | None = None,
    missing_share: float | None = None,
    design: str = "pre_post",
    flags=(),
) -> dict:
    """The strongest grade the evidence supports, with every reason it is
    not stronger. `n` counts measured schools in the exposed (or only) group;
    `n_comparison` the comparison group for a stratified comparison."""

    reasons: list[str] = []
    design = design if design in DESIGN_LABELS else PRE_POST
    base = {"min_n": MIN_N, "design_label": DESIGN_LABELS[design]}
    if not n or n < MIN_N:
        reasons.append(f"Fewer than {MIN_N} measured schools ({n or 0}).")
        return {
            "grade": INSUFFICIENT,
            "label": LABELS[INSUFFICIENT],
            "reasons": reasons,
            **base,
        }
    level = DESCRIPTIVE
    if design == STRATIFIED_COMPARISON:
        if n_comparison is not None and n_comparison >= MIN_COMPARISON_N:
            level = ASSOCIATIONAL
        else:
            reasons.append(
                f"Comparison group below {MIN_COMPARISON_N} schools ({n_comparison or 0})."
            )
    else:
        reasons.append("Before and after readings only; no comparison group.")
    if missing_share is not None and missing_share > MAX_MISSING_SHARE:
        reasons.append(f"{round(missing_share * 100)}% of schools are unmeasured.")
        level = DESCRIPTIVE
    if confirmed_share is not None and confirmed_share < MIN_CONFIRMED_SHARE:
        reasons.append(
            f"Only {round(confirmed_share * 100)}% of readings are independently confirmed."
        )
        level = DESCRIPTIVE
    for flag in flags or ():
        reasons.append(FLAG_TEXT.get(str(flag), str(flag)))
        level = DESCRIPTIVE
    reasons.append("Association is not proof that the programme caused the change.")
    return {"grade": level, "label": LABELS[level], "reasons": reasons, **base}
