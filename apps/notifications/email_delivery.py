"""Email: a copy of a notification, for what a person sent and what is urgent.

The proposal of 2026-10-21 asked for email as "a first-class delivery
channel", without Google Workspace, that "must not falsely report success"
while no provider is set up, and that does not mail every minor update.

There is still one source: the `Notification` row. This makes an email copy
of it, never a separate message.

* **Which** — a notification a person sent (a Send to, a Follow Up, a
  reminder: ``Notification.sender_id``), and an urgent notice. Everything
  else stays in the bell and on the phone.
* **Whether** — the recipient's `NotificationPreference` (email off, or a
  category muted) unless the notice is urgent, which is mandatory. A copy
  that is turned off is still recorded, as ``suppressed``.
* **How** — one `NotificationDelivery` row and one durable outbox event,
  written in the notification's own transaction; sent after commit on a
  short-lived thread, with the outbox's drain as the backstop. The handler
  runs outside any transaction (``atomic=False``) because it waits on a
  provider. The provider is given the delivery's id as its idempotency key,
  so a retry after a lost answer sends one email.
* **What is recorded** — ``accepted`` when the provider takes it, and
  ``delivered``, ``bounced`` or ``complained`` only when the provider says so
  in a signed event (`apply_provider_event`). With no provider, the copy is
  ``not_configured`` and nothing was sent.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import threading
import time

from django.conf import settings
from django.db import connections, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.utils import timezone

from apps.outbox.services import register

from .models import (
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationPreference,
)

logger = logging.getLogger("edify.notifications.email")

EVENT = "notification.email"
#: Tries before a copy is given up as failed. The outbox allows more, so the
#: copy always ends in a state of its own rather than a dead letter.
MAX_ATTEMPTS = 6
#: States a queued copy can still be sent from. ``sending`` is one: a worker
#: that died mid-send leaves it there, and the provider's idempotency key
#: makes the retry safe.
_SENDABLE = (
    DeliveryStatus.QUEUED,
    DeliveryStatus.RETRY_SCHEDULED,
    DeliveryStatus.SENDING,
)
#: How far a provider event may move a copy: never backwards, so a late
#: "delivered" does not overwrite a bounce.
_RANK = {
    DeliveryStatus.ACCEPTED: 1,
    DeliveryStatus.DELIVERED: 2,
    DeliveryStatus.BOUNCED: 3,
    DeliveryStatus.COMPLAINED: 3,
    DeliveryStatus.FAILED: 3,
}
_PROVIDER_EVENTS = {
    "email.delivered": DeliveryStatus.DELIVERED,
    "email.bounced": DeliveryStatus.BOUNCED,
    "email.complained": DeliveryStatus.COMPLAINED,
    "email.failed": DeliveryStatus.FAILED,
}
#: How old a signed provider event may be before it is refused as a replay.
WEBHOOK_TOLERANCE_SECONDS = 5 * 60


class EmailUnavailable(Exception):
    """The provider could not take the message now; the outbox retries."""


# ── Which notifications are emailed, and to whom ────────────────────────────
def is_mandatory(notification: Notification) -> bool:
    """An urgent notice is emailed whatever the recipient's settings say."""
    return notification.priority == "urgent"


def wants_email(notification: Notification, *, created: bool) -> bool:
    """A notification a person sent — and each reminder they send — and a
    new urgent notice. A job re-firing an urgent notice is not re-emailed."""
    if getattr(notification, "_sent_by_person", False):
        return True
    if not created:
        return False
    return bool(notification.sender_id) or is_mandatory(notification)


def turned_off(notification: Notification) -> bool:
    if is_mandatory(notification):
        return False
    preference = NotificationPreference.objects.filter(
        user_id=notification.recipient_id
    ).first()
    if preference is None:
        return False
    if not preference.email_enabled:
        return True
    return notification.category in (preference.email_muted_categories or [])


