"""Whether a plan is informed by the SSA, decided once for every plan.

Owner, 2026-09-13: every school activity plan (school visits, trainings,
cluster meetings and the rest) must be SSA informed. The recommendation engine
(`apps.ssa.recommendation_engine`) already ranks what a school needs, and the
school scheduling drawer shows it. But a plan was only as informed as the
screen it came from: a School Visit named no intervention unless the planner
picked one, a cluster session was chosen with no member evidence at all, a
partner assignment or an accepted weekly proposal carried none, and nothing
said afterwards whether a plan had followed the SSA or ignored it.

This module is the one answer, applied inside the canonical scheduling funnel
(`apps.activities.services.create`) so every entry point inherits it:

* ``default_focus`` names the intervention an any-intervention support plan
  targets when the planner named none: the school's top ranked need, or for a
  cluster session the weakest intervention across its assessed member schools.
* ``assess`` classifies the plan against the verified SSA and returns the
  evidence it was judged on, frozen at planning time.
* ``stamp`` writes that verdict onto the activity and hands the need to the
  recommendation lifecycle, so a recorded recommendation shows it is planned.
* ``settle_recommendations`` closes the loop when the work is verified, or
  releases the need when the plan is cancelled.

Nothing here blocks a plan. The owner removed planning restrictions, and a
missing SSA is a prompt rather than a reason to refuse support (see the school
drawer). What changes is that the plan says plainly what informed it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from django.utils import timezone

from apps.core.enums import (
    ActivityType,
    SsaAlignment,
    SsaIntervention,
    ssa_score_band,
)

ENGINE_VERSION = "apps.ssa.plan_alignment/2026-09"

#: How many of a school's ranked needs count as its priorities.
PRIORITY_DEPTH = 3
#: At or above this an intervention is Strong (apps.core.enums.ssa_score_band).
STRONG_SCORE = 8.0
#: Below this it is Critical, and every Critical intervention is a priority
#: however many there are.
CRITICAL_SCORE = 5.0

#: Work that exists to collect or review the SSA itself.
SSA_COLLECTION_KINDS = frozenset(
    {
        ActivityType.BASELINE_SSA_VISIT,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
        ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
        ActivityType.CLUSTER_MEETING_SSA_REVIEW,
        ActivityType.PARTNER_SSA_COLLECTION,
        ActivityType.CORE_ASSESSMENT_VISIT,
        ActivityType.SSA_ACTIVITY,
    }
)

#: Relationship and programme work: a donor visit or a camp is not meant to
#: move an intervention score, and naming one would put it into
#: school-improvement analytics under false pretences.
NOT_SCHOOL_IMPROVEMENT_KINDS = frozenset(
    {
        ActivityType.DONOR_VISIT,
        ActivityType.STORY_GATHERING_VISIT,
        ActivityType.SCHOOL_INVITATION,
        ActivityType.SOCIAL_VISIT,
        ActivityType.FIELD_EVENT,
        ActivityType.PROGRAMME_EVENT,
    }
)

#: Statuses at which the work that answered a need is verified.
DELIVERED_STATUSES = ("ia_verified", "accountant_confirmed", "closed")
#: Statuses at which a plan stops answering the need it was planned for.
RELEASED_STATUSES = ("cancelled", "rejected", "deferred")


#: The verdicts that count as SSA informed.
INFORMED = (
    SsaAlignment.PRIORITY,
    SsaAlignment.SSA_COLLECTION,
    SsaAlignment.NOT_APPLICABLE,
)
#: The verdicts that need attention: the plan names a target the SSA does not
#: support, names none, or had no assessment to follow.
UNINFORMED = (
    SsaAlignment.OFF_PRIORITY,
    SsaAlignment.NO_FOCUS,
    SsaAlignment.NO_SSA,
)

_LABELS = dict(SsaIntervention.choices)


# ── What the plan is ─────────────────────────────────────────────────────────
def plan_nature(
    activity_type: str | None, mapping_modes=(), *, collects_ssa: bool = False
) -> str:
    """``collection``, ``not_applicable`` or ``support`` for one plan.

    The catalogue mapping is the authority where it exists: an SSA-completion
    prerequisite collects the SSA and an administrative item is not
    school-improvement work. A visit scheduled to collect the SSA
    (``ssa_collection_expected``) collects it whatever its kind. The workflow
    kind decides the rest, which also covers legacy rows planned before the
    catalogue.
    """
    modes = set(mapping_modes or ())
    if (
        collects_ssa
        or activity_type in SSA_COLLECTION_KINDS
        or "ssa_completion_prerequisite" in modes
    ):
        return "collection"
    if activity_type in NOT_SCHOOL_IMPROVEMENT_KINDS or (
        modes and modes <= {"administrative"}
    ):
        return "not_applicable"
    return "support"


def _priority_codes(ranked: list[tuple[str, float]]) -> list[str]:
    """The priorities among interventions already ranked most urgent first.

    The top ranked needs that are not Strong, every Critical intervention, and
    when a school is Strong throughout, its single weakest area.
    """
    needs = [code for code, score in ranked if score < STRONG_SCORE]
    chosen = needs[:PRIORITY_DEPTH]
    chosen += [
        code for code, score in ranked if score < CRITICAL_SCORE and code not in chosen
    ]
    if not chosen and ranked:
        chosen = [ranked[0][0]]
    return chosen


# ── What the SSA says ────────────────────────────────────────────────────────
@dataclass
class SchoolNeed:
    record: object | None
    ranked: list[dict] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)

    @property
    def assessed(self) -> bool:
        return self.record is not None and bool(self.ranked)


def school_need(school) -> SchoolNeed:
    """The school's verified need, ranked by the recommendation engine."""
    from apps.ssa.recommendation_engine import prioritized_interventions
    from apps.ssa.services import latest_applicable_record

    if school is None:
        return SchoolNeed(None)
    record = latest_applicable_record(school)
    if record is None:
        return SchoolNeed(None)
    ranked = prioritized_interventions(school)
    return SchoolNeed(
        record,
        ranked,
        _priority_codes([(row["intervention"], row["score"]) for row in ranked]),
    )


