"""Partners service — directory + self-service + eligibility."""

from __future__ import annotations


from django.db import transaction
from django.db.models import Q

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.scoping import resolve_partner_ids, resolve_user_scope

from .models import Partner


# Core package slot types are governed by the nine-slot CorePlan (a partner
# may legitimately hold several slots for one school) — the default
# one-activity allowance applies to non-core partner work only.
_CORE_EXEMPT_TYPES = {
    "core_visit",
    "core_training",
    "core_assessment_visit",
}


def _assert_partner_directory_manager(principal) -> None:
    """Partner-directory membership is a people-administration decision.

    The Users page is shared with HR, but the business rule for partner
    organisations is deliberately narrower: only the active Admin or Country
    Director role may add or remove them. Keeping this guard in the canonical
    service protects the HTML page and the API equally.
    """
    from apps.core.navigation import get_user_role_slug

    if getattr(principal, "is_superuser", False):
        return
    if get_user_role_slug(principal) not in {"ADMIN", "CD"}:
        raise Forbidden(
            "Only an Admin or Country Director can manage partner organisations."
        )


def assert_partner_activity_allowance(
    partner_id: str, school_id: str, activity_type: str, fy: str
) -> None:
    """Enforce the default partner activity allowance (§F): one non-core
    activity per partner per school per FY; more requires an auditable
    PartnerActivityAllowance grant."""
    if not partner_id or not school_id or activity_type in _CORE_EXEMPT_TYPES:
        return
    from django.utils import timezone

    from apps.activities.models import Activity

    from .models import PartnerActivityAllowance

    used = (
        Activity.objects.filter(
            assigned_partner_id=partner_id,
            school_id=school_id,
            fy=fy,
            delivery_type="partner",
            deleted_at__isnull=True,
        )
        .exclude(status__in=["cancelled", "rejected"])
        .exclude(activity_type__in=_CORE_EXEMPT_TYPES)
        .count()
    )
    grants = PartnerActivityAllowance.objects.filter(
        partner_id=partner_id, school_id=school_id, fy=fy
    )
    extra = 0
    today = timezone.now().date()
    for grant in grants:
        if grant.expires_at and grant.expires_at < today:
            continue
        if grant.activity_type and grant.activity_type != activity_type:
            continue
        extra += grant.additional_activities
    if used >= 1 + extra:
        raise BadRequest(
            "Partner activity allowance reached for this school this FY "
            f"({used} used, {1 + extra} allowed). Grant an additional "
            "allowance (with a reason) to schedule more partner work here."
        )


def _serialize(p: Partner) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "regionName": p.region_name,
        "trainsOn": p.trains_on,
        "notes": p.notes,
        "contactPerson": p.contact_person,
        "email": p.email,
        "phone": p.phone,
        "coverageDistricts": p.coverage_districts,
        "contractStatus": p.contract_status,
        "isCertified": p.is_certified,
        "certificationStatus": p.certification_status,
        "expertiseAreas": p.expertise_areas,
        "ssaIntervention": p.ssa_intervention,
        "ssaInterventionLabel": p.ssa_intervention_label,
        "activeStatus": p.active_status,
    }


def list_partners(principal, query: dict) -> list[dict]:
    qs = Partner.objects.filter(deleted_at__isnull=True)
    if str(query.get("activeOnly", "")).lower() == "true":
        qs = qs.filter(active_status=True)
    return [_serialize(p) for p in qs.order_by("name")]


