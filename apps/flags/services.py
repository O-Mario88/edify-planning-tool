"""Flags service — CD→PL flag handoff (CD raises; assigned PL acts)."""

from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import CdFlag


def raise_flag(data: dict, principal) -> dict:
    # Only the CD raises flags.
    if principal.active_role not in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    ):
        raise BadRequest("Only the Country Director may raise flags.")
    assigned_to = data.get("assignedToUserId")
    if not assigned_to:
        raise BadRequest("assignedToUserId is required.")
    flag = CdFlag.objects.create(
        raised_by_user_id=principal.user_id,
        raised_by_name=principal.name,
        assigned_to_user_id=assigned_to,
        category=data.get("category", "general"),
        scope_type=data.get("scopeType"),
        scope_id=data.get("scopeId"),
        scope_name=data.get("scopeName"),
        note=data.get("note", ""),
        recommended_action=data.get("recommendedAction"),
        priority=data.get("priority", "normal"),
        due_date=data.get("dueDate"),
    )
    return _serialize(flag)


def program_leads(principal) -> list[dict]:
    """List Program Leads (the assignable actors for a CD flag)."""
    users = User.objects.filter(deleted_at__isnull=True, status="active")
    pls = [u for u in users if EdifyRole.COUNTRY_PROGRAM_LEAD.value in (u.roles or [])]
    return [{"id": u.id, "name": u.name, "email": u.email} for u in pls]


# Roles allowed to read the whole flag board rather than just their own rows.
# IA/Admin keep global read-only monitoring; the CD sees what they raised and
# the PL sees what was assigned to them (both handled by the row filter below).
_FLAG_MONITOR_ROLES = (
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.ADMIN.value,
)


def _actor_id(principal) -> str | None:
    """The acting user's id. The API passes an AuthPrincipal (`.user_id`); the
    server-rendered views pass the User model itself (`.id`)."""
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


def flags_visible_to(principal):
    """The flag queryset a principal may read.

    Mirrors the quality-checks page rule: a CD sees the flags they raised, the
    assigned PL sees the flags routed to them, IA/Admin monitor everything, and
    nobody else sees any. Without this the API returned every flag to any
    authenticated caller.
    """
    qs = CdFlag.objects.all().order_by("-created_at")
    role = getattr(principal, "active_role", "")
    if role in _FLAG_MONITOR_ROLES:
        return qs
    user_id = _actor_id(principal)
    if not user_id:
        return qs.none()
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return qs.filter(raised_by_user_id=user_id)
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return qs.filter(assigned_to_user_id=user_id)
    return qs.none()


def list_flags(query: dict, principal) -> list[dict]:
    qs = flags_visible_to(principal)
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    return [_serialize(f) for f in qs]


def update_flag(flag_id: str, data: dict, principal) -> dict:
    # Re-derive from the readable set: taking the id straight from the request
    # would let a caller act on a flag they can't see.
    flag = flags_visible_to(principal).filter(id=flag_id).first()
    if not flag:
        raise NotFoundError("Flag not found.")
    role = getattr(principal, "active_role", "")
    is_assignee = flag.assigned_to_user_id == _actor_id(principal)
    if not (is_assignee or role == EdifyRole.ADMIN.value):
        raise Forbidden("Only the assigned Program Lead may act on this flag.")
    action = data.get("action", "acknowledge")
    note = data.get("note")
    if action == "acknowledge":
        flag.status = "acknowledged"
    elif action == "resolve":
        flag.status = "resolved"
        flag.resolved_at = timezone.now()
        flag.resolution_note = note
    if note and not flag.resolution_note:
        flag.resolution_note = note
    flag.save()
    audit_log(
        action=f"flag_{action}",
        subject_kind="CdFlag",
        subject_id=flag.id,
        actor_id=_actor_id(principal),
        actor_role=role,
        payload={"status": flag.status},
    )
    return _serialize(flag)


def _serialize(f: CdFlag) -> dict:
    return {
        "id": f.id,
        "raisedByUserId": f.raised_by_user_id,
        "raisedByName": f.raised_by_name,
        "assignedToUserId": f.assigned_to_user_id,
        "category": f.category,
        "scopeType": f.scope_type,
        "scopeId": f.scope_id,
        "scopeName": f.scope_name,
        "note": f.note,
        "recommendedAction": f.recommended_action,
        "priority": f.priority,
        "dueDate": f.due_date,
        "status": f.status,
        "resolutionNote": f.resolution_note,
        "resolvedAt": f.resolved_at.isoformat() if f.resolved_at else None,
    }