@dataclass
class ClusterNeed:
    member_count: int
    rows: list[dict] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)
    assessed_schools: int = 0
    source_ssa_ids: list[str] = field(default_factory=list)

    @property
    def assessed(self) -> bool:
        return bool(self.rows)


def cluster_need(cluster_id, school_ids=None) -> ClusterNeed:
    """Verified need across a cluster's member schools, from their latest
    confirmed SSAs. There is no cluster SSA; this never invents one.

    Interventions rank by their average across the assessed members, weakest
    first (the ranking the cluster page's weakest-interventions panel uses), and
    each row says how many schools sit below the 5.5 weakness line.
    """
    from apps.schools.models import School
    from apps.ssa.services import latest_applicable_records

    if not cluster_id:
        return ClusterNeed(0)
    members = School.objects.filter(cluster_id=cluster_id, deleted_at__isnull=True)
    if school_ids:
        members = members.filter(id__in=list(school_ids))
    members = list(members.only("id", "school_id"))
    records = latest_applicable_records(members, with_scores=True)
    scores: dict[str, list[float]] = defaultdict(list)
    for record in records.values():
        for score in record.scores.all():
            if score.score is not None and score.intervention in _LABELS:
                scores[score.intervention].append(float(score.score))
    rows = []
    for code, values in scores.items():
        average = round(sum(values) / len(values), 1)
        band, _hex, _tone = ssa_score_band(average)
        rows.append(
            {
                "intervention": code,
                "label": _LABELS[code],
                "average": average,
                "band": band,
                "schoolsAssessed": len(values),
                "schoolsBelow": sum(1 for value in values if value < 5.5),
            }
        )
    rows.sort(key=lambda row: (row["average"], row["intervention"]))
    return ClusterNeed(
        member_count=len(members),
        rows=rows,
        priorities=_priority_codes(
            [(row["intervention"], row["average"]) for row in rows]
        ),
        assessed_schools=len(records),
        source_ssa_ids=sorted(record.id for record in records.values())[:50],
    )


