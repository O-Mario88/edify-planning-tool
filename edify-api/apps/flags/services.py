"""Flags service — CD→PL flag handoff (CD raises; assigned PL acts)."""
from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.rbac import EdifyRole

from .models import CdFlag


def raise_flag(data: dict, principal) -> dict:
    # Only the CD raises flags.
    if principal.active_role not in (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value):
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


def list_flags(query: dict) -> list[dict]:
    qs = CdFlag.objects.all().order_by("-created_at")
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    return [_serialize(f) for f in qs]


def update_flag(flag_id: str, data: dict, principal) -> dict:
    flag = CdFlag.objects.filter(id=flag_id).first()
    if not flag:
        raise NotFoundError("Flag not found.")
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
