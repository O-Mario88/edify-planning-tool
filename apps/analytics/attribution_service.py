"""Intervention contribution (association) — confirmed SSA movement by
intervention beside the focused work delivered (2026-09-03; merged into
Programme Learning by the IA review, 2026-09-13).

The first version was a second engine answering /impact's question with
weaker maths: its own stale lists of training and visit types (one of them
not an activity type at all), a clause that counted every school-less
activity in the deployment, delivery counted across the whole financial year
rather than between each school's two assessments, the primary focus only,
no minimum sample, "improved" as any upward movement, and a page titled
"Impact Attribution" with no word on causation.

It now reads the impact engine's own frames, so the two cannot disagree:

  - pairs: impact_engine.improvement_frame (confirmed SSAs, FY-1 against FY);
  - delivery: impact_engine.activity_frame (IA-verified work inside each
    school's exposure window, attributed through the school, the attendance
    list or the enrolment — never an unplaced activity), with the canonical
    TRAINING_TYPES and VISIT_TYPES and every focus the activity carried;
  - improved/declined: apps.ssa.change_rules, the one IA definition;
  - strength: apps.analytics.evidence_strength.grade, with the median change
    where no focused work reached the school shown beside it, so movement
    without delivery is visible as background drift.

/ia/attribution/ redirects to Programme Learning (Training tab), which renders
`intervention_contribution` under the association caveat.
"""

from __future__ import annotations

from statistics import median

from apps.analytics.evidence_strength import MIN_N, PRE_POST, grade
from apps.core.enums import SsaIntervention

CAVEAT = (
    "Association, not attribution: schools were not randomly chosen for "
    "focused work, and the SSA is the school's own assessment."
)


def _median(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return round(median(values), 2) if values else None


def intervention_contribution(
    imp, acts, *, countries: dict, schools_in_scope: int, confirmed_share=None
) -> list[dict]:
    """One row per SSA intervention over precomputed engine frames.

    `imp` and `acts` are impact_engine.improvement_frame / activity_frame for
    the reader's schools; `countries` maps school id → country (for the change
    rule). Pure computation over the frames plus one query for the rule book.
    """
    from apps.ssa import change_rules

    book = change_rules.RuleBook()
    pairs = (
        change_rules.classify_pairs(
            imp.to_dict("records"),
            book=book,
            country_for=lambda school_id: countries.get(school_id) or "",
        )
        if not imp.empty
        else []
    )
    focused: dict[tuple[str, str], dict[str, set]] = {}
    if not acts.empty:
        for row in acts[acts["kind"].isin(("training", "visit"))].to_dict("records"):
            for intervention in row["focus"] or ():
                bucket = focused.setdefault(
                    (row["kind"], intervention), {"activities": set(), "schools": set()}
                )
                bucket["activities"].add(row["activity_id"])
                bucket["schools"].add(row["school_id"])

    rows = []
    for value, label in SsaIntervention.choices:
        own = [p for p in pairs if p["intervention"] == value]
        trainings = focused.get(
            ("training", value), {"activities": set(), "schools": set()}
        )
        visits = focused.get(("visit", value), {"activities": set(), "schools": set()})
        reached = trainings["schools"] | visits["schools"]
        measured = len({p["school_id"] for p in own})
        movement = [
            p["delta"]
            for p in own
            if p["classification"] != change_rules.MAINTAINED_STRONG
        ]
        improved = sum(1 for p in own if p["classification"] == change_rules.IMPROVED)
        declined = sum(1 for p in own if p["classification"] == change_rules.DECLINED)
        enough = measured >= MIN_N
        without = [
            p["delta"]
            for p in own
            if p["school_id"] not in reached
            and p["classification"] != change_rules.MAINTAINED_STRONG
        ]
        rows.append(
            {
                "key": value,
                "intervention": value,
                "label": str(label),
                "schools_measured": measured,
                "median_prior": _median(p["prev_score"] for p in own)
                if enough
                else None,
                "median_latest": _median(p["curr_score"] for p in own)
                if enough
                else None,
                "median_change": _median(movement) if enough else None,
                "median_change_without_focus": (
                    _median(without) if len(without) >= MIN_N else None
                ),
                "improved_pct": round(improved / measured * 100) if enough else None,
                "declined_pct": round(declined / measured * 100) if enough else None,
                "withheld": 0 < measured < MIN_N,
                "trainings": len(trainings["activities"]),
                "visits": len(visits["activities"]),
                "schools_reached": len(reached),
                "rule_label": own[0]["rule_label"] if own else "",
                "grade": grade(
                    measured,
                    confirmed_share=confirmed_share,
                    missing_share=(
                        1 - measured / schools_in_scope if schools_in_scope else None
                    ),
                    design=PRE_POST,
                ),
            }
        )
    rows.sort(
        key=lambda r: (
            r["median_change"] is None,
            -(r["median_change"] or 0),
            r["label"],
        )
    )
    return rows


def attribution(
    principal, fy: str | None = None, district_id: str | None = None
) -> dict:
    """The contribution table for one reader, FY-1 against `fy`, optionally
    one district of the reader's own schools."""
    from apps.analytics.impact_engine import activity_frame, improvement_frame
    from apps.core.fy import get_operational_fy
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.ssa.models import SsaRecord

    fy = fy or get_operational_fy()
    prior_fy = str(int(fy) - 1)
    scope = resolve_user_scope(principal)
    schools = scoped_school_queryset(scope)
    if schools is None or scope.can_view_summary_only:
        schools = None
    elif district_id:
        schools = schools.filter(district_id=district_id)
    countries = (
        dict(schools.values_list("id", "region__country"))
        if schools is not None
        else {}
    )
    school_ids = list(countries)
    imp = improvement_frame(school_ids, fy)
    acts = activity_frame(imp, school_ids)
    records = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True
    )
    total = records.count() if school_ids else 0
    confirmed = records.filter(verification_status="confirmed").count() if total else 0
    return {
        "fy": fy,
        "prior_fy": prior_fy,
        "schools_in_scope": len(school_ids),
        "schools_with_both_years": int(imp["school_id"].nunique())
        if not imp.empty
        else 0,
        "total_records": total,
        "confirmed_records": confirmed,
        "confirmed_share": round(confirmed / total * 100) if total else None,
        "rows": intervention_contribution(
            imp,
            acts,
            countries=countries,
            schools_in_scope=len(school_ids),
            # Pairs are built from confirmed readings only; unconfirmed ones
            # are missing, and count in the missing share instead.
            confirmed_share=1.0,
        ),
        "caveat": CAVEAT,
    }
