"""Turning what the engine computes into something someone is answerable for.

`recommendation_engine` stays exactly as it is — it decides what a school
needs, and it does that well. This module is the record-keeping half: it
persists those findings as `SsaRecommendation` rows, moves them through a
lifecycle, and refuses to raise the same need twice while somebody is already
dealing with it.

Two rules govern everything here:

  Generation converges, it does not accumulate. Running it twice for the same
  school produces the same rows, because a need is identified by
  `condition_key` and only one live recommendation per need may exist.

  A decision not to act needs a reason. Deferring or rejecting a measured
  weakness is exactly the decision that has to be explainable later, so the
  service demands one and the database enforces it.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest
from apps.ssa.recommendation_models import (
    LIVE_STATES,
    RecommendationState,
    SsaRecommendation,
    condition_key_for,
)

#: How long a recommendation stays current before it should be re-derived from
#: a fresher assessment. An SSA cycle is annual; half a year is the point at
#: which acting on the old picture stops being obviously right.
DEFAULT_VALIDITY_DAYS = 182

ENGINE_VERSION = "recommendation_engine/2026-08"


def _audit(action: str, recommendation, principal, payload=None) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="ssa_recommendation",
            subject_id=recommendation.id,
            actor_id=getattr(principal, "id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "school": recommendation.school_id,
                "intervention": recommendation.intervention,
                "state": recommendation.state,
                **(payload or {}),
            },
        )
    except Exception:  # noqa: BLE001 — the audit never blocks the decision
        pass


def generate_for_school(school, *, fy: str, limit: int = 3, principal=None) -> dict:
    """Persist the engine's findings for one school. Idempotent.

    Returns a count of what changed rather than the rows, so a caller
    generating across a portfolio can report progress without holding
    everything in memory.
    """
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.ssa.recommendation_engine import prioritized_interventions
    from apps.ssa.services import latest_applicable_record

    record = latest_applicable_record(school)
    if record is None:
        # No confirmed assessment: there is nothing to recommend FROM. This is
        # not a failure — it is the state the SSA-collection visit exists to
        # resolve, and it must not be reported as "no needs".
        return {"created": 0, "refreshed": 0, "skipped": "no confirmed ssa"}

    findings = prioritized_interventions(school, n=limit) or []
    created = refreshed = 0

    for rank, finding in enumerate(findings, start=1):
        intervention = finding.get("intervention")
        if not intervention:
            continue
        key = condition_key_for(
            school_id=str(school.id), fy=fy, intervention=intervention
        )
        live = SsaRecommendation.objects.filter(
            condition_key=key, state__in=LIVE_STATES
        ).first()
        if live is not None:
            # The need is already someone's. Refresh the evidence so the queue
            # shows the current score, but never reset the decision.
            live.score = finding.get("score")
            live.score_band = finding.get("band") or finding.get("classification") or ""
            live.rank = rank
            live.reason = explain(finding)
            live.save(
                update_fields=["score", "score_band", "rank", "reason", "updated_at"]
            )
            refreshed += 1
            continue

        # Prefer something deliverable AT the school; fall back to a cluster
        # response so a real answer is proposed rather than none. Five of the
        # eight interventions are answered mainly by cluster training, and a
        # school-only filter would report them as unanswerable.
        answers = ActivityCatalogueItem.objects.filter(
            intervention_mappings__intervention=intervention,
            intervention_mappings__active=True,
            status="active",
        ).order_by("-intervention_mappings__is_primary", "display_name")
        item = answers.filter(individual_school_allowed=True).first() or answers.first()
        try:
            with transaction.atomic():
                recommendation = SsaRecommendation.objects.create(
                    condition_key=key,
                    school=school,
                    ssa_record=record,
                    intervention=intervention,
                    fy=fy,
                    score=finding.get("score"),
                    score_band=(
                        finding.get("band") or finding.get("classification") or ""
                    ),
                    rank=rank,
                    reason=explain(finding),
                    recommended_item=item,
                    unmapped_reason=(
                        ""
                        if item
                        else "No published school-level activity answers this "
                        "intervention."
                    ),
                    expires_on=(
                        timezone.localdate() + timedelta(days=DEFAULT_VALIDITY_DAYS)
                    ),
                    engine_version=ENGINE_VERSION,
                    supersedes=_previous_for(key),
                )
        except IntegrityError:
            # Another worker raised the same need between our check and our
            # write. The constraint is the authority; converge on its answer.
            refreshed += 1
            continue
        created += 1
        _audit(
            "ssa.recommendation_generated", recommendation, principal, {"rank": rank}
        )

    return {"created": created, "refreshed": refreshed, "skipped": None}


def explain(finding: dict) -> str:
    """Say, in the reader's language, why this ranked where it did.

    The engine's composite priority is a number built from four measurable
    components. A number nobody can read is a ranking nobody can challenge, so
    this turns the components that actually fired into sentences — and says
    when one could not be measured rather than quietly treating it as zero.
    """
    label = finding.get("label") or finding.get("intervention") or "This area"
    band = finding.get("band") or "unscored"
    parts = [f"{label} scored {finding.get('score')} ({band})."]
    components = finding.get("components") or {}

    peer = components.get("peer_gap") or {}
    if peer.get("measurable") and peer.get("z_score", 0) < 0:
        parts.append(
            f"It sits below the cluster average of {peer.get('peer_mean')} "
            f"across {peer.get('peer_count')} peer schools."
        )

    trend = components.get("trend") or {}
    if trend.get("measurable") and trend.get("direction") == "declining":
        parts.append("It has been declining across assessments.")

    persistence = components.get("persistence") or {}
    if persistence.get("measurable") and persistence.get("below_count"):
        parts.append(
            f"It has stayed weak in {persistence['below_count']} of the last "
            f"{persistence['considered']} assessments."
        )

    prior = finding.get("prior_support_count") or 0
    parts.append(
        f"{prior} previous support activit{'y has' if prior == 1 else 'ies have'} "
        f"not moved it."
        if prior
        else "No support has been delivered against it yet."
    )

    confidence = finding.get("confidence")
    if confidence and confidence != "high":
        parts.append(
            f"Confidence is {confidence} — there are few assessments to compare."
        )
    return " ".join(parts)


def _previous_for(condition_key: str):
    """The most recent closed recommendation for this same need, if any."""
    return (
        SsaRecommendation.objects.filter(condition_key=condition_key)
        .exclude(state__in=LIVE_STATES)
        .order_by("-created_at")
        .first()
    )


def _transition(recommendation, *, to, principal, reason="", **extra):
    if not recommendation.is_live:
        raise BadRequest(
            f"This recommendation is already {recommendation.get_state_display()}."
        )
    recommendation.state = to
    recommendation.decided_by_id = getattr(principal, "id", None)
    recommendation.decided_at = timezone.now()
    if reason:
        recommendation.decision_reason = reason.strip()
    for field, value in extra.items():
        setattr(recommendation, field, value)
    recommendation.save()
    _audit(f"ssa.recommendation_{to}", recommendation, principal, {"reason": reason})
    return recommendation


def accept(recommendation, principal, *, owner_id=None):
    """Take the need on. The activity comes later; ownership starts now."""
    return _transition(
        recommendation,
        to=RecommendationState.ACCEPTED,
        principal=principal,
        owner_id=owner_id or getattr(principal, "id", None),
    )


def defer(recommendation, principal, *, reason: str):
    """Postpone it. Still live — the school still has the weakness."""
    if not (reason or "").strip():
        raise BadRequest("Deferring a measured weakness requires a reason.")
    return _transition(
        recommendation,
        to=RecommendationState.DEFERRED,
        principal=principal,
        reason=reason,
    )


def reject(recommendation, principal, *, reason: str):
    """Decide not to act. Closes the need without the work being done."""
    if not (reason or "").strip():
        raise BadRequest("Rejecting a measured weakness requires a reason.")
    return _transition(
        recommendation,
        to=RecommendationState.REJECTED,
        principal=principal,
        reason=reason,
    )


def mark_planned(recommendation, activity, principal=None):
    """An activity now answers this need."""
    return _transition(
        recommendation,
        to=RecommendationState.PLANNED,
        principal=principal,
        planned_activity=activity,
    )


def mark_delivered(recommendation, principal=None):
    """Verified work closed it. A later recurrence is a NEW need."""
    return _transition(
        recommendation, to=RecommendationState.DELIVERED, principal=principal
    )


def supersede_stale(school, *, fy: str, principal=None) -> int:
    """Retire live recommendations built on an assessment newer work replaced.

    Called when a fresher SSA is confirmed: the old picture stops being the
    basis for a decision, and a queue that keeps showing it is showing
    something nobody should act on.
    """
    from apps.ssa.services import latest_applicable_record

    current = latest_applicable_record(school)
    if current is None:
        return 0
    stale = list(
        SsaRecommendation.objects.filter(
            school=school, fy=fy, state__in=LIVE_STATES
        ).exclude(ssa_record_id=current.id)
    )
    for recommendation in stale:
        recommendation.state = RecommendationState.SUPERSEDED
        recommendation.decision_reason = "A newer confirmed assessment replaced it."
        recommendation.decided_at = timezone.now()
        recommendation.save(
            update_fields=[
                "state",
                "decision_reason",
                "decided_at",
                "updated_at",
            ]
        )
        _audit("ssa.recommendation_superseded", recommendation, principal)
    return len(stale)


def open_recommendations(*, school_ids=None, fy=None, owner_id=None):
    """The live queue — what is outstanding, worst first."""
    query = SsaRecommendation.objects.filter(state__in=LIVE_STATES)
    if school_ids is not None:
        query = query.filter(school_id__in=list(school_ids))
    if fy:
        query = query.filter(fy=fy)
    if owner_id:
        query = query.filter(owner_id=owner_id)
    return query.select_related("school", "recommended_item").order_by(
        "rank", "score", "school__name"
    )