def my_partner(principal) -> dict:
    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        raise NotFoundError("No partner linked to your account.")
    p = Partner.objects.filter(id=partner_ids[0], deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Partner not found.")
    return _serialize(p)


def my_activities(principal) -> list[dict]:
    """The partner's work queue — only activities where the partner still has a
    pending action (assigned, scheduled, or mid-completion). Once the activity is
    submitted for PL/IA review or reaches a terminal state it leaves the partner's
    queue: their part is done and the handoff has moved on."""
    from apps.activities.models import Activity
    from apps.activities.services import _serialize as serialize_activity

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        return []
    qs = Activity.objects.filter(
        assigned_partner_id__in=partner_ids, deleted_at__isnull=True
    ).exclude(
        status__in=[
            # Terminal states.
            "completed",
            "cancelled",
            "rejected",
            "deferred",
            # Handed off past the partner — PL review / IA verification / payment.
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
        ]
    )
    return [serialize_activity(a) for a in qs.select_related("school")]


def schedule_activity(activity_id: str, data: dict, principal) -> dict:
    """Partner self-schedules an assigned activity."""
    from apps.activities.services import partner_schedule

    return partner_schedule(activity_id, data, principal)


def eligible(query: dict) -> list[dict]:
    """Partners eligible for a district + expertise, and able to take new work.

    Held partners are excluded here too — the API is a second door to the same
    choice, and a rule enforced only in the HTML picker is not a rule.
    """
    qs = assignable_partners()
    district = query.get("districtName")
    if district:
        qs = qs.filter(coverage_districts__contains=[district])
    expertise = query.get("expertise")
    if expertise:
        qs = qs.filter(expertise_areas__contains=[expertise])
    return [_serialize(p) for p in qs.order_by("name")]


@transaction.atomic
def onboard(data: dict, principal) -> dict:
    """Onboard a partner organisation from the CD/Admin Users workspace."""
    _assert_partner_directory_manager(principal)
    from django.utils import timezone

    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("Partner organisation name is required.")
    if Partner.objects.filter(name__iexact=name).exists():
        raise ConflictError(f"A partner organisation named '{name}' already exists.")

    email = (data.get("email") or "").strip().lower()
    partner_user = None
    if email:
        from apps.accounts.models import User
        from apps.core.rbac import EdifyRole

        partner_user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if not partner_user:
            partner_user = User.objects.create(
                email=email,
                name=name,
                roles=[EdifyRole.PARTNER_ADMIN.value],
                active_role=EdifyRole.PARTNER_ADMIN.value,
                is_active=True,
            )

    p = Partner.objects.create(
        name=name,
        region_name=data.get("regionName") or data.get("region_name"),
        trains_on=data.get("trainsOn", []),
        notes=data.get("notes"),
        contact_person=data.get("contactPerson") or data.get("contact_person"),
        email=email,
        phone=data.get("phone"),
        ssa_intervention=data.get("ssaIntervention") or data.get("ssa_intervention"),
        coverage_districts=data.get("coverageDistricts", []),
        contract_status=data.get("contractStatus", "pending"),
        is_certified=bool(data.get("isCertified")),
        certification_status=data.get("certificationStatus"),
        expertise_areas=data.get("expertiseAreas", []),
        user=partner_user,
        onboarded_by_user_id=getattr(
            principal, "user_id", str(getattr(principal, "id", ""))
        ),
        onboarded_at=timezone.now(),
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.created",
        subject_kind="partner",
        subject_id=p.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"name": p.name, "email": p.email, "region": p.region_name},
    )
    return _serialize(p)


@transaction.atomic
def delete_partner(partner_id: str, principal) -> dict:
    """Soft-delete a partner while preserving assignments and audit history."""
    _assert_partner_directory_manager(principal)
    partner = Partner.objects.select_related("user").filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")

    snapshot = {
        "id": partner.id,
        "name": partner.name,
        "email": partner.email,
        "linkedUserId": partner.user_id,
    }
    partner.active_status = False
    partner.save(update_fields=["active_status", "updated_at"])
    partner.soft_delete()

    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.deleted",
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload=snapshot,
    )
    return {**snapshot, "deleted": True}


def update(partner_id: str, data: dict, principal) -> dict:
    p = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Partner not found.")
    # PARTNER_MANAGE alone isn't ownership — mirrors the scope check every
    # other domain service applies before mutation (e.g. clusters._scope_filter
    # gating writes by district_ids). Country-scoped roles (Admin, CD) manage
    # every partner by design; any role holding PARTNER_MANAGE without country
    # scope is restricted to the partner(s) actually in their resolved scope.
    scope = resolve_user_scope(principal)
    if not scope.country_scope and p.id not in scope.partner_ids:
        raise Forbidden("You may only update a partner within your scope.")
    for field_name in (
        "name",
        "region_name",
        "notes",
        "contact_person",
        "email",
        "phone",
        "contract_status",
        "certification_status",
    ):
        camel = _camel(field_name)
        if camel in data:
            setattr(p, field_name, data[camel])
    for arr_field in ("trains_on", "coverage_districts", "expertise_areas"):
        camel = _camel(arr_field)
        if camel in data:
            setattr(p, arr_field, data[camel])
    if "isCertified" in data:
        p.is_certified = bool(data["isCertified"])
    if "activeStatus" in data:
        p.active_status = bool(data["activeStatus"])
    p.save()
    return _serialize(p)


_CAMEL_MAP = {
    "region_name": "regionName",
    "contact_person": "contactPerson",
    "coverage_districts": "coverageDistricts",
    "contract_status": "contractStatus",
    "certification_status": "certificationStatus",
    "expertise_areas": "expertiseAreas",
    "trains_on": "trainsOn",
}


def _camel(snake: str) -> str:
    return _CAMEL_MAP.get(snake, snake)


