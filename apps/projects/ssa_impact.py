"""Did the intervention move, and do we have the evidence to say so?

Three engines already answer nearby questions — `impact_service`'s FY deltas,
`impact_engine`'s treated/untreated comparison, and `visit_effectiveness`'s
fixed cohort. They use three different baseline rules, which is fine while they
answer three different questions and fatal the moment they answer the same one.

This module answers exactly one: for a school enrolled in a project, against
the intervention that project is meant to move, did the score change between
the assessment it started with and a later assessment inside the window the
mapping declared. Every project surface asks this and nothing else, so two
pages cannot disagree about the same school.

The honesty rules it exists to enforce:

  - A missing follow-up is missing, never zero. A project nobody has
    re-assessed has not failed.
  - A score outside 0-10 is rejected rather than clamped.
  - Where no meaningful-change threshold has been approved, any positive
    movement is Improved. Inventing a threshold would reclassify real
    movement into "no change".
  - Where the mapping's goal is maintenance, holding a Strong score is
    success, not failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from apps.core.enums import ssa_score_band

#: Only IA-confirmed assessments may measure anything.
CONFIRMED = "confirmed"

#: The full 0-10 range an SSA score may occupy.
SCORE_MIN = 0.0
SCORE_MAX = 10.0


class Impact:
    """What can be said about one school's movement on one intervention."""

    IMPROVED = "improved"
    NO_CHANGE = "no_change"
    DECLINED = "declined"
    MAINTAINED_STRONG = "maintained_strong"
    #: The activity is done but the window has not opened yet.
    NOT_YET_MEASURABLE = "not_yet_measurable"
    #: Something the measurement needs is absent — a baseline, a verified
    #: activity, or a confirmed follow-up inside the window.
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


#: Classifications that belong in an impact percentage. The others describe
#: the state of the evidence, not the state of the school, and counting them
#: as failures is how a young project looks like a bad one.
MEASURED = (
    Impact.IMPROVED,
    Impact.NO_CHANGE,
    Impact.DECLINED,
    Impact.MAINTAINED_STRONG,
)


@dataclass(frozen=True)
class ScoreReading:
    """One confirmed assessment of one intervention at one school."""

    record_id: str
    assessed_on: date
    score: float
    band: str


def _valid(score) -> bool:
    return score is not None and SCORE_MIN <= float(score) <= SCORE_MAX


def _readings(school_id: str, intervention: str):
    """Every confirmed score for this school and intervention, oldest first."""
    from apps.ssa.models import SsaScore

    rows = (
        SsaScore.objects.filter(
            ssa_record__school_id=school_id,
            ssa_record__verification_status=CONFIRMED,
            intervention=intervention,
        )
        .select_related("ssa_record")
        .order_by("ssa_record__date_of_ssa")
    )
    readings = []
    for row in rows:
        assessed_on = getattr(row.ssa_record, "date_of_ssa", None)
        if assessed_on is None or not _valid(row.score):
            # A record with no date cannot be placed before or after an
            # activity, and a score outside the scale is not evidence.
            continue
        readings.append(
            ScoreReading(
                record_id=row.ssa_record_id,
                assessed_on=(
                    assessed_on.date() if hasattr(assessed_on, "date") else assessed_on
                ),
                score=float(row.score),
                band=ssa_score_band(float(row.score))[0],
            )
        )
    return readings


def baseline_for(school_id: str, intervention: str, *, before: date | None = None):
    """The assessment a project starts from.

    The latest confirmed reading before the school entered — not the latest
    overall, which would let an assessment taken during delivery become the
    thing delivery is judged against.
    """
    readings = _readings(school_id, intervention)
    if before is not None:
        readings = [r for r in readings if r.assessed_on <= before]
    return readings[-1] if readings else None


def follow_up_for(
    school_id: str,
    intervention: str,
    *,
    after: date,
    min_days: int | None = None,
    max_days: int | None = None,
):
    """The assessment that may judge the work, or None.

    Bounded on both sides, and the bounds carry meaning. Too soon and the
    intervention has not had time to show — a training last week cannot have
    moved a school's Leadership score. Too late and other things have
    happened, so the reading is no longer about this activity.

    The FIRST qualifying reading is taken, not the latest: the earliest
    assessment inside the window is the one closest to the work.
    """
    earliest = after + timedelta(days=min_days) if min_days else after
    latest = after + timedelta(days=max_days) if max_days else None

    for reading in _readings(school_id, intervention):
        if reading.assessed_on < earliest:
            continue
        if latest is not None and reading.assessed_on > latest:
            break
        return reading
    return None


