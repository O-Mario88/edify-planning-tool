"""Core-schools service — candidates → verify → onboard → slots → champion."""

from __future__ import annotations


from django.db import transaction
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.calendar_policy import SchedulingPolicyService, resolve_scheduling_user
from apps.schools.models import School

from .models import (
    CoreActivitySlot,
    CoreCandidateVerification,
    CorePlan,
    CoreSchoolOnboarding,
    CoreSchoolProfile,
    cplan_id,
    cprof_id,
)

# The 11 polymorphic slot actions.
SLOT_ACTIONS = {
    "assign",
    "schedule",
    "start",
    "evidence",
    "acceptEvidence",
    "returnEvidence",
    "complete",
    "plVerify",
    "iaVerify",
    "return",
    "accountantConfirm",
}

# Activity statuses that represent the field work as verified/settled done —
# mirrors the "completed" statusGroup bucket in
# activities.services.list_activities(), the canonical "is this activity
# done?" definition already used elsewhere in the app. "closed" is the
# terminal state written by ActivityClosureService — omitting it made a
# fully-closed package drop back OUT of the completion counters.
CORE_SLOT_DONE_STATUSES = {"completed", "closed", "ia_verified", "accountant_confirmed"}

# Legacy CamelCase spellings written only by the unreachable DRF slot_action
# path; kept in read queries so historical rows are not stranded. Never write
# these values.
CORE_SLOT_DONE_WITH_LEGACY = CORE_SLOT_DONE_STATUSES | {
    "Completed",
    "Accountant Confirmed",
    "iaVerify",
}

# The mandatory Core School package: 1 Core Assessment + 4 visits + 4
# trainings = 9 slots. This spec is the single source of truth for slot
# creation (onboard + self-heal) and every completion threshold — never
# hardcode "8" or "9" against it again.
CORE_PACKAGE_SPEC = (("a", 1), ("v", 4), ("t", 4))
CORE_SLOT_KIND_TO_TYPE = {"a": "assessment", "v": "visit", "t": "training"}
EXPECTED_CORE_SLOTS = sum(count for _kind, count in CORE_PACKAGE_SPEC)


def create_package_slots(
    plan, school_id, interventions, actor_id=None, actor_name=None
):
    """Create the canonical 9-slot Core package if not already present.
    Shared by the onboard path and the self-heal path so they can never
    drift. Idempotent via get_or_create on the deterministic slot id."""
    from apps.core_schools.models import CoreActivitySlot, cslot_id

    interventions = interventions or ["christlike_behaviour"]
    for kind, count in CORE_PACKAGE_SPEC:
        for seq in range(1, count + 1):
            CoreActivitySlot.objects.get_or_create(
                id=cslot_id(school_id, kind, seq, fy=plan.fy),
                defaults={
                    "core_plan": plan,
                    "school_id": school_id,
                    "intervention": interventions[(seq - 1) % len(interventions)],
                    "activity_type": CORE_SLOT_KIND_TO_TYPE[kind],
                    "sequence_number": seq,
                },
            )