# ── The verdict ──────────────────────────────────────────────────────────────
@dataclass
class PlanEvidence:
    alignment: str
    focus: str | None
    evidence: dict

    @property
    def informed(self) -> bool:
        return self.alignment in INFORMED


def default_focus(
    *,
    activity_type: str | None,
    mapping_modes=(),
    school=None,
    cluster_id=None,
    school_ids=None,
    school_need_=None,
    cluster_need_=None,
    collects_ssa: bool = False,
) -> str | None:
    """The intervention a support plan should target when none was named.

    Only for any-intervention support (standard school visits, in-school
    support, coaching, cluster meetings and cluster trainings without a named
    course). A named course, a follow-up or a project decides its own
    intervention, and collection or relationship work names none.
    """
    modes = set(mapping_modes or ())
    if plan_nature(activity_type, modes, collects_ssa=collects_ssa) != "support":
        return None
    if modes and "any_ssa_intervention" not in modes:
        return None
    if school is not None:
        need = school_need_ or school_need(school)
        return need.priorities[0] if need.priorities else None
    if cluster_id:
        need = cluster_need_ or cluster_need(cluster_id, school_ids)
        return need.priorities[0] if need.priorities else None
    return None


def assess(
    *,
    activity_type: str | None,
    focus: str | None,
    mapping_modes=(),
    school=None,
    cluster_id=None,
    school_ids=None,
    focus_source: str = "planner",
    school_need_=None,
    cluster_need_=None,
    collects_ssa: bool = False,
) -> PlanEvidence:
    """Judge one plan against the verified SSA and keep what it was judged on."""
    nature = plan_nature(activity_type, mapping_modes, collects_ssa=collects_ssa)
    evidence: dict = {
        "engine": ENGINE_VERSION,
        "assessedOn": timezone.localdate().isoformat(),
        "nature": nature,
        "focus": focus or None,
        "focusSource": focus_source if focus else "",
    }

    if school is not None:
        need = school_need_ or school_need(school)
        if need.record is not None:
            evidence["school"] = _school_evidence(need, focus)
        priorities = need.priorities
        assessed = need.assessed
    elif cluster_id:
        need = cluster_need_ or cluster_need(cluster_id, school_ids)
        evidence["cluster"] = _cluster_evidence(need, focus)
        priorities = need.priorities
        assessed = need.assessed
    else:
        # Non-school programme work has no school to assess.
        return PlanEvidence(
            SsaAlignment.NOT_APPLICABLE
            if nature != "collection"
            else SsaAlignment.SSA_COLLECTION,
            focus,
            {**evidence, "alignment": SsaAlignment.NOT_APPLICABLE},
        )

    if nature == "collection":
        alignment = SsaAlignment.SSA_COLLECTION
    elif nature == "not_applicable":
        alignment = SsaAlignment.NOT_APPLICABLE
    elif not assessed:
        alignment = SsaAlignment.NO_SSA
    elif not focus:
        alignment = SsaAlignment.NO_FOCUS
    elif focus in priorities:
        alignment = SsaAlignment.PRIORITY
    else:
        alignment = SsaAlignment.OFF_PRIORITY
    evidence["alignment"] = alignment
    return PlanEvidence(alignment, focus, evidence)


def _school_evidence(need: SchoolNeed, focus: str | None) -> dict:
    record = need.record
    by_code = {row["intervention"]: row for row in need.ranked}
    chosen = by_code.get(focus) if focus else None
    top = need.ranked[0] if need.ranked else None
    return {
        "ssaId": record.id,
        "ssaDate": record.date_of_ssa.isoformat() if record.date_of_ssa else None,
        "ssaFy": record.fy,
        "averageScore": record.average_score,
        "priorities": list(need.priorities),
        "top": _need_summary(top),
        "focusScore": chosen["score"] if chosen else None,
        "focusBand": chosen["band"] if chosen else None,
        "focusRank": (
            [row["intervention"] for row in need.ranked].index(focus) + 1
            if chosen
            else None
        ),
    }


