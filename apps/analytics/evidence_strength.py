"""How much a figure can bear (IA review, 2026-09-13).

Minimum sample sizes differed page to page (5, 8, 10 or none) and no surface
said whether a result came from a before-and-after reading or a comparison
with similar schools. Every IA finding carries one grade from here. The
platform has no randomised design, so "causal" is never a grade.

Owner: IA-L refines this module; the signature is the contract.
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

LABELS = {
    INSUFFICIENT: "Insufficient evidence",
    DESCRIPTIVE: "Descriptive (before and after only)",
    ASSOCIATIONAL: "Association (compared with similar schools)",
}


def grade(
    n: int,
    *,
    n_comparison: int | None = None,
    confirmed_share: float | None = None,
    missing_share: float | None = None,
    design: str = "pre_post",
    flags=(),
) -> dict:
    reasons: list[str] = []
    if not n or n < MIN_N:
        reasons.append(f"Fewer than {MIN_N} measured schools ({n or 0}).")
        return {
            "grade": INSUFFICIENT,
            "label": LABELS[INSUFFICIENT],
            "reasons": reasons,
            "min_n": MIN_N,
        }
    level = DESCRIPTIVE
    if design == "stratified_comparison":
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
        reasons.append(str(flag))
    reasons.append("Association is not proof that the programme caused the change.")
    return {"grade": level, "label": LABELS[level], "reasons": reasons, "min_n": MIN_N}