def list_candidates(principal) -> list[dict]:
    """Best-SSA client/potential-core/potential-champion schools → candidate
    for core onboarding. potential_champion is included here (not on a
    separate Champion-candidates pipeline) because ChampionEligibilityService
    only evaluates schools that already have a CoreSchoolProfile, which is
    only created through this same Core onboarding path — a "potential
    champion" school's actual next step is identical to a "potential core"
    school's, and it used to be invisible to every workflow (not client-only,
    not core, no CoreSchoolProfile) until it went through here."""
    qs = School.objects.filter(
        deleted_at__isnull=True,
        school_type__in=["client", "potential_core", "potential_champion"],
    )
    out = []
    for s in qs:
        latest = (
            s.ssa_records.filter(
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .order_by("-date_of_ssa", "-created_at")
            .first()
        )
        if latest and (latest.average_score or 0) >= 7.0:
            out.append(
                {
                    "schoolId": s.school_id,
                    "name": s.name,
                    "schoolType": s.school_type,
                    "averageScore": latest.average_score,
                }
            )
    return out


def verify_candidate(school_id: str, data: dict, principal) -> dict:
    """IA verifies a Potential Core candidate (SSA >= 7.5 gate)."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    latest = (
        school.ssa_records.filter(
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .order_by("-date_of_ssa", "-created_at")
        .first()
    )
    if not latest:
        raise BadRequest("No SSA record to verify against.")
    verification = CoreCandidateVerification.objects.create(
        school_id=school_id,
        ssa_record_id=latest.id,
        verification_id=data.get("verificationId", ""),
        verified_by_id=principal.user_id,
        verified_by_name=principal.name,
        verified_at=timezone.now(),
        status=data.get("status", "Verified Potential Core"),
        comments=data.get("comments"),
    )
    if data.get("status", "Verified Potential Core") != "Rejected":
        school.school_type = "potential_core"
        school.save(update_fields=["school_type"])
    return {"id": verification.id, "schoolId": school_id, "status": verification.status}


def reject_candidate(school_id: str, data: dict, principal) -> dict:
    return verify_candidate(school_id, {**data, "status": "Rejected"}, principal)


def onboard(school_id: str, data: dict, principal) -> dict:
    """Onboard a verified candidate to Core: creates CorePlan + 8 slots + profile."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    latest = (
        school.ssa_records.filter(
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .order_by("-date_of_ssa", "-created_at")
        .first()
    )
    baseline_avg = latest.average_score if latest else 0.0
    fy = get_operational_fy()
    plan_id = cplan_id(school_id, fy=fy)

    with transaction.atomic():
        plan, _ = CorePlan.objects.update_or_create(
            id=plan_id,
            defaults={
                "school_id": school_id,
                "fy": fy,
                "status": "Active",
                "baseline_average": baseline_avg,
                "baseline_ssa_record_id": latest.id if latest else None,
                "created_by_id": principal.user_id,
                "created_by_name": principal.name,
            },
        )
        CoreSchoolProfile.objects.update_or_create(
            id=cprof_id(school_id),
            defaults={"school_id": school_id, "core_plan": plan, "core_start_fy": fy},
        )
        CoreSchoolOnboarding.objects.update_or_create(
            school_id=school_id,
            defaults={
                "core_plan": plan,
                "fy": fy,
                "previous_school_type": school.school_type,
                "baseline_ssa_record_id": latest.id if latest else "",
                "baseline_average_score": baseline_avg,
                "onboarded_by_id": principal.user_id,
                "onboarded_by_name": principal.name,
                "onboarded_at": timezone.now(),
                "onboarding_reason": data.get("reason"),
            },
        )
        # Persist the four-weakest recommendation on the plan, anchored to the
        # baseline SSA record. CorePlan.interventions existed but was never
        # written: the recommendation recomputed live against whatever the
        # latest SSA later became, so the historical rationale for the package
        # was lost and slots were seeded round-robin across ALL interventions
        # instead of the recommended four.
        from apps.core_schools.core_planning_services import (
            CoreInterventionRecommendationService,
        )

        recommendation = CoreInterventionRecommendationService.recommend(school)
        recommended_rows = recommendation.get("rows") or []
        plan.interventions = {
            "recommended": recommended_rows,
            "maintenance": recommendation.get("maintenance", False),
            "source_ssa_record_id": latest.id if latest else None,
            "captured_at": timezone.now().isoformat(),
            # Version anchor: a later SSA or algorithm change must never
            # rewrite the historical rationale this package was planned on.
            "algorithm_version": 1,
        }
        plan.save(update_fields=["interventions", "updated_at"])

        # Create the canonical 9-slot package (1 assessment + 4 visit +
        # 4 training) if not present — seeded from the recommended weakest
        # interventions when a baseline exists, else the full canonical list.
        interventions = [row["code"] for row in recommended_rows] or [
            i.value for i in SsaIntervention
        ]
        create_package_slots(plan, school_id, interventions)
        school.school_type = "core"
        school.save(update_fields=["school_type"])
    return _serialize_plan(plan)


def list_plans(principal) -> list[dict]:
    qs = CorePlan.objects.filter(status="Active")
    return [_serialize_plan(p) for p in qs]


def get_detail(school_id: str, principal) -> dict:
    plan = CorePlan.objects.filter(school_id=school_id).first()
    if not plan:
        raise NotFoundError("No core plan for this school.")
    data = _serialize_plan(plan)
    data["slots"] = [
        _serialize_slot(s)
        for s in plan.slots.order_by("activity_type", "sequence_number")
    ]
    return data


def slot_action(slot_id: str, action: str, data: dict, principal) -> dict:
    """Polymorphic slot action (11-action allowlist)."""
    if action not in SLOT_ACTIONS:
        raise BadRequest(f"Unknown slot action '{action}'.")
    slot = CoreActivitySlot.objects.filter(id=slot_id).first()
    if not slot:
        raise NotFoundError("Slot not found.")

    if action == "assign":
        slot.assigned_staff_id = data.get("assignedStaffId")
        slot.assigned_staff_name = data.get("assignedStaffName")
        slot.assigned_partner_id = data.get("assignedPartnerId")
        slot.assigned_partner_name = data.get("assignedPartnerName")
        slot.owner = "partner" if data.get("assignedPartnerId") else "staff"
        slot.status = "Assigned"
    elif action == "schedule":
        scheduled_for = data.get("scheduledFor")
        if scheduled_for:
            # REG-02 — same calendar gate every other scheduling surface
            # applies; a core slot must never land on a date Planning/My
            # Plan would have blocked.
            resp_user = resolve_scheduling_user(slot.assigned_staff_id)
            avail = SchedulingPolicyService.check(resp_user, scheduled_for)
            if avail["status"] == "blocked":
                raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))
        slot.scheduled_month = data.get("scheduledMonth")
        slot.scheduled_week = data.get("scheduledWeek")
        slot.scheduled_for = scheduled_for
        slot.status = "Scheduled"
    elif action == "start":
        slot.status = "In Progress"
    elif action == "evidence":
        slot.evidence_uri = data.get("evidenceUri")
        slot.evidence_notes = data.get("evidenceNotes")
        slot.status = "Evidence Uploaded"
    elif action == "acceptEvidence":
        slot.pl_verification_status = "accepted"
        slot.status = "Evidence Accepted"
    elif action == "returnEvidence":
        slot.pl_verification_status = "returned"
        slot.returned_reason = data.get("reason")
        slot.status = "Evidence Returned"
    elif action == "complete":
        # §26 — a core slot can only complete with evidence AND an Activity
        # SF ID on record; IA verification is tracked separately and package
        # verification counts it before final package completion.
        sf_id = (data.get("salesforceId") or slot.salesforce_id or "").strip()
        if not sf_id:
            raise BadRequest(
                "Activity SF ID is required before a core slot can complete."
            )
        if not (slot.evidence_uri or data.get("evidenceUri")):
            raise BadRequest(
                "Evidence must be uploaded before a core slot can complete."
            )
        if data.get("evidenceUri"):
            slot.evidence_uri = data.get("evidenceUri")
        slot.salesforce_id = sf_id
        slot.teachers = data.get("teachers")
        slot.leaders = data.get("leaders")
        slot.participants = data.get("participants")
        slot.status = "Completed"
        slot.completed_at = timezone.now()
    elif action == "plVerify":
        slot.pl_verification_status = "confirmed"
    elif action == "iaVerify":
        slot.ia_verification_status = "confirmed"
    elif action == "return":
        slot.returned_reason = data.get("reason")
        slot.status = "Returned"
    elif action == "accountantConfirm":
        slot.accountant_status = "confirmed"

    slot.save()
    return _serialize_slot(slot)


