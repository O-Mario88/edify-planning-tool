"""Messaging service — in-app threads scoped to the caller."""
from __future__ import annotations

from django.utils import timezone
from django.db.models import Q

from apps.core.exceptions import NotFoundError, Forbidden, BadRequest
from apps.core.permissions import RolePermissionService
from apps.accounts.models import User

from .models import Message, MessageThread


def recent(principal, query: dict) -> list[dict]:
    qs = Message.objects.filter(
        Q(sender_id=principal.user_id) | Q(recipient_id=principal.user_id)
    ).order_by("-created_at")
    return [_serialize(m) for m in qs[:50]]


def counts(principal) -> dict:
    base = Message.objects.filter(recipient_id=principal.user_id)
    return {"unread": base.filter(status="unread").count(), "total": base.count()}


def recipients(principal) -> list[dict]:
    """Composable recipients for the caller (by role policy)."""
    users = User.objects.filter(deleted_at__isnull=True, status="active").exclude(id=principal.user_id)
    
    # Filter by role policy
    allowed_users = []
    for u in users:
        if RolePermissionService.can_message_recipient(principal, u):
            allowed_users.append(u)
            
    return [{"id": u.id, "name": u.name, "role": (u.roles or [None])[0]} for u in allowed_users[:100]]


def contexts(query: dict) -> list[dict]:
    recipient_id = query.get("recipientId")
    qs = Message.objects.all()
    if recipient_id:
        qs = qs.filter(recipient_id=recipient_id)
    return [{"contextType": m.context_type, "contextId": m.context_id} for m in qs.exclude(context_type__isnull=True).values("context_type", "context_id", "id")[:20]]


def thread(thread_id: str, principal) -> list[dict]:
    # Verify participant ownership
    t = MessageThread.objects.filter(id=thread_id).first()
    if not t:
        raise NotFoundError("Thread not found.")
    
    messages = Message.objects.filter(thread_id=thread_id).order_by("created_at")
    has_access = messages.filter(Q(sender_id=principal.user_id) | Q(recipient_id=principal.user_id)).exists()
    if not has_access and principal.active_role != "Admin":
        raise Forbidden("You are not a participant in this conversation thread.")
        
    return [_serialize(m) for m in messages]


def send(data: dict, principal) -> dict:
    recipient_id = data.get("recipientId")
    if not recipient_id:
        raise BadRequest("Recipient ID is required.")
        
    recipient = User.objects.filter(id=recipient_id, deleted_at__isnull=True).first()
    if not recipient:
        raise NotFoundError("Recipient not found.")
        
    # Check context rule
    if not data.get("contextType") or not data.get("contextId"):
        raise BadRequest("All new messages must have a context (contextType and contextId).")

    # Enforce role-based messaging policy
    if not RolePermissionService.can_message_recipient(principal, recipient):
        raise Forbidden("Your active role is not permitted to message this user.")

    thread, _ = MessageThread.objects.get_or_create(
        subject=data.get("subject", "(no subject)"),
        defaults={"context_type": data.get("contextType"), "context_id": data.get("contextId")},
    )
    msg = Message.objects.create(
        thread=thread,
        sender_id=principal.user_id,
        recipient_id=recipient_id,
        body=data.get("body", ""),
        category=data.get("category"),
        context_type=data.get("contextType"),
        context_id=data.get("contextId"),
        target_route=data.get("targetRoute"),
        action_required=bool(data.get("actionRequired")),
    )
    return _serialize(msg)


def reply(thread_id: str, data: dict, principal) -> dict:
    thread = MessageThread.objects.filter(id=thread_id).first()
    if not thread:
        raise NotFoundError("Thread not found.")
        
    # Verify participant access
    messages = Message.objects.filter(thread_id=thread_id)
    first_msg = messages.first()
    if not first_msg:
        raise BadRequest("Thread is empty.")
        
    has_access = messages.filter(Q(sender_id=principal.user_id) | Q(recipient_id=principal.user_id)).exists()
    if not has_access:
        raise Forbidden("You do not have permission to reply to this thread.")

    # Determine recipient (the other participant in the thread)
    recipient_id = first_msg.recipient_id if first_msg.sender_id == principal.user_id else first_msg.sender_id

    # Create message with inherited context
    msg = Message.objects.create(
        thread=thread,
        sender_id=principal.user_id,
        recipient_id=recipient_id,
        body=data.get("body", ""),
        context_type=thread.context_type,
        context_id=thread.context_id
    )
    return _serialize(msg)


def mark_read(message_id: str, principal) -> dict:
    m = Message.objects.filter(id=message_id).first()
    if m:
        if m.recipient_id != principal.user_id:
            raise Forbidden("Cannot mark another user's message as read.")
        m.status = "read"
        m.read_at = timezone.now() if hasattr(m, "read_at") else None
        m.save(update_fields=["status"])
    return {"ok": True}


def _serialize(m: Message) -> dict:
    return {
        "id": m.id,
        "threadId": m.thread_id,
        "senderId": m.sender_id,
        "recipientId": m.recipient_id,
        "body": m.body,
        "category": m.category,
        "priority": m.priority,
        "actionRequired": m.action_required,
        "status": m.status,
        "contextType": m.context_type,
        "contextId": m.context_id,
        "targetRoute": m.target_route,
        "createdAt": m.created_at.isoformat(),
    }