def _cluster_evidence(need: ClusterNeed, focus: str | None) -> dict:
    by_code = {row["intervention"]: row for row in need.rows}
    chosen = by_code.get(focus) if focus else None
    return {
        "members": need.member_count,
        "assessedSchools": need.assessed_schools,
        "priorities": list(need.priorities),
        "top": dict(need.rows[0]) if need.rows else None,
        "focusAverage": chosen["average"] if chosen else None,
        "focusSchoolsBelow": chosen["schoolsBelow"] if chosen else None,
        "focusRank": (
            [row["intervention"] for row in need.rows].index(focus) + 1
            if chosen
            else None
        ),
        "sourceSsaIds": list(need.source_ssa_ids),
    }


def _need_summary(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "intervention": row["intervention"],
        "label": row.get("label") or _LABELS.get(row["intervention"], ""),
        "score": row.get("score"),
        "band": row.get("band"),
    }


def reason_for(evidence: PlanEvidence) -> str:
    """One sentence a planner, a PL or IA can read about the verdict."""
    data = evidence.evidence
    focus_label = _LABELS.get(evidence.focus or "", "")
    alignment = evidence.alignment
    if alignment == SsaAlignment.SSA_COLLECTION:
        return "Collects the SSA this school's support will be planned from."
    if alignment == SsaAlignment.NOT_APPLICABLE:
        return "Not school-improvement work, so no SSA intervention applies."
    if alignment == SsaAlignment.NO_SSA:
        return (
            "No verified SSA yet: collect the assessment so support can target a "
            "measured need."
        )
    school = data.get("school")
    cluster = data.get("cluster")
    if alignment == SsaAlignment.NO_FOCUS:
        top = (school or {}).get("top") or (cluster or {}).get("top") or {}
        return (
            f"Names no intervention although the SSA ranks "
            f"{top.get('label', 'a need')} first."
        )
    if school:
        rank = school.get("focusRank")
        score = school.get("focusScore")
        where = f"ranked {rank} of the school's needs" if rank else "not scored"
        prefix = "Targets" if alignment == SsaAlignment.PRIORITY else "Targets"
        suffix = (
            ""
            if alignment == SsaAlignment.PRIORITY
            else f"; the SSA ranks {(school.get('top') or {}).get('label', 'another need')} first"
        )
        return f"{prefix} {focus_label} ({score}/10, {where}){suffix}."
    if cluster:
        rank = cluster.get("focusRank")
        average = cluster.get("focusAverage")
        below = cluster.get("focusSchoolsBelow")
        detail = (
            f"cluster average {average}/10, {below} of "
            f"{cluster.get('assessedSchools')} assessed schools below 5.5"
            if rank
            else "not scored in any member school"
        )
        suffix = (
            ""
            if alignment == SsaAlignment.PRIORITY
            else f"; the weakest cluster need is {(cluster.get('top') or {}).get('label', 'another')}"
        )
        return f"Targets {focus_label} ({detail}){suffix}."
    return ""


# ── Writing it down ──────────────────────────────────────────────────────────
def stamp(activity, evidence: PlanEvidence, *, link: bool = True) -> None:
    """Record the verdict on the activity and hand the need to the lifecycle."""
    source = dict(activity.recommendation_source or {})
    source["ssa"] = {**evidence.evidence, "reason": reason_for(evidence)}
    activity.recommendation_source = source
    activity.ssa_alignment = evidence.alignment
    update_fields = ["recommendation_source", "ssa_alignment", "updated_at"]

    school = (evidence.evidence or {}).get("school")
    if school and not activity.source_ssa_id:
        activity.source_ssa_id = school["ssaId"]
        activity.source_ssa_verification_state = "confirmed"
        update_fields += ["source_ssa", "source_ssa_verification_state"]
        if school.get("focusScore") is not None and activity.source_score is None:
            activity.source_score = school["focusScore"]
            activity.source_classification = school.get("focusBand")
            update_fields += ["source_score", "source_classification"]
    if not activity.recommendation_reason:
        activity.recommendation_reason = reason_for(evidence)
        update_fields.append("recommendation_reason")
    activity.save(update_fields=update_fields)
    if link:
        link_recommendations(activity)


