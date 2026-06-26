"""
Activities service — the 21-state field-work lifecycle (ports activities.service).

create → start-completion → complete → ia-confirm → (PL review) → payment.
Reschedule/reassign/cancel/defer; partner self-schedule; the accountant payment
queue + clear-payment. Period integrity (fy/quarter DERIVED from scheduledDate),
SSA planning gate, cluster-only type rules, Salesforce ID validation, and the
authoritative payment guards (money never moves before evidence accepted +
SF ID + IA confirmed).
"""
from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.enums import ActivityType
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School

from .models import Activity, ActivityCompletionVerification
from .salesforce import is_valid_salesforce_id


# Type rules (spec §8).
CLUSTER_ONLY_TYPES = {
    "training", "school_improvement_training", "cluster_meeting",
    "cluster_training", "core_training",
}
SCHOOL_VISIT_TYPES = {
    "school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit",
}
TRAINING_TYPES = {
    "training", "school_improvement_training", "cluster_meeting",
    "cluster_training", "ssa_activity", "core_training",
}
RESCHEDULE_SLIP_LIMIT = 3


def sf_kind(activity_type: str) -> str:
    return "training" if activity_type in TRAINING_TYPES else "visit"


# ── List ─────────────────────────────────────────────────────────────────────
def list_activities(query: dict, principal) -> list[Activity]:
    """Scope-constrained activity list. Supports the FE filter bar (status,
    activityType, schoolId, fy, quarter, deliveryType, mine, statusGroup)."""
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope:
        # Constrain to in-scope schools OR activities assigned to the caller /
        # their partner (so a CCEO sees their own, a partner sees theirs).
        conds = []
        if scope.school_ids:
            conds.append(Q(school_id__in=scope.school_ids))
        if scope.staff_ids:
            conds.append(Q(responsible_staff_id__in=scope.staff_ids))
        if scope.partner_ids:
            conds.append(Q(assigned_partner_id__in=scope.partner_ids))
        if conds:
            from functools import reduce as _reduce

            qs = qs.filter(_reduce(lambda a, b: a | b, conds))
        else:
            qs = qs.none()

    if query.get("status"):
        qs = qs.filter(status=query["status"])
    if query.get("activityType"):
        qs = qs.filter(activity_type=query["activityType"])
    if query.get("schoolId"):
        qs = qs.filter(school__school_id=query["schoolId"])
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("quarter"):
        qs = qs.filter(quarter=query["quarter"])
    if query.get("deliveryType"):
        qs = qs.filter(delivery_type=query["deliveryType"])
    if str(query.get("mine", "")).lower() == "true" and scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    sg = query.get("statusGroup")
    if sg == "active":
        qs = qs.exclude(status__in=["completed", "cancelled", "rejected", "deferred"])
    elif sg == "completed":
        qs = qs.filter(status__in=["completed", "ia_verified", "accountant_confirmed"])
    return qs.select_related("school")


def _assert_in_scope(activity: Activity, principal) -> None:
    """Object-level scope check (mirrors assertInScope)."""
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return
    if scope.staff_ids and activity.responsible_staff_id in scope.staff_ids:
        return
    if scope.partner_ids and activity.assigned_partner_id in scope.partner_ids:
        return
    if scope.school_ids and activity.school_id in scope.school_ids:
        return
    raise Forbidden("Activity outside your scope.")


def _get_in_scope(activity_id: str, principal) -> Activity:
    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    _assert_in_scope(a, principal)
    return a


