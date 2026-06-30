"""Messaging models — in-app message threads."""
from __future__ import annotations

from django.db import models

from apps.core.enums import MessageStatus, NotificationPriority
from apps.core.models import CuidField, TimeStampedModel


class MessageThread(TimeStampedModel):
    id = CuidField()
    subject = models.CharField(max_length=255)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=30, null=True, blank=True)


class Message(TimeStampedModel):
    id = CuidField()
    thread = models.ForeignKey(MessageThread, on_delete=models.CASCADE, related_name="messages")
    sender_id = models.CharField(max_length=30)
    recipient_id = models.CharField(max_length=30, null=True, blank=True)
    body = models.TextField()
    category = models.CharField(max_length=64, null=True, blank=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=30, null=True, blank=True)
    target_route = models.CharField(max_length=255, null=True, blank=True)
    priority = models.CharField(max_length=16, choices=NotificationPriority.choices, default=NotificationPriority.NORMAL)
    action_required = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=MessageStatus.choices, default=MessageStatus.UNREAD)

    class Meta:
        db_table = "message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["recipient_id", "status"])]


__all__ = ["MessageThread", "Message"]
