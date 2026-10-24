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
    #: The person who asked (a Send to, a Follow Up, a reminder); empty for a
    #: notice the platform raised by itself. What a person sends is also
    #: emailed (apps.notifications.email_delivery).
    sender_id = models.CharField(max_length=30, null=True, blank=True)
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


class PushKind(models.TextChoices):
    """What a device is told through: a browser's push service (Web Push), or
    Firebase Cloud Messaging for the Edify app, which carries an iPhone's
    messages on through Apple's push service."""

    WEB = "web", "Browser"
    ANDROID = "android", "Android app"
    IOS = "ios", "iPhone app"


class PushSubscription(TimeStampedModel):
    """One browser or installed app that asked to be told on the device.

    The row is what the browser's push service handed back when the user
    allowed notifications: the address to send to and the two keys a message
    is encrypted with (apps.notifications.webpush). A user has one row per
    device; a device belongs to whoever subscribed on it last, so a phone
    that changes hands stops receiving the previous user's notifications.

    A subscription is never deleted by a failure: it is marked revoked with
    the reason, so "why did my phone stop ringing" has an answer.

    The Edify app on a phone is a row here too (``kind`` android or ios): its
    ``endpoint`` is the device's FCM registration token and it has no keys,
    since Firebase encrypts on the way.
    """

    id = CuidField()
    user_id = models.CharField(max_length=30, db_index=True)
    kind = models.CharField(
        max_length=16, choices=PushKind.choices, default=PushKind.WEB
    )
    endpoint = models.TextField()
    #: SHA-256 of the endpoint: an endpoint is too long to index, and one
    #: device is one row.
    endpoint_hash = models.CharField(max_length=64, unique=True)
    p256dh = models.CharField(max_length=255, blank=True, default="")
    auth = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    #: "Android · Chrome", read from the user agent for the user's own list.
    device_label = models.CharField(max_length=64, blank=True, default="")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "notification_push_subscription"
        indexes = [
            models.Index(
                fields=["user_id", "revoked_at"], name="push_sub_user_live_idx"
            ),
        ]


class DeliveryChannel(models.TextChoices):
    EMAIL = "email", "Email"
    PUSH = "push", "Phone and desktop"


class DeliveryStatus(models.TextChoices):
    """Where one copy of a notification got to. Each is a different fact:
    a provider *accepting* a message is not the recipient *receiving* it."""

    QUEUED = "queued", "Queued"
    SENDING = "sending", "Sending"
    RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
    ACCEPTED = "accepted", "Accepted by provider"
    DELIVERED = "delivered", "Delivered"
    BOUNCED = "bounced", "Bounced"
    COMPLAINED = "complained", "Marked as spam"
    FAILED = "failed", "Failed"
    SUPPRESSED = "suppressed", "Turned off by recipient"
    SKIPPED = "skipped", "Not sent"
    NOT_CONFIGURED = "not_configured", "Email not set up"


class NotificationDelivery(TimeStampedModel):
    """One copy of one notification on one channel, and what became of it.

    The notification is the record; this is its travel log. A copy is one
    row per notification, channel, round (a reminder is a new round) and
    target (an address, or a device), so a retry updates its row and never
    adds one.
    """

    id = CuidField()
    notification_id = models.CharField(max_length=30, db_index=True)
    recipient_id = models.CharField(max_length=30)
    channel = models.CharField(max_length=16, choices=DeliveryChannel.choices)
    #: The notification's reminder count when this copy was made.
    round = models.PositiveIntegerField(default=0)
    #: The push subscription id for a device; empty for email, whose address
    #: is read when it is sent so a changed address is the one used.
    target = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.QUEUED
    )
    attempts = models.PositiveIntegerField(default=0)
    provider_message_id = models.CharField(max_length=128, blank=True, default="")
    last_error = models.CharField(max_length=255, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_delivery"
        constraints = [
            models.UniqueConstraint(
                fields=["notification_id", "channel", "round", "target"],
                name="notif_delivery_once",
            )
        ]
        indexes = [
            models.Index(
                fields=["channel", "status"], name="notif_delivery_status_idx"
            ),
            models.Index(
                fields=["provider_message_id"], name="notif_delivery_provider_idx"
            ),
            models.Index(fields=["created_at"], name="notif_delivery_created_idx"),
        ]


class NotificationPreference(TimeStampedModel):
    """How one person wants to be told, beyond the bell (which always has
    everything). Urgent notices ignore it: they are mandatory."""

    id = CuidField()
    user_id = models.CharField(max_length=30, unique=True)
    email_enabled = models.BooleanField(default=True)
    #: Categories this person does not want emailed.
    email_muted_categories = models.JSONField(default=list, blank=True)
    #: Push to this person's browsers and Edify app devices. Each device can
    #: also be turned off on its own; this is all of them at once.
    push_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "notification_preference"


__all__ = [
    "DeliveryChannel",
    "DeliveryStatus",
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "PushKind",
    "PushSubscription",
]
