"""Notification model — per-user notification rail."""
from __future__ import annotations

from django.db import models

from apps.core.enums import MessageStatus, NotificationPriority
from apps.core.models import CuidField, TimeStampedModel


class Notification(TimeStampedModel):
    """A per-user notification (workflow-generated, with provenance for dedupe)."""

    id = CuidField()
    recipient_id = models.CharField(max_length=30)
    recipient_role = models.CharField(max_length=64, null=True, blank=True)
    title = models.CharField(max_length=255)
    body = models.TextField(null=True, blank=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=30, null=True, blank=True)
    target_route = models.CharField(max_length=255, null=True, blank=True)
    action_label = models.CharField(max_length=64, null=True, blank=True)
    action_required = models.BooleanField(default=False)
    priority = models.CharField(max_length=16, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL)
    status = models.CharField(max_length=16, choices=MessageStatus.choices, default=MessageStatus.UNREAD)
    source_event_type = models.CharField(max_length=64, null=True, blank=True)
    source_event_id = models.CharField(max_length=30, null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient_id", "status"]),
            models.Index(fields=["source_event_id"]),
        ]


__all__ = ["Notification"]
