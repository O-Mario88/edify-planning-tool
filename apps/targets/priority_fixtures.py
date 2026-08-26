"""Agreed-performance-priority fixtures for tests.

Not collected as a test module (the runner's pattern is ``test*.py``) and not
imported by production code — it exists so the several suites that need a
measurable person build one the same way.

Why it appeared: CONFLICT-001 was decided in favour of the honest denominator,
so every leadership surface now weights against the priorities a person has
**agreed** rather than the global TargetArea catalogue. Fixtures that set an
annual ``StaffTargetProfile`` and no agreement therefore measure nothing —
correctly, because that is exactly the "no signed agreements" case the decision
was about.

Several suites were built that way, and their subjects are not agreements at
all: they test proration arithmetic, weighting, ledger staleness, drill-down
completeness. Rewriting their assertions down to zero would keep them green
while quietly deleting what they check. Giving them the agreement their annual
targets already imply keeps every one of those invariants testing the real
path.
"""

from __future__ import annotations

from django.utils import timezone

#: Performance metric key -> the TargetArea key it projects onto. Mirrors
#: apps.targets.my_targets.PERFORMANCE_METRIC_TO_AREA, from the other side.
AREA_TO_METRIC = {
    "school_visits": "direct_visits",
    "cluster_meetings": "cluster_meetings",
    "cluster_trainings": "trainings",
    "ssa_completed": "ssa_coverage",
    "mscs": "mscs",
}

#: The official weights, so a fixture's weighting matches the catalogue's
#: unless a test deliberately says otherwise.
DEFAULT_WEIGHTS = {
    "school_visits": 30,
    "cluster_meetings": 15,
    "cluster_trainings": 20,
    "ssa_completed": 25,
    "mscs": 10,
}


def agree_priorities(staff, fy: str, **area_targets: int):
    """Give ``staff`` an agreed annual-priorities review for ``fy``.

    Call with TargetArea keys and annual numbers::

        agree_priorities(cceo_sp, "FY26", school_visits=13, ssa_completed=3)

    Areas passed as zero are recorded with a zero target, which the resolver
    then skips — the same as not agreeing them at all, but explicit in the
    fixture so a reader can see the intent.
    """
    from apps.hr.models import (
        PerformancePriority,
        PerformanceReview,
        ReviewStage,
        ReviewType,
    )

    unknown = set(area_targets) - set(AREA_TO_METRIC)
    if unknown:
        raise ValueError(f"not TargetArea keys: {sorted(unknown)}")

    review = PerformanceReview.objects.create(
        staff=staff,
        fy=fy,
        period=fy,
        due_date=timezone.localdate(),
        review_type=ReviewType.ANNUAL_PRIORITIES,
        stage=ReviewStage.PRIORITIES_AGREED,
    )
    for sequence, (area_key, target) in enumerate(area_targets.items(), start=1):
        PerformancePriority.objects.create(
            review=review,
            metric_key=AREA_TO_METRIC[area_key],
            outcome_statement=f"Agreed {area_key.replace('_', ' ')}",
            target_number=target,
            weight=DEFAULT_WEIGHTS[area_key],
            sequence=sequence,
        )
    return review