def _cluster_school_ids(activity) -> list[str]:
    from apps.activities.models import ClusterActivityAttendance

    invited = list(
        ClusterActivityAttendance.objects.filter(
            activity_id=activity.id, invited=True
        ).values_list("school_id", flat=True)
    )
    if invited:
        return invited
    from apps.schools.models import School

    return list(
        School.objects.filter(
            cluster_id=activity.cluster_id, deleted_at__isnull=True
        ).values_list("id", flat=True)
    )


def link_recommendations(activity) -> int:
    """Mark the recorded recommendations this plan answers as planned.

    The live recommendation for the same school and intervention, whatever the
    FY it was raised in: an SSA confirmed last year is still the evidence a
    plan this year acts on. A cluster session answers the recommendation of
    every school it invited.
    """
    from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation

    if not activity.focus_intervention:
        return 0
    if activity.school_id:
        school_ids = [activity.school_id]
    elif activity.cluster_id:
        school_ids = _cluster_school_ids(activity)
    else:
        return 0
    open_states = (
        RecommendationState.GENERATED,
        RecommendationState.ACCEPTED,
        RecommendationState.DEFERRED,
    )
    recommendations = list(
        SsaRecommendation.objects.filter(
            school_id__in=school_ids,
            intervention=activity.focus_intervention,
            state__in=open_states,
        ).order_by("school_id", "-created_at")
    )
    if not recommendations:
        return 0
    now = timezone.now()
    ids = [recommendation.id for recommendation in recommendations]
    SsaRecommendation.objects.filter(id__in=ids).update(
        state=RecommendationState.PLANNED,
        planned_activity_id=activity.id,
        decided_at=now,
        updated_at=now,
    )
    if activity.school_id and not activity.ssa_recommendation_id:
        activity.ssa_recommendation_id = recommendations[0].id
        activity.save(update_fields=["ssa_recommendation", "updated_at"])
    _audit_recommendations("ssa.recommendation_planned", activity, ids)
    return len(ids)


def settle_recommendations(activity) -> int:
    """Close or release the recommendations a plan was answering.

    Verified work delivers them; for a cluster session only the schools that
    attended, the rest go back to the queue. A cancelled, rejected or deferred
    plan releases them so the need is visible again.
    """
    from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation

    status = getattr(activity, "status", "")
    if status not in DELIVERED_STATUSES and status not in RELEASED_STATUSES:
        return 0
    planned = list(
        SsaRecommendation.objects.filter(
            planned_activity_id=activity.id, state=RecommendationState.PLANNED
        ).values_list("id", "school_id")
    )
    if not planned:
        return 0
    now = timezone.now()
    delivered: list[str] = []
    released: list[str] = []
    if status in DELIVERED_STATUSES:
        attended = None
        if activity.cluster_id and not activity.school_id:
            from apps.activities.models import ClusterActivityAttendance

            attended = set(
                ClusterActivityAttendance.objects.filter(
                    activity_id=activity.id, attended=True
                ).values_list("school_id", flat=True)
            ) or set(activity.attended_school_ids or [])
        for rec_id, school_id in planned:
            if attended is None or school_id in attended:
                delivered.append(rec_id)
            else:
                released.append(rec_id)
    else:
        released = [rec_id for rec_id, _school in planned]
    if delivered:
        SsaRecommendation.objects.filter(id__in=delivered).update(
            state=RecommendationState.DELIVERED, decided_at=now, updated_at=now
        )
        _audit_recommendations("ssa.recommendation_delivered", activity, delivered)
    if released:
        SsaRecommendation.objects.filter(id__in=released).update(
            state=RecommendationState.ACCEPTED,
            planned_activity_id=None,
            decided_at=now,
            updated_at=now,
            decision_reason=(
                "The planned activity was "
                + ("not attended" if status in DELIVERED_STATUSES else status)
                + "; the need is back in the queue."
            ),
        )
        _audit_recommendations("ssa.recommendation_released", activity, released)
    return len(delivered) + len(released)


