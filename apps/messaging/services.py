"""Messaging service — in-app threads scoped to the caller."""
from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import NotFoundError

from .models import Message, MessageThread


def recent(principal, query: dict) -> list[dict]:
    qs = Message.objects.filter(recipient_id=principal.user_id).order_by("-created_at")
    return [_serialize(m) for m in qs[:50]]


def counts(principal) -> dict:
    base = Message.objects.filter(recipient_id=principal.user_id)
    return {"unread": base.filter(status="unread").count(), "total": base.count()}


def recipients(principal) -> list[dict]:
    """Composable recipients for the caller (by role policy)."""
    from apps.accounts.models import User

    users = User.objects.filter(deleted_at__isnull=True, status="active").exclude(id=principal.user_id)
    return [{"id": u.id, "name": u.name, "role": (u.roles or [None])[0]} for u in users[:100]]


def contexts(query: dict) -> list[dict]:
    recipient_id = query.get("recipientId")
    qs = Message.objects.all()
    if recipient_id:
        qs = qs.filter(recipient_id=recipient_id)
    return [{"contextType": m.context_type, "contextId": m.context_id} for m in qs.exclude(context_type__isnull=True).values("context_type", "context_id", "id")[:20]]


def thread(thread_id: str, principal) -> list[dict]:
    return [_serialize(m) for m in Message.objects.filter(thread_id=thread_id).order_by("created_at")]


def send(data: dict, principal) -> dict:
    thread, _ = MessageThread.objects.get_or_create(
        subject=data.get("subject", "(no subject)"),
        defaults={"context_type": data.get("contextType"), "context_id": data.get("contextId")},
    )
    msg = Message.objects.create(
        thread=thread,
        sender_id=principal.user_id,
        recipient_id=data.get("recipientId"),
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
    msg = Message.objects.create(thread=thread, sender_id=principal.user_id, body=data.get("body", ""))
    return _serialize(msg)


def mark_read(message_id: str, principal) -> dict:
    m = Message.objects.filter(id=message_id).first()
    if m:
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