def resync_plan_completion(plan: CorePlan) -> None:
    """Recompute CorePlan.visits_completed/trainings_completed from the actual
    status of its slots.

    Called from Activity.save() (apps.activities.models) whenever a linked
    CoreActivitySlot's mirrored status changes — that is the real, reachable
    completion path (ia_confirm(), clear_payment(), etc. all route through a
    plain a.save()). slot_action()'s own "complete" branch above is DRF-only
    and unreachable from any template/frontend, so it can never be the
    trigger in practice.

    Recomputes from scratch (rather than incrementing) so this is idempotent
    no matter how many times, or in what order, it gets called.
    """
    visits_completed = plan.slots.filter(
        activity_type="visit", status__in=CORE_SLOT_DONE_STATUSES
    ).count()
    trainings_completed = plan.slots.filter(
        activity_type="training", status__in=CORE_SLOT_DONE_STATUSES
    ).count()
    assessment_completed = plan.slots.filter(
        activity_type="assessment", status__in=CORE_SLOT_DONE_STATUSES
    ).count()
    if (
        plan.visits_completed != visits_completed
        or plan.trainings_completed != trainings_completed
        or plan.assessment_completed != assessment_completed
    ):
        plan.visits_completed = visits_completed
        plan.trainings_completed = trainings_completed
        plan.assessment_completed = assessment_completed
        plan.save(
            update_fields=[
                "visits_completed",
                "trainings_completed",
                "assessment_completed",
                "updated_at",
            ]
        )


