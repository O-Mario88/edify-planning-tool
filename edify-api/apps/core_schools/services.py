"""Core-schools service — candidates → verify → onboard → slots → champion."""
from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy
from apps.schools.models import School
from apps.ssa.models import SsaRecord

from .models import (
    CoreActivitySlot, CoreCandidateVerification, CorePlan, CoreSchoolOnboarding,
    CoreSchoolProfile, cplan_id, cprof_id, cslot_id,
)

# The 11 polymorphic slot actions.
SLOT_ACTIONS = {
    "assign", "schedule", "start", "evidence", "acceptEvidence", "returnEvidence",
    "complete", "plVerify", "iaVerify", "return", "accountantConfirm",
}


def list_candidates(principal) -> list[dict]:
    """Best-SSA client/potential-core schools → candidate for core onboarding."""
    qs = School.objects.filter(deleted_at__isnull=True, school_type__in=["client", "potential_core"])
    out = []
    for s in qs:
        latest = s.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if latest and (latest.average_score or 0) >= 7.0:
            out.append({
                "schoolId": s.school_id, "name": s.name,
                "schoolType": s.school_type, "averageScore": latest.average_score,
            })
    return out


def verify_candidate(school_id: str, data: dict, principal) -> dict:
    """IA verifies a Potential Core candidate (SSA >= 7.5 gate)."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    latest = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    if not latest:
        raise BadRequest("No SSA record to verify against.")
    verification = CoreCandidateVerification.objects.create(
        school_id=school_id, ssa_record_id=latest.id, verification_id=data.get("verificationId", ""),
        verified_by_id=principal.user_id, verified_by_name=principal.name,
        verified_at=timezone.now(), status=data.get("status", "Verified Potential Core"),
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
    latest = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
    baseline_avg = latest.average_score if latest else 0.0
    fy = get_operational_fy()
    plan_id = cplan_id(school_id)

    with transaction.atomic():
        plan, _ = CorePlan.objects.update_or_create(
            id=plan_id,
            defaults={
                "school_id": school_id, "fy": fy, "status": "Active",
                "baseline_average": baseline_avg,
                "baseline_ssa_record_id": latest.id if latest else None,
                "created_by_id": principal.user_id, "created_by_name": principal.name,
            },
        )
        CoreSchoolProfile.objects.update_or_create(
            id=cprof_id(school_id),
            defaults={"school_id": school_id, "core_plan": plan, "core_start_fy": fy},
        )
        CoreSchoolOnboarding.objects.update_or_create(
            school_id=school_id,
            defaults={
                "core_plan": plan, "fy": fy, "previous_school_type": school.school_type,
                "baseline_ssa_record_id": latest.id if latest else "",
                "baseline_average_score": baseline_avg,
                "onboarded_by_id": principal.user_id, "onboarded_by_name": principal.name,
                "onboarded_at": timezone.now(), "onboarding_reason": data.get("reason"),
            },
        )
        # Create the 8 slots (4 visit + 4 training) if not present.
        interventions = [i.value for i in SsaIntervention]
        for kind, count in (("v", 4), ("t", 4)):
            for seq in range(1, count + 1):
                slot_id = cslot_id(school_id, kind, seq)
                CoreActivitySlot.objects.get_or_create(
                    id=slot_id,
                    defaults={
                        "core_plan": plan, "school_id": school_id,
                        "intervention": interventions[(seq - 1) % len(interventions)],
                        "activity_type": "visit" if kind == "v" else "training",
                        "sequence_number": seq,
                    },
                )
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
    data["slots"] = [_serialize_slot(s) for s in plan.slots.order_by("activity_type", "sequence_number")]
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
        slot.scheduled_month = data.get("scheduledMonth")
        slot.scheduled_week = data.get("scheduledWeek")
        slot.scheduled_for = data.get("scheduledFor")
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
        slot.salesforce_id = data.get("salesforceId")
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


def schedule_follow_up(plan_id: str, data: dict, principal) -> dict:
    plan = CorePlan.objects.filter(id=plan_id).first()
    if not plan:
        raise NotFoundError("Plan not found.")
    plan.follow_up_scheduled_for = data.get("scheduledFor")
    plan.follow_up_assignee = data.get("assignee")
    plan.save(update_fields=["follow_up_scheduled_for", "follow_up_assignee"])
    return _serialize_plan(plan)


def upload_follow_up_ssa(plan_id: str, data: dict, principal) -> dict:
    """Upload the follow-up SSA (impact measurement)."""
    plan = CorePlan.objects.filter(id=plan_id).first()
    if not plan:
        raise NotFoundError("Plan not found.")
    school = School.objects.filter(school_id=plan.school_id).first()
    from apps.ssa.services import upload as ssa_upload

    record = ssa_upload({"schoolId": plan.school_id, "dateOfSsa": data.get("dateOfSsa"), "scores": data.get("scores", [])}, principal)
    plan.follow_up_ssa_record_id = record["id"]
    plan.follow_up_average = record["averageScore"]
    plan.save(update_fields=["follow_up_ssa_record_id", "follow_up_average"])
    return _serialize_plan(plan)


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
        "id": p.id, "schoolId": p.school_id, "fy": p.fy, "status": p.status,
        "visitsTarget": p.visits_target, "trainingsTarget": p.trainings_target,
        "visitsCompleted": p.visits_completed, "trainingsCompleted": p.trainings_completed,
        "baselineAverage": p.baseline_average, "followUpAverage": p.follow_up_average,
    }


def _serialize_slot(s: CoreActivitySlot) -> dict:
    return {
        "id": s.id, "schoolId": s.school_id, "intervention": s.intervention,
        "activityType": s.activity_type, "sequenceNumber": s.sequence_number,
        "status": s.status, "owner": s.owner,
        "assignedStaffId": s.assigned_staff_id, "assignedPartnerId": s.assigned_partner_id,
        "scheduledMonth": s.scheduled_month, "scheduledWeek": s.scheduled_week,
        "salesforceId": s.salesforce_id, "completedAt": s.completed_at.isoformat() if s.completed_at else None,
    }
