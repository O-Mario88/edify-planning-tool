"""Project baselines captured when the evidence arrives (IA review, 2026-09-13).

A Special Project enrolment is measured against what the school scored before
it joined. That score was only ever read at the moment of enrolment
(`apps.projects.services._capture_baseline`), so an enrolment made before the
school's assessment was confirmed — or by the seeder, which skipped the
service — stayed "Baseline missing" for ever, even after a confirmed SSA dated
before the enrolment existed. On the dev database all 25 enrolments read
"Baseline missing" while every one of those schools held such an SSA.

The rule here only fills gaps and never overwrites:

- an enrolment whose baseline is empty takes the latest CONFIRMED, not deleted
  reading for its intervention dated on or before the enrolment's start date
  (else the day it was created);
- a reading taken after the school joined is never a baseline — it is what
  the work is judged by;
- a baseline already captured is never recomputed (the "captured once"
  doctrine on `ProjectSchoolAssignment`).

It runs off the outbox whenever an SSA is confirmed or imported
(`enqueue_baseline_capture`), and for the whole deployment from the
idempotent `capture_project_baselines` command.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.outbox.services import enqueue, register

logger = logging.getLogger(__name__)

EVENT = "projects.baselines.capture"

#: Why an enrolment has no baseline yet — two different findings the Outcomes
#: and collection views keep apart.
CAPTURED = "captured"
NOT_CAPTURED = "baseline_not_captured"  # a qualifying confirmed SSA exists
NO_CONFIRMED_SSA = "no_confirmed_ssa"  # nothing to capture from yet
NO_INTERVENTION = "no_intervention"  # the enrolment measures nothing yet


def enqueue_baseline_capture(school_id: str, *, version: str) -> None:
    """One outbox insert, riding the caller's transaction."""
    if not school_id:
        return
    enqueue(
        EVENT,
        {"schoolId": str(school_id)},
        idempotency_key=f"{EVENT}:{school_id}:{version}",
    )


@register(
    EVENT,
    idempotency_note=(
        "capture_missing_baselines only fills empty baselines from confirmed "
        "readings dated before the enrolment, so a replay changes nothing."
    ),
)
def handle_baseline_capture(payload: dict) -> None:
    school_id = payload["schoolId"]
    filled = capture_missing_baselines(school_ids=[school_id])
    if filled:
        # A baseline that has just arrived may already have a follow-up and a
        # verified delivery waiting for it: classify now rather than on the
        # next event.
        from apps.projects.handlers import refresh_school_impact

        refresh_school_impact(school_id)


def _intervention(assignment) -> str:
    return (
        assignment.matched_intervention
        or getattr(assignment.project, "intervention", "")
        or ""
    )


def _start(assignment) -> date:
    if assignment.start_date:
        return assignment.start_date
    return timezone.localtime(assignment.created_at).date()


def _readings_by_school(school_ids, interventions) -> dict:
    """{(school_id, intervention): [(assessed_on, score, record_id), ...]}
    oldest first — confirmed, not deleted records only, in one query."""
    from apps.ssa.models import SsaScore

    rows = (
        SsaScore.objects.filter(
            ssa_record__school_id__in=list(school_ids),
            ssa_record__verification_status="confirmed",
            ssa_record__deleted_at__isnull=True,
            intervention__in=list(interventions),
        )
        .values_list(
            "ssa_record__school_id",
            "intervention",
            "ssa_record__date_of_ssa",
            "score",
            "ssa_record_id",
        )
        .order_by("ssa_record__date_of_ssa", "ssa_record_id")
    )
    readings: dict = defaultdict(list)
    for school_id, intervention, assessed_at, score, record_id in rows:
        if assessed_at is None or score is None or not 0 <= float(score) <= 10:
            continue
        readings[(school_id, intervention)].append(
            (timezone.localtime(assessed_at).date(), float(score), record_id)
        )
    return readings