def rejudge(activity, *, focus_source: str = "planner") -> PlanEvidence:
    """Judge a live plan again after its target intervention changed.

    A plan's intervention can be edited after it was made; the verdict and the
    recommendation it answered were then describing the old target. The
    recommendations planned against the old target go back to the queue, and
    the plan is judged, and linked, as it now stands.
    """
    from apps.ssa.recommendation_models import RecommendationState, SsaRecommendation

    now = timezone.now()
    stale = SsaRecommendation.objects.filter(
        planned_activity_id=activity.id, state=RecommendationState.PLANNED
    ).exclude(intervention=activity.focus_intervention or "")
    released = list(stale.values_list("id", flat=True))
    if released:
        SsaRecommendation.objects.filter(id__in=released).update(
            state=RecommendationState.ACCEPTED,
            planned_activity_id=None,
            decided_at=now,
            updated_at=now,
            decision_reason="The planned activity now targets another intervention.",
        )
        _audit_recommendations("ssa.recommendation_released", activity, released)
        if activity.ssa_recommendation_id in released:
            activity.ssa_recommendation_id = None
            activity.save(update_fields=["ssa_recommendation", "updated_at"])
    modes = (
        set(
            activity.catalogue_item.intervention_mappings.filter(
                active=True
            ).values_list("mapping_mode", flat=True)
        )
        if activity.catalogue_item_id
        else set()
    )
    evidence = assess(
        activity_type=activity.activity_type,
        focus=activity.focus_intervention,
        mapping_modes=modes,
        school=activity.school if activity.school_id else None,
        cluster_id=None if activity.school_id else activity.cluster_id,
        focus_source=focus_source,
        collects_ssa=activity.ssa_collection_expected,
    )
    stamp(activity, evidence)
    return evidence


LIVE_PLAN_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "awaiting_owner_approval",
    "in_progress",
    "completion_started",
)


def judge_unjudged_plans(fy: str, *, limit: int | None = None) -> tuple[int, int]:
    """Judge live plans that carry no verdict yet, and link what they answer.

    Plans made before plans were judged at planning time have no verdict. They
    are judged against the SSA as it stands today and marked as backfilled;
    completed history is never re-judged, because what informed finished work
    is what was known when it was planned. Run nightly after recommendations
    are synced, and by ``audit_ssa_informed_plans --stamp``. Returns
    (plans judged, recommendations linked).
    """
    from apps.activities.models import Activity

    plans = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            fy=fy,
            status__in=LIVE_PLAN_STATUSES,
            ssa_alignment="",
        )
        .select_related("school", "catalogue_item")
        .order_by("planned_date", "id")
    )
    stamped = linked = 0
    for activity in plans.iterator(chunk_size=200):
        modes = (
            set(
                activity.catalogue_item.intervention_mappings.filter(
                    active=True
                ).values_list("mapping_mode", flat=True)
            )
            if activity.catalogue_item_id
            else set()
        )
        evidence = assess(
            activity_type=activity.activity_type,
            focus=activity.focus_intervention,
            mapping_modes=modes,
            school=activity.school,
            cluster_id=None if activity.school_id else activity.cluster_id,
            focus_source="planner",
            collects_ssa=activity.ssa_collection_expected,
        )
        evidence.evidence["backfilled"] = True
        stamp(activity, evidence, link=False)
        linked += link_recommendations(activity)
        stamped += 1
        if limit and stamped >= limit:
            break
    return stamped, linked


def _audit_recommendations(action: str, activity, ids) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="Activity",
            subject_id=activity.id,
            actor_id="system",
            actor_role="",
            payload={
                "recommendationIds": list(ids)[:200],
                "intervention": activity.focus_intervention or "",
                "status": activity.status,
            },
        )
    except Exception:  # noqa: BLE001 — the audit never blocks the lifecycle
        pass