__all__ = [
    "list_partners",
    "my_partner",
    "my_activities",
    "schedule_activity",
    "eligible",
    "onboard",
    "update",
]


def mark_assignment_scheduled(assignment, *, scheduled_date, activity):
    """Move a PartnerAssignment from pending to scheduled, once its Activity exists.

    Both planning views -- the single handoff and the bulk one -- wrote this
    three-line transition inline and identically. Keeping it here means the
    assignment lifecycle has one owner: a handoff that stays stuck at
    `pending_scheduling` after its Activity was created is a real defect people
    have hit, and it is easier to see and to fix in one function than in two
    copies inside unrelated view bodies.

    `activity` is required, not optional. A scheduled assignment whose activity
    is not recorded is exactly the row planning oversight cannot resolve: it has
    to decide whether the assignment and some activity are one item or two, and
    without the id it is guessing. Making the argument mandatory means a future
    caller cannot create that row by omission.

    Idempotent: re-running it on an already-scheduled assignment rewrites the
    same values rather than raising, so a retried HTMX POST is harmless.
    """
    assignment.status = "partner_scheduled"
    assignment.scheduled_date = scheduled_date
    assignment.scheduled_activity = activity
    assignment.save(
        update_fields=[
            "status",
            "scheduled_date",
            "scheduled_activity",
            "updated_at",
        ]
    )
    return assignment


# ── Returning an assignment to staff ─────────────────────────────────────────
# Minimum is long enough to rule out "no" and "busy"; maximum is short enough
# that the field stays a sentence rather than becoming a report. Staff need
# enough to choose the next action, not a narrative.
RETURN_REASON_MIN_LENGTH = 10
RETURN_REASON_MAX_LENGTH = 300


