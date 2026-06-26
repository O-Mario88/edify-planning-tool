"""Notifications service — per-user notification rail."""
from __future__ import annotations

from django.utils import timezone

from .models import Notification


def recent(principal) -> list[dict]:
    qs = Notification.objects.filter(recipient_id=principal.user_id).order_by("-created_at")[:50]
    return [_serialize(n) for n in qs]


def rail(principal) -> list[dict]:
    """The notification rail (unread + recent read, capped)."""
    qs = Notification.objects.filter(recipient_id=principal.user_id).order_by("-created_at")[:20]
    return [_serialize(n) for n in qs]


def counts(principal) -> dict:
    base = Notification.objects.filter(recipient_id=principal.user_id)
    return {"unread": base.filter(status="unread").count(), "total": base.count()}


def unread_count(principal) -> dict:
    return {"count": Notification.objects.filter(recipient_id=principal.user_id, status="unread").count()}


def mark_read(notification_id: str, principal) -> dict:
    n = Notification.objects.filter(id=notification_id, recipient_id=principal.user_id).first()
    if n:
        n.status = "read"
        n.read_at = timezone.now()
        n.save(update_fields=["status", "read_at"])
    return {"ok": True}


def mark_all_read(principal) -> dict:
    Notification.objects.filter(recipient_id=principal.user_id, status="unread").update(
        status="read", read_at=timezone.now()
    )
    return {"ok": True}


def resolve(notification_id: str, principal) -> dict:
    n = Notification.objects.filter(id=notification_id, recipient_id=principal.user_id).first()
    if n:
        n.status = "archived"
        n.save(update_fields=["status"])
    return {"ok": True}


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "priority": n.priority,
        "actionRequired": n.action_required,
        "actionLabel": n.action_label,
        "contextType": n.context_type,
        "contextId": n.context_id,
        "targetRoute": n.target_route,
        "status": n.status,
        "sourceEventType": n.source_event_type,
        "createdAt": n.created_at.isoformat(),
    }