def classify(
    baseline: ScoreReading | None,
    follow_up: ScoreReading | None,
    *,
    expected_direction: str = "improve",
    min_meaningful_change=None,
    window_open: bool = True,
):
    """What the pair of readings supports saying.

    Returns (classification, change). `change` is None whenever there is
    nothing to subtract — which is the point: a project with no follow-up has
    no number, and giving it a zero would put it in the same bucket as one
    that was measured and did not move.
    """
    if baseline is None:
        return Impact.INSUFFICIENT_EVIDENCE, None
    if follow_up is None:
        # The distinction the whole module exists for.
        return (
            Impact.NOT_YET_MEASURABLE
            if not window_open
            else Impact.INSUFFICIENT_EVIDENCE
        ), None

    change = round(follow_up.score - baseline.score, 2)

    # One definition of improved and declined (apps.ssa.change_rules). The
    # window has already placed the follow-up far enough from the work, so no
    # dates are passed here: the pair is compared on its scores.
    #
    # Maintenance is a real goal. A school already scoring Strong that is
    # still Strong has done what was asked, and calling that "no change"
    # would report success as inaction. And with no approved threshold,
    # movement is movement: inventing one here would silently reclassify a
    # real half-point gain as nothing happening.
    from apps.ssa import change_rules

    threshold = (
        abs(float(min_meaningful_change)) if min_meaningful_change is not None else None
    )
    rule = {
        "threshold": threshold,
        "direction": expected_direction or "improve",
        "rule_label": (
            f"±{threshold:g}" if threshold is not None else change_rules.FALLBACK_LABEL
        ),
        "mapping_id": None,
        "version": None,
    }
    result = change_rules.change_between(baseline.score, follow_up.score, "", rule=rule)
    verdict = {
        change_rules.IMPROVED: Impact.IMPROVED,
        change_rules.DECLINED: Impact.DECLINED,
        change_rules.NO_CHANGE: Impact.NO_CHANGE,
        change_rules.MAINTAINED_STRONG: Impact.MAINTAINED_STRONG,
    }.get(result["classification"], Impact.INSUFFICIENT_EVIDENCE)
    return verdict, change


#: Below this, a rate is arithmetic rather than evidence. Six schools where
#: four improved is not a two-thirds improvement rate, it is four schools.
MIN_COHORT_FOR_A_RATE = 5


def project_impact(project, *, intervention: str | None = None) -> dict:
    """The project's measured position, with its denominator shown.

    The cohort is deliberately narrow: a school counts only when it has a
    baseline, at least one IA-verified activity, and a confirmed follow-up
    inside the window. Everything else is reported as the reason it is not
    countable rather than folded in as a zero — which is the difference
    between "we have not measured this yet" and "this did not work".
    """
    from apps.projects.models import ProjectSchoolAssignment

    rows = list(
        ProjectSchoolAssignment.objects.filter(project=project).select_related("school")
    )
    target = intervention or (project.intervention or "")

    pipeline = {
        "added": len(rows),
        "baseline_missing": 0,
        "awaiting_follow_up": 0,
        "measured": 0,
    }
    changes: list[float] = []
    baselines: list[float] = []
    follow_ups: list[float] = []
    counts = {key: 0 for key in MEASURED}

    for row in rows:
        if row.baseline_score is None:
            pipeline["baseline_missing"] += 1
            continue
        classification = row.impact_classification
        if classification not in MEASURED:
            pipeline["awaiting_follow_up"] += 1
            continue
        pipeline["measured"] += 1
        counts[classification] += 1
        baselines.append(row.baseline_score)
        if row.follow_up_score is not None:
            follow_ups.append(row.follow_up_score)
            changes.append(round(row.follow_up_score - row.baseline_score, 2))

    cohort = pipeline["measured"]
    enough = cohort >= MIN_COHORT_FOR_A_RATE

    def _rate(n):
        # A rate over a cohort too small to mean anything is withheld rather
        # than shown with a caveat nobody reads.
        return round(n / cohort, 4) if (cohort and enough) else None

    return {
        "intervention": target,
        "pipeline": pipeline,
        "cohort_size": cohort,
        "has_enough_evidence": enough,
        "minimum_cohort": MIN_COHORT_FOR_A_RATE,
        "average_baseline": round(sum(baselines) / len(baselines), 2)
        if baselines
        else None,
        "average_follow_up": round(sum(follow_ups) / len(follow_ups), 2)
        if follow_ups
        else None,
        "average_change": round(sum(changes) / len(changes), 2) if changes else None,
        "improved": counts[Impact.IMPROVED],
        "no_change": counts[Impact.NO_CHANGE],
        "declined": counts[Impact.DECLINED],
        "maintained_strong": counts[Impact.MAINTAINED_STRONG],
        "improvement_rate": _rate(
            counts[Impact.IMPROVED] + counts[Impact.MAINTAINED_STRONG]
        ),
        "decline_rate": _rate(counts[Impact.DECLINED]),
        "limitation": (
            None
            if enough
            else (
                f"{cohort} school{'' if cohort == 1 else 's'} have a baseline, "
                f"verified delivery and a confirmed follow-up. That is not "
                f"enough to state a project-level rate."
            )
        ),
    }