def enqueue(notification: Notification) -> list[str]:
    """Record this round's email copy and queue it; the outbox keys written.
    Inside the caller's transaction: no notification, no email."""
    from apps.outbox.services import enqueue as outbox_enqueue

    off = turned_off(notification)
    delivery, created = NotificationDelivery.objects.get_or_create(
        notification_id=notification.id,
        channel=DeliveryChannel.EMAIL,
        round=notification.reminder_count or 0,
        target="",
        defaults={
            "recipient_id": notification.recipient_id,
            "status": DeliveryStatus.SUPPRESSED if off else DeliveryStatus.QUEUED,
        },
    )
    if not created or off:
        return []
    key = f"email:{delivery.id}"
    outbox_enqueue(EVENT, {"deliveryId": delivery.id}, idempotency_key=key)
    return [key]


@receiver(post_save, sender=Notification, dispatch_uid="notifications.email_on_save")
def _email_on_save(sender, instance, created, update_fields=None, **_kwargs):
    """A new notification, or a person's reminder about one (the same save
    that bumps ``reminder_count``); never a read, a resolve or an edit."""
    if not created and "reminder_count" not in (update_fields or ()):
        return
    if instance.status != "unread" or instance.resolved_at:
        return
    if not wants_email(instance, created=created):
        return
    try:
        # A savepoint of its own: a failure here never poisons the
        # transaction that raised the notification.
        with transaction.atomic():
            keys = enqueue(instance)
    except Exception:  # noqa: BLE001 — an email copy never undoes the notice
        logger.exception("email could not be queued for %s", instance.id)
        return
    if keys and getattr(settings, "NOTIFICATION_EMAIL_EAGER", True):
        transaction.on_commit(lambda: deliver_soon(keys))


# ── What is sent ────────────────────────────────────────────────────────────
def app_base_url() -> str:
    return (
        os.environ.get("APP_BASE_URL") or getattr(settings, "APP_BASE_URL", "")
    ).rstrip("/")


def subject_for(notification: Notification) -> str:
    """A subject that says what kind of thing is waiting and nothing more:
    no school, no person and none of the message, which a lock screen or a
    shared inbox would otherwise show."""
    kind = (notification.category or "general").replace("_", " ")
    wording = (
        f"Edify: a {kind} item needs your action"
        if notification.action_required
        else f"Edify: a new {kind} notification"
    )
    return f"Urgent: {wording}" if is_mandatory(notification) else wording


def compose(notification: Notification, recipient):
    from apps.accounts.models import User
    from apps.core.email import MailMessage

    from .push import open_url

    sender = (
        User.objects.filter(id=notification.sender_id).only("name").first()
        if notification.sender_id
        else None
    )
    base = app_base_url()
    context = {
        "recipient_name": (recipient.name or "").split(" ")[0] or "there",
        "sender_name": getattr(sender, "name", "") or "",
        "title": notification.title,
        "body": notification.body or "",
        "action_label": notification.action_label or "Open in Edify",
        "open_url": f"{base}{open_url(notification.id)}",
        "settings_url": f"{base}/notifications/#delivery-settings",
        "sent_at": timezone.localtime(
            notification.last_reminded_at or notification.created_at
        ),
        "urgent": is_mandatory(notification),
    }
    return MailMessage(
        to=recipient.email,
        subject=subject_for(notification),
        text=render_to_string("emails/notification.txt", context),
        html=render_to_string("emails/notification.html", context),
    )


# ── Sending ─────────────────────────────────────────────────────────────────
def _record(delivery_id: str, status: str, **fields) -> None:
    now = timezone.now()
    if status == DeliveryStatus.FAILED:
        fields.setdefault("failed_at", now)
    if "last_error" in fields:
        fields["last_error"] = (fields["last_error"] or "")[:255]
    NotificationDelivery.objects.filter(id=delivery_id).update(
        status=status, updated_at=now, **fields
    )


def _recipient(user_id: str):
    from apps.accounts.models import User

    user = User.objects.filter(id=user_id).first()
    if user is None or not user.is_active or getattr(user, "deleted_at", None):
        return None
    if not (user.email or "").strip():
        return None
    return user


