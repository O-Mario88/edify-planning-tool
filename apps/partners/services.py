"""Partners service — directory + self-service + eligibility."""

from __future__ import annotations


from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.scoping import resolve_partner_ids

from .models import Partner


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
    """Partners eligible for a district + expertise."""
    qs = Partner.objects.filter(deleted_at__isnull=True, active_status=True)
    district = query.get("districtName")
    if district:
        qs = qs.filter(coverage_districts__contains=[district])
    expertise = query.get("expertise")
    if expertise:
        qs = qs.filter(expertise_areas__contains=[expertise])
    return [_serialize(p) for p in qs.order_by("name")]


def onboard(data: dict, principal) -> dict:
    """Onboards a new partner. Restricted to Admin, CD, or IA."""
    from apps.core.rbac import EdifyRole
    from apps.core.exceptions import Forbidden

    allowed = {
        EdifyRole.ADMIN.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
    }
    user_roles = getattr(principal, "roles", []) or []
    active_role = getattr(principal, "active_role", None)
    if active_role and active_role not in user_roles:
        user_roles = list(user_roles) + [active_role]

    if not any(r in allowed for r in user_roles):
        raise Forbidden(
            "Only Admin, Country Director, or Impact Assessment users can onboard partners."
        )

    if not data.get("name"):
        raise BadRequest("name is required.")
    from django.utils import timezone

    p = Partner.objects.create(
        name=data["name"],
        region_name=data.get("regionName"),
        trains_on=data.get("trainsOn", []),
        notes=data.get("notes"),
        contact_person=data.get("contactPerson"),
        email=data.get("email"),
        phone=data.get("phone"),
        coverage_districts=data.get("coverageDistricts", []),
        contract_status=data.get("contractStatus", "pending"),
        is_certified=bool(data.get("isCertified")),
        certification_status=data.get("certificationStatus"),
        expertise_areas=data.get("expertiseAreas", []),
        onboarded_by_user_id=principal.user_id,
        onboarded_at=timezone.now(),
    )
    return _serialize(p)


def update(partner_id: str, data: dict, principal) -> dict:
    p = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Partner not found.")
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