def refresh_follow_up(assignment, *, mapping=None, delivered_on: date | None = None):
    """Look for the assessment that can judge this enrolment, and classify it.

    Idempotent, and safe to run repeatedly: it reads confirmed assessments and
    writes what they support. A school whose window has not opened is left
    saying so rather than being given a verdict early.

    `mapping` is the rule the enrolment was stamped with (see
    `stamp_measurement_rule`); None measures under the platform fallback —
    no window, improve, no threshold — with the one documented minimum
    interval between the baseline and the follow-up
    (apps.ssa.change_rules.MIN_INTERVAL_DAYS).
    """
    from django.utils import timezone

    from apps.projects.models import ProjectSchoolAssignment
    from apps.ssa.change_rules import MIN_INTERVAL_DAYS

    intervention = assignment.matched_intervention or (
        assignment.project.intervention or ""
    )
    if not intervention or assignment.baseline_score is None:
        return assignment

    delivered_on = delivered_on or _first_verified_delivery(assignment)
    if delivered_on is None:
        # Nothing verified has happened yet, so nothing can be judged.
        return assignment

    min_days = getattr(mapping, "follow_up_min_days", None)
    expected_days = getattr(mapping, "follow_up_expected_days", None)
    max_days = getattr(mapping, "follow_up_max_days", None)
    direction = getattr(mapping, "expected_direction", "improve")
    threshold = getattr(mapping, "min_meaningful_change", None)
    if min_days is None:
        # No governed window: the follow-up must still sit the minimum
        # interval after the baseline reading, or the "change" is the same
        # assessment period read twice.
        baseline_on = _baseline_date(assignment)
        if baseline_on is not None:
            earliest = baseline_on + timedelta(days=MIN_INTERVAL_DAYS)
            gap = (earliest - delivered_on).days
            min_days = gap if gap > 0 else None

    follow_up = follow_up_for(
        assignment.school_id,
        intervention,
        after=delivered_on,
        min_days=min_days,
        max_days=max_days,
    )
    window_open = min_days is None or (
        timezone.now().date() >= delivered_on + timedelta(days=min_days)
    )
    baseline = ScoreReading(
        record_id=assignment.baseline_ssa_id or "",
        assessed_on=delivered_on,
        score=assignment.baseline_score,
        band=assignment.baseline_band,
    )
    if getattr(mapping, "measurement_role", "") == "eligibility_only":
        # The score chose the school; it was never declared the measure of
        # the work, so the enrolment is not given an outcome verdict.
        verdict = (
            Impact.NOT_YET_MEASURABLE
            if follow_up is None and not window_open
            else Impact.INSUFFICIENT_EVIDENCE
        )
    else:
        verdict, _change = classify(
            baseline,
            follow_up,
            expected_direction=direction,
            min_meaningful_change=threshold,
            window_open=window_open,
        )

    due_after = expected_days if expected_days is not None else min_days
    fields = {
        "impact_classification": verdict,
        "follow_up_due_on": (
            delivered_on + timedelta(days=due_after) if due_after else delivered_on
        ),
    }
    if follow_up is not None:
        fields["follow_up_ssa_id"] = follow_up.record_id
        fields["follow_up_score"] = follow_up.score

    ProjectSchoolAssignment.objects.filter(id=assignment.id).update(**fields)
    for key, value in fields.items():
        setattr(assignment, key, value)
    return assignment


