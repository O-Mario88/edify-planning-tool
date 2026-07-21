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
    category = models.CharField(max_length=64, default="general", db_index=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=30, null=True, blank=True)
    target_route = models.CharField(max_length=255, null=True, blank=True)
    action_label = models.CharField(max_length=64, null=True, blank=True)
    action_required = models.BooleanField(default=False)
    priority = models.CharField(
        max_length=16,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    status = models.CharField(
        max_length=16, choices=MessageStatus.choices, default=MessageStatus.UNREAD
    )
    source_event_type = models.CharField(max_length=64, null=True, blank=True)
    source_event_id = models.CharField(max_length=30, null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # Set when the underlying workflow condition is satisfied. Until this
    # existed nothing ever closed a notification: To-Dos are derived live and
    # disappear when the work is done, but notifications persisted, so
    # approving a leave request cleared the task and left the notice unread
    # forever — and a job then promoted it to "urgent" at 48 hours, which is
    # why the urgent count carried no information.
    resolved_at = models.DateTimeField(null=True, blank=True)
    # How many times a reminder has re-fired for this same unresolved
    # condition. A reminder updates the live row rather than inserting a new
    # one, so a 30-day-overdue item is one notification with a count, not 30.
    reminder_count = models.PositiveIntegerField(default=0)
    last_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient_id", "status"]),
            models.Index(fields=["source_event_id"]),
            models.Index(
                fields=["recipient_id", "source_event_type", "context_id"],
                name="notif_dedupe_idx",
            ),
            models.Index(fields=["resolved_at"], name="notif_resolved_idx"),
        ]


__all__ = ["Notification"]
