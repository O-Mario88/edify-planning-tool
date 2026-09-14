"""Durable outbox handlers for Special Project impact measurement.

PROJ-01. `ssa_impact.refresh_follow_up` is the only code that can move a
project school out of "not yet measurable" — it writes the follow-up score,
the follow-up assessment id, the due date the reminder needs, and the verdict
itself. It was complete, careful, idempotent and tested, and nothing called
it, so `project_impact` reported every school as awaiting a follow-up for
ever and the whole Special Project subsystem could never answer the one
question it exists to answer.

The refresh runs off the outbox rather than inline for the reason the
Business Transformation bridge beside it does: a confirmed SSA can arrive one
at a time from a verification screen or several hundred at a time from an
import, and the upload path has a query budget that a per-row projection
would break (apps.ssa test_upload_query_count_does_not_grow_per_ssa_row).
Enqueueing is one insert; the work happens on the `outbox_drain` job, which
is registered with the scheduler and covered by the INTG-02 failure alerting.
"""

from __future__ import annotations

from apps.outbox.services import register


@register(
    "projects.impact.refresh",
    idempotency_note=(
        "refresh_follow_up reads confirmed assessments and verified "
        "deliveries and writes what they support, so replaying it on the "
        "same school converges on the same classification."
    ),
)
def handle_impact_refresh(payload: dict) -> None:
    refresh_school_impact(payload["schoolId"])


def refresh_school_impact(school_id: str) -> int:
    """Re-derive every project assignment this school has. Returns how many.

    Both triggers reduce to the same statement — something new is known about
    this school — so one handler covers the assessment arriving and the
    delivery being verified. Assignments with no baseline are skipped because
    `refresh_follow_up` has nothing to measure against and says so itself;
    they are already reported as `baseline_missing`, which is a different
    finding with its own To-Do.

    Each enrolment is measured under the rule stamped on it at its first
    verified delivery (IA review, 2026-09-13): `stamp_measurement_rule` writes
    it once, from the delivered activity's catalogue item and the school's
    country, and a later republish never reaches an enrolment already stamped.
    """
    from apps.projects.models import ProjectSchoolAssignment
    from apps.projects.ssa_impact import refresh_follow_up, stamp_measurement_rule

    assignments = list(
        ProjectSchoolAssignment.objects.filter(
            school_id=school_id, baseline_score__isnull=False
        ).select_related("project", "mapping", "baseline_ssa", "school__region")
    )
    for assignment in assignments:
        region = getattr(assignment.school, "region", None)
        country = (getattr(region, "country", "") or "").strip()
        rule = stamp_measurement_rule(assignment, country=country)
        refresh_follow_up(assignment, mapping=rule)
    return len(assignments)