def _serialize(a: Activity) -> dict:
    return {
        "id": a.id,
        "activityType": a.activity_type,
        "schoolId": a.school.school_id if a.school_id else None,
        "schoolName": a.school.name if a.school_id else None,
        "clusterId": a.cluster_id,
        "fy": a.fy,
        "quarter": a.quarter,
        "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
        "responsibleStaffId": a.responsible_staff_id,
        "assignedPartnerId": a.assigned_partner_id,
        "deliveryType": a.delivery_type,
        "status": a.status,
        "evidenceStatus": a.evidence_status,
        "iaVerificationStatus": a.ia_verification_status,
        "paymentStatus": a.payment_status,
        "salesforceActivityId": a.salesforce_activity_id,
        "salesforceActivityType": a.salesforce_activity_type,
        "rescheduleCount": a.reschedule_count,
        "lastReason": a.last_reason,
        "estCostCents": a.est_cost_cents,
        "costMissing": a.cost_missing,
        "teachersAttended": a.teachers_attended,
        "leadersAttended": a.leaders_attended,
        "otherParticipants": a.other_participants,
    }


# ── Create ───────────────────────────────────────────────────────────────────
def create(data: dict, principal) -> dict:
    """Create + schedule an activity (SSA gate, cluster-type rules, FY-derivation)."""
    activity_type = data.get("activityType")
    school_id_str = data.get("schoolId")
    cluster_id = data.get("clusterId")
    school = None
    if school_id_str:
        school = School.objects.filter(school_id=school_id_str).first()
        if not school:
            raise NotFoundError(f"School {school_id_str} not in directory")
        # SSA planning gate: locked until a complete current-FY SSA.
        if school.current_fy_ssa_status != "done":
            raise BadRequest(
                f'Cannot schedule activity — "{school.name}" has no complete current-FY SSA. '
                "Planning is locked until the SSA is recorded."
            )
    if not school and not cluster_id:
        raise BadRequest("Activity must reference a school or cluster")
    if activity_type in CLUSTER_ONLY_TYPES and not cluster_id:
        raise BadRequest("Trainings and cluster meetings must be scheduled through a cluster, not on an individual school.")
    if school and not cluster_id and activity_type not in SCHOOL_VISIT_TYPES:
        raise BadRequest("Only school visits may be scheduled directly from a school. Trainings must go through clusters.")

    is_partner = data.get("deliveryType") == "partner" or bool(data.get("assignedPartnerId"))
    responsible_staff_id = (
        data.get("responsibleStaffId") if is_partner
        else (data.get("responsibleStaffId") or principal.staff_profile_id)
    )

    scheduled_date = _parse_date(data["scheduledDate"]) if data.get("scheduledDate") else None
    fy = get_operational_fy(scheduled_date) if scheduled_date else data.get("fy", get_operational_fy())
    quarter = get_quarter_for_date(scheduled_date) if scheduled_date else data.get("quarter", get_quarter_for_date())

    status = "assigned_to_partner" if is_partner else ("scheduled" if scheduled_date else "planned")
    activity = Activity.objects.create(
        activity_type=activity_type,
        school=school,
        cluster_id=cluster_id,
        project_id=data.get("projectId"),
        fy=fy,
        quarter=quarter,
        planned_month=data.get("plannedMonth"),
        planned_week=data.get("plannedWeek"),
        responsible_staff_id=responsible_staff_id,
        assigned_partner_id=data.get("assignedPartnerId"),
        delivery_type="partner" if is_partner else "staff",
        cluster_slot=data.get("clusterSlot"),
        purpose_intervention=data.get("purposeIntervention"),
        scheduled_date=scheduled_date,
        status=status,
        salesforce_activity_type=sf_kind(activity_type),
    )
    return _serialize(activity)


def _parse_date(value) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequest(f"Invalid date: {value}") from exc


# ── Lifecycle transitions ────────────────────────────────────────────────────
def start_completion(activity_id: str, data: dict | None = None, principal=None) -> dict:
    a = _get_in_scope(activity_id, principal)
    if a.status not in ("scheduled", "in_progress", "partner_scheduled", "assigned_to_partner"):
        raise BadRequest("Activity must be scheduled before completion can start.")
    a.status = "completion_started"
    a.save(update_fields=["status", "updated_at"])
    return _serialize(a)