def _qualifying(assignment, readings) -> tuple | None:
    before = _start(assignment)
    found = None
    for reading in readings.get((assignment.school_id, _intervention(assignment)), ()):
        if reading[0] > before:
            break
        found = reading
    return found


def _assignments(school_ids=None):
    from apps.projects.models import ProjectSchoolAssignment

    qs = ProjectSchoolAssignment.objects.filter(
        baseline_score__isnull=True, project__deleted_at__isnull=True
    ).select_related("project")
    if school_ids is not None:
        qs = qs.filter(school_id__in=list(school_ids))
    return qs


def capture_missing_baselines(*, school_ids=None, chunk: int = 500) -> int:
    """Fill every empty baseline a confirmed pre-enrolment reading supports.

    Returns how many enrolments were filled. Bulk: one read of the empty
    enrolments, one read of readings per chunk of schools, one bulk update.
    """
    from apps.core.enums import ssa_score_band
    from apps.projects.models import ProjectSchoolAssignment
    from apps.projects.ssa_impact import Impact

    pending = [a for a in _assignments(school_ids) if _intervention(a)]
    if not pending:
        return 0
    filled = 0
    now = timezone.now()
    for offset in range(0, len(pending), chunk):
        batch = pending[offset : offset + chunk]
        readings = _readings_by_school(
            {a.school_id for a in batch}, {_intervention(a) for a in batch}
        )
        changed = []
        for assignment in batch:
            reading = _qualifying(assignment, readings)
            if reading is None:
                continue
            _on, score, record_id = reading
            assignment.baseline_ssa_id = record_id
            assignment.baseline_score = score
            assignment.baseline_band = ssa_score_band(score)[0]
            assignment.baseline_captured_at = now
            if assignment.impact_classification in ("", Impact.INSUFFICIENT_EVIDENCE):
                assignment.impact_classification = Impact.NOT_YET_MEASURABLE
            assignment.updated_at = now
            changed.append(assignment)
        if not changed:
            continue
        with transaction.atomic():
            # Re-check under the write: a baseline captured concurrently (the
            # enrolment service, another worker) is never overwritten.
            still_empty = set(
                ProjectSchoolAssignment.objects.select_for_update()
                .filter(id__in=[a.id for a in changed], baseline_score__isnull=True)
                .values_list("id", flat=True)
            )
            changed = [a for a in changed if a.id in still_empty]
            ProjectSchoolAssignment.objects.bulk_update(
                changed,
                [
                    "baseline_ssa",
                    "baseline_score",
                    "baseline_band",
                    "baseline_captured_at",
                    "impact_classification",
                    "updated_at",
                ],
            )
        filled += len(changed)
    return filled


def baseline_states(assignments) -> dict:
    """{assignment id: CAPTURED | NOT_CAPTURED | NO_CONFIRMED_SSA |
    NO_INTERVENTION} for many enrolments from one query.

    "Baseline not captured" means the evidence exists and the capture has not
    run yet — an operations gap, cleared by the command or the next
    confirmation. "No confirmed SSA" means there is nothing to capture: the
    school needs an assessment, which is collection work.
    """
    assignments = list(assignments)
    open_ones = [
        a for a in assignments if a.baseline_score is None and _intervention(a)
    ]
    readings = (
        _readings_by_school(
            {a.school_id for a in open_ones}, {_intervention(a) for a in open_ones}
        )
        if open_ones
        else {}
    )
    states = {}
    for assignment in assignments:
        if assignment.baseline_score is not None:
            states[assignment.id] = CAPTURED
        elif not _intervention(assignment):
            states[assignment.id] = NO_INTERVENTION
        elif _qualifying(assignment, readings) is not None:
            states[assignment.id] = NOT_CAPTURED
        else:
            states[assignment.id] = NO_CONFIRMED_SSA
    return states


__all__ = [
    "CAPTURED",
    "NOT_CAPTURED",
    "NO_CONFIRMED_SSA",
    "NO_INTERVENTION",
    "baseline_states",
    "capture_missing_baselines",
    "enqueue_baseline_capture",
]