@register(
    EVENT,
    idempotency_note=(
        "A replay of a copy already accepted, failed or skipped does nothing "
        "(its row says so). A replay of one still sending is sent with the "
        "same provider idempotency key, which the provider sends once."
    ),
    atomic=False,
)
def handle_email(payload: dict) -> None:
    from apps.core.email import mailer

    delivery = NotificationDelivery.objects.filter(
        id=payload.get("deliveryId"), channel=DeliveryChannel.EMAIL
    ).first()
    if delivery is None or delivery.status not in _SENDABLE:
        return
    notification = Notification.objects.filter(id=delivery.notification_id).first()
    if notification is None or notification.resolved_at:
        _record(
            delivery.id,
            DeliveryStatus.SKIPPED,
            last_error="The work was done before the email was sent.",
        )
        return
    if notification.status != "unread":
        _record(
            delivery.id,
            DeliveryStatus.SKIPPED,
            last_error="Read in the app before the email was sent.",
        )
        return
    if not mailer.is_configured:
        _record(
            delivery.id,
            DeliveryStatus.NOT_CONFIGURED,
            last_error="No email provider is set up, so nothing was sent.",
        )
        return
    recipient = _recipient(delivery.recipient_id)
    if recipient is None:
        _record(
            delivery.id,
            DeliveryStatus.SKIPPED,
            last_error="The recipient has no active account with an email address.",
        )
        return

    attempts = delivery.attempts + 1
    _record(delivery.id, DeliveryStatus.SENDING, attempts=attempts)
    result = mailer.deliver(
        compose(notification, recipient),
        idempotency_key=f"edify-notification-{delivery.id}",
    )
    if result.accepted:
        _record(
            delivery.id,
            DeliveryStatus.ACCEPTED,
            provider_message_id=result.provider_id,
            sent_at=timezone.now(),
            last_error="",
        )
        return
    if result.retryable and attempts < MAX_ATTEMPTS:
        _record(delivery.id, DeliveryStatus.RETRY_SCHEDULED, last_error=result.error)
        raise EmailUnavailable(result.error)
    _record(delivery.id, DeliveryStatus.FAILED, last_error=result.error)


def deliver_soon(keys: list[str]) -> None:
    """Send without making the request that raised the notification wait on
    the provider; anything this does not finish is the drain's."""
    from apps.outbox.services import run_now

    def run() -> None:
        try:
            run_now(keys, worker_id="email-eager")
        except Exception:  # noqa: BLE001
            logger.exception("eager email delivery failed")
        finally:
            connections.close_all()

    threading.Thread(target=run, name="edify-email", daemon=True).start()


# ── What the provider says afterwards ───────────────────────────────────────
def signature_is_valid(
    secret: str, *, message_id: str, timestamp: str, signatures: str, body: bytes
) -> bool:
    """A provider event signed the way Resend signs them (Svix): HMAC-SHA256
    of ``id.timestamp.body`` with the endpoint's secret, sent fresh."""
    if not (secret and message_id and timestamp and signatures):
        return False
    try:
        sent_at = int(timestamp)
        key = base64.b64decode(secret.split("_", 1)[-1])
    except (ValueError, binascii.Error):
        return False
    if abs(time.time() - sent_at) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    expected = base64.b64encode(
        hmac.new(
            key, f"{message_id}.{timestamp}.".encode() + body, hashlib.sha256
        ).digest()
    ).decode()
    for candidate in signatures.split():
        version, _sep, signature = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(signature, expected):
            return True
    return False


def apply_provider_event(event: dict) -> bool:
    """Move a sent copy on by what the provider reports. True when a copy
    changed. Unknown events and unknown messages are ignored."""
    status = _PROVIDER_EVENTS.get(str(event.get("type") or ""))
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    provider_id = str(data.get("email_id") or "")[:128]
    if status is None or not provider_id:
        return False
    with transaction.atomic():
        delivery = (
            NotificationDelivery.objects.select_for_update()
            .filter(channel=DeliveryChannel.EMAIL, provider_message_id=provider_id)
            .first()
        )
        if delivery is None:
            return False
        if _RANK.get(status, 0) <= _RANK.get(delivery.status, 0):
            return False
        now = timezone.now()
        fields = {"status": status, "updated_at": now}
        if status == DeliveryStatus.DELIVERED:
            fields["delivered_at"] = now
        else:
            fields["failed_at"] = now
            fields["last_error"] = str(event.get("type"))[:255]
        NotificationDelivery.objects.filter(id=delivery.id).update(**fields)
    return True


__all__ = [
    "EVENT",
    "MAX_ATTEMPTS",
    "apply_provider_event",
    "deliver_soon",
    "enqueue",
    "handle_email",
    "signature_is_valid",
    "subject_for",
]