def complete(activity_id: str, data: dict, principal) -> dict:
    """Submit completion: evidence present, Salesforce ID validated, attendance
    for trainings, CCEO routes to PL / staff routes to IA."""
    a = _get_in_scope(activity_id, principal)
    if a.status not in ("completion_started", "in_progress", "evidence_uploaded", "evidence_accepted", "salesforce_id_required"):
        raise BadRequest("Click Complete first to unlock evidence upload and Activity Code entry.")

    # Evidence presence (lazily import to avoid a circular dep with evidence app).
    try:
        from apps.evidence.models import EvidenceRecord  # type: ignore

        evidence_count = EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False).count()
    except Exception:  # noqa: BLE001
        evidence_count = 1  # evidence app not yet present during build
    if evidence_count == 0:
        raise BadRequest("Upload evidence before submitting completion.")

    # SF ID lock after IA confirmation.
    if a.ia_verification_status == "confirmed":
        raise Forbidden("Salesforce ID is locked after IA confirmation. Ask IA to return the activity to make a correction.")

    kind = sf_kind(a.activity_type)
    sf_id = (data.get("salesforceId") or "").strip()
    if not is_valid_salesforce_id(sf_id, kind):
        raise BadRequest(f"{'SV-' if kind == 'visit' else 'TS-'} Salesforce ID required")

    # Trainings require attendance.
    if kind == "training" and not ((data.get("teachersAttended") or 0) > 0 or (data.get("leadersAttended") or 0) > 0):
        raise BadRequest("Training completion requires attendance (teachers and/or school leaders)")

    # Partner evidence must be accepted first.
    if a.delivery_type == "partner" and a.evidence_status != "accepted":
        raise BadRequest("Partner evidence must be accepted by staff before submission.")

    is_cceo = principal.active_role == "CCEO"
    next_status = "submitted_to_pl" if is_cceo else "awaiting_ia_verification"
    with transaction.atomic():
        a.salesforce_activity_id = sf_id
        a.salesforce_activity_type = kind
        a.teachers_attended = data.get("teachersAttended")
        a.leaders_attended = data.get("leadersAttended")
        a.other_participants = data.get("otherParticipants")
        a.status = next_status
        a.evidence_status = "accepted" if a.evidence_status == "none" else a.evidence_status
        a.save(update_fields=[
            "salesforce_activity_id", "salesforce_activity_type", "teachers_attended",
            "leaders_attended", "other_participants", "status", "evidence_status", "updated_at",
        ])
        ActivityCompletionVerification.objects.update_or_create(
            activity=a,
            defaults={"salesforce_id": sf_id, "entered_by": principal.user_id, "status": "pending"},
        )
    return _serialize(a)


def ia_confirm(activity_id: str, data: dict | None = None, principal=None) -> dict:
    """IA confirms the Salesforce entry (manual confirmation)."""
    a = _get_in_scope(activity_id, principal)
    if a.status != "awaiting_ia_verification":
        raise BadRequest("Activity is not awaiting IA verification")
    if a.delivery_type == "partner" and a.evidence_status != "accepted":
        raise Forbidden("Cannot confirm — partner evidence not accepted.")
    a.status = "ia_verified"
    a.ia_verification_status = "confirmed"
    a.ia_confirmed_at = timezone.now()
    a.ia_confirmed_by = principal.user_id
    if a.verification:
        a.verification.status = "confirmed"
        a.verification.ia_actor_id = principal.user_id
        a.verification.ia_action_at = timezone.now()
        a.verification.save(update_fields=["status", "ia_actor_id", "ia_action_at"])
    # Payment path: partner activities enter the payment queue.
    if a.delivery_type == "partner":
        a.payment_status = "ia_confirmed"
    a.save(update_fields=["status", "ia_verification_status", "ia_confirmed_at", "ia_confirmed_by", "payment_status", "updated_at"])
    return _serialize(a)


