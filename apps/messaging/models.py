"""Messaging models — contextual, workflow-linked message threads.

Every thread is anchored to a workflow context (school, cluster, activity,
fund request, leave, …). Threads carry N participants (TO/CC) with per-user
read/archive state; messages belong to a thread and may carry attachments.
"""

from __future__ import annotations

from django.db import models

from apps.core.enums import MessageStatus, NotificationPriority
from apps.core.models import CuidField, TimeStampedModel


class MessageThread(TimeStampedModel):
    id = CuidField()
    subject = models.CharField(max_length=255)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=64, null=True, blank=True)
    # Human-readable snapshot of the context at thread creation, so the list
    # renders without resolving the record each time (and survives deletes).
    context_label = models.CharField(max_length=255, null=True, blank=True)
    category = models.CharField(max_length=64, null=True, blank=True)
    priority = models.CharField(
        max_length=16,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    created_by = models.CharField(max_length=30, null=True, blank=True)
    last_reply_at = models.DateTimeField(null=True, blank=True)
    is_system_generated = models.BooleanField(default=False)
    # Bulk-context sends keep the primary record in context_id and the full
    # selection here: [{"id", "label", "status"}, ...].
    linked_items = models.JSONField(default=list, blank=True)
    # The two participants, stored in sorted order so (A,B) == (B,A). Thread
    # identity for direct sends is participants + context + subject — never
    # subject alone, which merged unrelated users' conversations into one
    # thread and leaked messages across them. Null on multi-party threads.
    participant_a_id = models.CharField(max_length=30, null=True, blank=True)
    participant_b_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["participant_a_id", "participant_b_id"]),
            models.Index(fields=["context_type", "context_id"]),
        ]


class MessageParticipant(TimeStampedModel):
    """Per-user thread membership: TO/CC role, read cursor, archive state."""

    TO = "to"
    CC = "cc"

    id = CuidField()
    thread = models.ForeignKey(
        MessageThread, on_delete=models.CASCADE, related_name="participants"
    )
    user_id = models.CharField(max_length=30)
    recipient_type = models.CharField(
        max_length=8, choices=[(TO, "To"), (CC, "Cc")], default=TO
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    starred = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "user_id"], name="uniq_thread_participant"
            ),
        ]
        indexes = [models.Index(fields=["user_id", "archived_at"])]


class Message(TimeStampedModel):
    id = CuidField()
    thread = models.ForeignKey(
        MessageThread, on_delete=models.CASCADE, related_name="messages"
    )
    sender_id = models.CharField(max_length=30)
    recipient_id = models.CharField(max_length=30, null=True, blank=True)
    body = models.TextField()
    category = models.CharField(max_length=64, null=True, blank=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=64, null=True, blank=True)
    target_route = models.CharField(max_length=255, null=True, blank=True)
    priority = models.CharField(
        max_length=16,
        choices=NotificationPriority.choices,
        default=NotificationPriority.NORMAL,
    )
    action_required = models.BooleanField(default=False)
    is_system_generated = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=MessageStatus.choices, default=MessageStatus.UNREAD
    )

    class Meta:
        db_table = "message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["recipient_id", "status"])]


class MessageAttachment(TimeStampedModel):
    id = CuidField()
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to="message_attachments/%Y/%m/")
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=64, null=True, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_by = models.CharField(max_length=30, null=True, blank=True)


class MessageDraft(TimeStampedModel):
    """A compose form snapshot: context, recipients, category, body."""

    id = CuidField()
    user_id = models.CharField(max_length=30)
    subject = models.CharField(max_length=255, blank=True, default="")
    category = models.CharField(max_length=64, null=True, blank=True)
    context_type = models.CharField(max_length=64, null=True, blank=True)
    context_id = models.CharField(max_length=64, null=True, blank=True)
    recipient_ids = models.JSONField(default=list, blank=True)
    cc_ids = models.JSONField(default=list, blank=True)
    body = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user_id"])]


__all__ = [
    "MessageThread",
    "MessageParticipant",
    "Message",
    "MessageAttachment",
    "MessageDraft",
]