def return_assignment(assignment_id: str, data: dict, principal) -> dict:
    """Partner hands an unscheduled assignment back to the managing staff.

    Return exists only before scheduling. Once a partner has scheduled, the
    assignment has an Activity, a catalogue-snapshotted cost and a place in the
    week/month/quarter/FY budget, and unpicking that silently is what
    rescheduling, release and cancellation are for. So this refuses rather than
    reaching into finance.

    Idempotent: returning an already-returned assignment is a no-op that
    reports success. A partner double-tapping on a slow connection should not
    get an error for something that already happened, and a second audit row
    would misrepresent one decision as two.
    """
    from django.utils import timezone

    from apps.audit.services import log as audit_log
    from apps.partners.models import PartnerAssignment, PartnerReturnReason

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        raise Forbidden("Only a partner user may return an assignment.")

    category = ((data or {}).get("reason_category") or "").strip()
    reason = ((data or {}).get("reason") or "").strip()

    valid_categories = {c.value for c in PartnerReturnReason}
    if category not in valid_categories:
        raise BadRequest("Choose a reason category.")
    # Length is measured on the stripped value, so whitespace padding cannot
    # buy the minimum.
    if len(reason) < RETURN_REASON_MIN_LENGTH:
        raise BadRequest(
            f"Explain briefly why you cannot take this assignment "
            f"(at least {RETURN_REASON_MIN_LENGTH} characters)."
        )
    if len(reason) > RETURN_REASON_MAX_LENGTH:
        raise BadRequest(
            f"Keep the explanation under {RETURN_REASON_MAX_LENGTH} characters."
        )

    with transaction.atomic():
        # Locked because the staff side can withdraw or reassign the same row,
        # and a partner page open in another tab can be stale.
        assignment = (
            PartnerAssignment.objects.select_for_update()
            .filter(id=assignment_id, partner_id__in=partner_ids)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Assignment not found.")

        if assignment.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
            return _serialize_assignment(assignment)

        if assignment.status not in PartnerAssignment.UNSCHEDULED_STATUSES:
            raise ConflictError(
                "This assignment has already been scheduled. Use Reschedule or "
                "request release instead of returning it."
            )

        assignment.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        assignment.return_reason_category = category
        assignment.return_reason = reason
        assignment.returned_at = timezone.now()
        assignment.returned_by = getattr(principal, "user_id", None) or getattr(
            principal, "id", None
        )
        assignment.save(
            update_fields=[
                "status",
                "return_reason_category",
                "return_reason",
                "returned_at",
                "returned_by",
                "updated_at",
            ]
        )

    audit_log(
        action="partner.assignment_returned",
        subject_kind="PartnerAssignment",
        subject_id=assignment.id,
        actor_id=assignment.returned_by or "unknown",
        actor_role=getattr(principal, "active_role", "") or "",
        success=True,
        payload={
            "partner_id": assignment.partner_id,
            "school_id": assignment.school_id,
            "cluster_id": assignment.cluster_id,
            "reason_category": category,
            "reason": reason,
        },
    )
    # After commit, so a notification never announces a return that rolled back.
    _notify_assignment_returned(assignment, principal, category, reason)
    return _serialize_assignment(assignment)


def _serialize_assignment(assignment) -> dict:
    return {
        "id": assignment.id,
        "status": assignment.status,
        "schoolId": assignment.school_id,
        "clusterId": assignment.cluster_id,
        "partnerId": assignment.partner_id,
        "returnReasonCategory": assignment.return_reason_category,
        "returnReason": assignment.return_reason,
        "returnedAt": (
            assignment.returned_at.isoformat() if assignment.returned_at else None
        ),
        "returnedBy": assignment.returned_by,
    }


def _notify_assignment_returned(assignment, principal, category, reason) -> None:
    """Tell the managing staff, with the reason, and close the partner's To-Do.

    Bookkeeping must not break the return itself: the assignment is already
    committed by the time this runs, and a notification backend being down is
    not a reason to tell the partner their return failed.
    """
    import logging

    from apps.partners.models import PartnerReturnReason

    logger = logging.getLogger(__name__)
    try:
        from apps.notifications.services import WorkflowNotificationService

        staff_id = assignment.assigning_staff_id
        if not staff_id:
            return
        label = dict(PartnerReturnReason.choices).get(category, category)
        where = getattr(assignment.school, "name", None) or getattr(
            assignment.cluster, "name", "an assignment"
        )
        WorkflowNotificationService.trigger(
            event_type="partner_assignment_returned",
            category="partner",
            # High: this is work that will not happen unless the staff member
            # acts, and the schedule-by date keeps running while it waits.
            priority="high",
            title="A partner returned an assignment",
            body=(
                f"{getattr(principal, 'name', 'A partner')} returned "
                f"{where} — {label}. {reason}"
            ),
            context_type="partner_assignment",
            context_id=assignment.id,
            recipients=[staff_id],
        )
    except Exception:  # pragma: no cover — bookkeeping must not break the flow
        logger.warning("partner.assignment_returned notification failed", exc_info=True)


def assignable_partners():
    """Partners who may receive NEW work right now.

    The one place that question is answered, because six views built the
    picker independently and a held partner was still offered by all of them —
    the assignment failed at save with a conflict, after the person had chosen
    a school, an activity and a reason. Offering a choice the system will
    refuse is a worse experience than not offering it, and it teaches people
    that the error is arbitrary.

    Excludes held partners. Does NOT exclude partners with withdrawn history:
    a partner who lost one assignment to a closed school is not disqualified
    from the next one, and quietly hiding them would be a performance
    judgement made by a query.
    """
    from apps.partners.withdrawal_models import PartnerHold

    held = PartnerHold.objects.filter(lifted_at__isnull=True).values_list(
        "partner_id", flat=True
    )
    return (
        Partner.objects.filter(deleted_at__isnull=True, active_status=True)
        .exclude(id__in=held)
        .order_by("name")
    )


#: Certification states that permit new bookings. A blank value is the
#: historic shape for a partner flagged certified before the status column
#: existed, and is treated as certified rather than as a refusal.
BOOKABLE_CERTIFICATION_STATES = {"", "certified", "active"}


def bookable_certified_agencies(*, activity_type: str = "", district_name: str = ""):
    """Certified agencies Edify staff may book onto a date right now (§16).

    Certified-agency booking is a stronger act than assignment: staff choose
    the date, the Activity is scheduled immediately, budget moves, and the
    booking lands in the agency's My Plan as work they are expected to
    prepare for. So the picker offers only agencies that will actually pass
    the booking transaction — every condition here is re-checked at write
    time, and offering a choice the system will refuse teaches people that
    the error is arbitrary.

    Ordinary uncertified partners are never included. They receive work
    through assignment and choose their own dates.
    """
    qs = assignable_partners().filter(is_certified=True)
    qs = qs.filter(
        Q(certification_status__isnull=True)
        | Q(certification_status__in=BOOKABLE_CERTIFICATION_STATES)
    )
    if district_name:
        # An empty coverage list means "not yet scoped", which the directory
        # treats as unrestricted everywhere else; narrowing it here only would
        # hide agencies the assignment picker offers.
        qs = qs.filter(
            Q(coverage_districts__len=0) | Q(coverage_districts__contains=[district_name])
        )
    if activity_type:
        qs = qs.filter(
            Q(trains_on__len=0) | Q(trains_on__contains=[activity_type])
        )
    return qs