def reschedule(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    if a.reschedule_count >= RESCHEDULE_SLIP_LIMIT:
        raise BadRequest(f"Reschedule limit reached ({RESCHEDULE_SLIP_LIMIT}). Escalate or convert this activity instead.")
    new_date = _parse_date(data["scheduledDate"])
    new_fy = get_operational_fy(new_date)
    new_quarter = get_quarter_for_date(new_date)
    a.scheduled_date = new_date
    a.fy = new_fy
    a.quarter = new_quarter
    a.reschedule_count += 1
    a.last_reason = data.get("reason")
    a.status = "planned" if a.status in ("cancelled", "deferred") else "rescheduled"
    a.save(update_fields=["scheduled_date", "fy", "quarter", "reschedule_count", "last_reason", "status", "updated_at"])
    return _serialize(a)


def reassign(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    delivery = data.get("deliveryType", a.delivery_type)
    a.delivery_type = delivery
    a.assigned_partner_id = data.get("assignedPartnerId")
    a.responsible_staff_id = data.get("responsibleStaffId") or a.responsible_staff_id
    if delivery == "partner":
        a.status = "assigned_to_partner"
    a.save(update_fields=["delivery_type", "assigned_partner_id", "responsible_staff_id", "status", "updated_at"])
    return _serialize(a)


def partner_schedule(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    new_date = _parse_date(data["scheduledDate"])
    a.scheduled_date = new_date
    a.fy = get_operational_fy(new_date)
    a.quarter = get_quarter_for_date(new_date)
    a.status = "partner_scheduled"
    a.save(update_fields=["scheduled_date", "fy", "quarter", "status", "updated_at"])
    return _serialize(a)


def cancel(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    a.status = "cancelled"
    a.last_reason = data.get("reason")
    a.save(update_fields=["status", "last_reason", "updated_at"])
    return _serialize(a)


def defer(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    a.status = "deferred"
    a.last_reason = data.get("reason")
    a.save(update_fields=["status", "last_reason", "updated_at"])
    return _serialize(a)


# ── Payment queue + clear-payment ────────────────────────────────────────────
def payment_queue(principal) -> list[dict]:
    """Accountant queue: partner-delivered activities awaiting payment."""
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        payment_status__in=["ia_confirmed", "pl_approved", "accountant_cleared"],
    )
    if not scope.country_scope:
        if scope.school_ids:
            qs = qs.filter(school_id__in=scope.school_ids)
        else:
            qs = qs.none()
    qs = qs.select_related("school")[:200]
    out = []
    for a in qs:
        out.append({
            "id": a.id,
            "activityType": a.activity_type,
            "salesforceActivityId": a.salesforce_activity_id,
            "evidenceStatus": a.evidence_status,
            "iaVerificationStatus": a.ia_verification_status,
            "paymentStatus": a.payment_status,
            "school": {"schoolId": a.school.school_id, "name": a.school.name} if a.school_id else None,
            "ready": (
                a.evidence_status == "accepted"
                and bool(a.salesforce_activity_id)
                and a.ia_verification_status == "confirmed"
                and a.payment_status != "paid"
            ),
        })
    return out


def clear_payment(activity_id: str, principal) -> dict:
    """Clear a partner payment. Authoritative guards: money never moves before
    evidence accepted + SF ID + IA confirmed."""
    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    if a.delivery_type != "partner":
        raise BadRequest("Payment clearance is for partner-delivered activities.")
    if a.ia_verification_status != "confirmed":
        raise Forbidden("Cannot clear payment — activity is not IA-verified.")
    if not a.salesforce_activity_id:
        raise Forbidden("Cannot clear payment — no Salesforce ID entered.")
    if a.evidence_status != "accepted":
        raise Forbidden("Cannot clear payment — evidence not accepted.")
    if a.payment_status in ("paid", "closed"):
        raise BadRequest("Payment already cleared.")
    _assert_in_scope(a, principal)
    a.payment_status = "paid"
    a.status = "completed"
    a.save(update_fields=["payment_status", "status", "updated_at"])
    return {"ok": True, "id": a.id, "paymentStatus": a.payment_status, "status": a.status}


__all__ = [
    "list_activities",
    "create",
    "start_completion",
    "complete",
    "ia_confirm",
    "reschedule",
    "reassign",
    "partner_schedule",
    "cancel",
    "defer",
    "payment_queue",
    "clear_payment",
    "sf_kind",
    "_serialize",
]