def schedule_follow_up(plan_id: str, data: dict, principal) -> dict:
    plan = CorePlan.objects.filter(id=plan_id).first()
    if not plan:
        raise NotFoundError("Plan not found.")
    scheduled_for = data.get("scheduledFor")
    assignee = data.get("assignee")
    if scheduled_for:
        # REG-02 — same calendar gate every other scheduling surface applies.
        resp_user = resolve_scheduling_user(assignee)
        avail = SchedulingPolicyService.check(resp_user, scheduled_for)
        if avail["status"] == "blocked":
            raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))
    plan.follow_up_scheduled_for = scheduled_for
    plan.follow_up_assignee = assignee
    plan.save(update_fields=["follow_up_scheduled_for", "follow_up_assignee"])
    return _serialize_plan(plan)


def upload_follow_up_ssa(plan_id: str, data: dict, principal) -> dict:
    """Upload the follow-up SSA (impact measurement) and check for graduation candidacy."""
    plan = CorePlan.objects.filter(id=plan_id).first()
    if not plan:
        raise NotFoundError("Plan not found.")
    from apps.ssa.services import upload as ssa_upload

    record = ssa_upload(
        {
            "schoolId": plan.school_id,
            "dateOfSsa": data.get("dateOfSsa"),
            "scores": data.get("scores", []),
        },
        principal,
    )
    plan.follow_up_ssa_record_id = record["id"]
    plan.follow_up_average = record["averageScore"]

    baseline = plan.baseline_average or 0.0
    followup = record["averageScore"] or 0.0
    average_change = followup - baseline

    completed_slots_count = plan.slots.filter(
        status__in=CORE_SLOT_DONE_WITH_LEGACY
    ).count()
    slots_complete = completed_slots_count >= EXPECTED_CORE_SLOTS

    is_champion_candidate = followup >= 7.5 and average_change > 0.0 and slots_complete

    if is_champion_candidate:
        plan.status = "Champion Candidate"
        profile = getattr(plan, "profile", None)
        if profile:
            profile.champion_status = "Potential Champion"
            profile.save(update_fields=["champion_status"])
    else:
        plan.status = "Impact Measured"

    plan.save(update_fields=["follow_up_ssa_record_id", "follow_up_average", "status"])

    return {
        "ok": True,
        "planId": plan.id,
        "averageChange": round(average_change, 2),
        "championCandidate": is_champion_candidate,
        "status": plan.status,
    }


def advance_champion(school_id: str, principal) -> dict:
    """Advance a core school to champion (follow-up SSA >= 7.5 + slots complete)."""
    plan = CorePlan.objects.filter(school_id=school_id).first()
    if not plan:
        raise NotFoundError("No core plan.")
    school = School.objects.filter(school_id=school_id).first()
    if school:
        school.school_type = "champion"
        school.save(update_fields=["school_type"])
    profile = getattr(plan, "profile", None)
    if profile:
        profile.champion_status = "Champion"
        profile.save(update_fields=["champion_status"])
    return {"ok": True, "schoolId": school_id, "schoolType": "champion"}


def _serialize_plan(p: CorePlan) -> dict:
    return {
        "id": p.id,
        "schoolId": p.school_id,
        "fy": p.fy,
        "status": p.status,
        "visitsTarget": p.visits_target,
        "trainingsTarget": p.trainings_target,
        "visitsCompleted": p.visits_completed,
        "trainingsCompleted": p.trainings_completed,
        "baselineAverage": p.baseline_average,
        "followUpAverage": p.follow_up_average,
    }


def _serialize_slot(s: CoreActivitySlot) -> dict:
    return {
        "id": s.id,
        "schoolId": s.school_id,
        "intervention": s.intervention,
        "activityType": s.activity_type,
        "sequenceNumber": s.sequence_number,
        "status": s.status,
        "owner": s.owner,
        "assignedStaffId": s.assigned_staff_id,
        "assignedPartnerId": s.assigned_partner_id,
        "scheduledMonth": s.scheduled_month,
        "scheduledWeek": s.scheduled_week,
        "salesforceId": s.salesforce_id,
        "completedAt": s.completed_at.isoformat() if s.completed_at else None,
    }