def _baseline_date(assignment) -> date | None:
    record = (
        getattr(assignment, "baseline_ssa", None)
        if assignment.baseline_ssa_id
        else None
    )
    assessed = getattr(record, "date_of_ssa", None)
    if assessed is None:
        return None
    return assessed.date() if hasattr(assessed, "date") else assessed


def _first_verified(assignment):
    """The first verified delivery of this project at this school, as
    (delivered_on, catalogue_item_id), or None."""
    from apps.activities.models import Activity

    row = (
        Activity.objects.filter(
            school_id=assignment.school_id,
            project_id=assignment.project_id,
            status__in=("ia_verified", "accountant_confirmed", "closed"),
            deleted_at__isnull=True,
        )
        .order_by("actual_delivery_date", "scheduled_date")
        .values_list("actual_delivery_date", "scheduled_date", "catalogue_item_id")
        .first()
    )
    if not row:
        return None
    actual, scheduled, item_id = row
    chosen = actual or scheduled
    if chosen is None:
        return None
    return (chosen.date() if hasattr(chosen, "date") else chosen), item_id


def _first_verified_delivery(assignment) -> date | None:
    """When this project first verifiably reached this school.

    Verified, not scheduled: a plan is not an intervention, and measuring from
    a date nothing happened on would open the follow-up window early.
    """
    found = _first_verified(assignment)
    return found[0] if found else None


def stamp_measurement_rule(assignment, *, country: str = ""):
    """Fix the rule this enrolment is measured under, once. Returns the rule.

    Rules resolve by the catalogue item the project first delivered to the
    school — not by any mapping that happens to share the intervention — in
    the school's country first, then the deployment-wide rule
    (apps.ssa.change_rules.rule_for_activity). The rule and its version are
    written on the enrolment at its first verified delivery, and never
    rewritten: republishing a mapping changes what future enrolments are
    measured under, not what a finished one meant.

    An enrolment whose first delivery found no published rule stays unstamped
    and is measured under the fallback. A rule published later still stamps it
    — but only while it has no verdict, so no measured result is re-judged by
    a rule that arrived after it.
    """
    from apps.projects.models import ProjectSchoolAssignment
    from apps.ssa.change_rules import rule_for_activity

    if assignment.mapping_id:
        return assignment.mapping
    if assignment.impact_classification in MEASURED:
        return None
    intervention = assignment.matched_intervention or (
        assignment.project.intervention or ""
    )
    found = _first_verified(assignment)
    if not intervention or found is None:
        return None
    rule = rule_for_activity(found[1], intervention, country=country)
    if rule is None:
        return None
    ProjectSchoolAssignment.objects.filter(
        id=assignment.id, mapping__isnull=True
    ).update(mapping=rule, mapping_version=rule.version)
    assignment.mapping = rule
    assignment.mapping_version = rule.version
    return rule


def schools_in_other_projects(school_ids, *, intervention: str, exclude_project=None):
    """Which of these schools another project is also trying to move.

    §19.3: where a school sits in two projects aimed at the same intervention,
    neither may report its improvement as uniquely its own. Naming the overlap
    is the alternative to silently double-counting it in a country total.
    """
    from apps.projects.models import ProjectSchoolAssignment

    rows = ProjectSchoolAssignment.objects.filter(
        school_id__in=list(school_ids or [])
    ).select_related("project")
    if exclude_project is not None:
        rows = rows.exclude(project_id=exclude_project.id)

    overlap: dict[str, list[str]] = {}
    for row in rows:
        project = row.project
        if project.deleted_at is not None:
            continue
        targets = set(project.target_intervention_list() or [])
        if project.intervention:
            targets.add(project.intervention)
        if intervention and intervention not in targets:
            continue
        overlap.setdefault(row.school_id, []).append(project.name)
    return overlap
