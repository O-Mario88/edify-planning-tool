"""Phone notifications: every notification, pushed to the user's devices.

Owner's brief, 2026-10-10: two things that must stay in step — the in-app
notification centre and the phone's own notification — and "do not implement
a fake notification system".

There is one source: the `Notification` row. Nothing is written for the
phone that the bell does not hold.

* **When** — a notification is saved for the first time, or re-fired for the
  same unresolved condition (`WorkflowNotificationService.trigger` and every
  other place that creates one: the hook is the model's own ``post_save``).
* **To whom** — each device the recipient subscribed on and has not turned
  off (`PushSubscription`).
* **How** — one durable outbox event per notification and device
  (apps.outbox): it commits with the notification or not at all, is retried
  with backoff while the push service or the network is down, and is tried
  at once after commit so a message does not wait for the minute's drain.
* **What the phone opens** — ``/notifications/<id>/open``: it signs the user
  in if the session has gone, marks the notification read, and goes to the
  record; a record that no longer exists clears the notification and says so
  (`open_destination`).

One notification is one message on a phone however many times it is sent:
the idempotency key is the notification, its re-fire count and the device,
and the message carries the notification's id as its ``tag`` and ``topic``,
so a repeat replaces the one already waiting or shown.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.outbox.services import register

from . import webpush
from .models import Notification, PushSubscription

logger = logging.getLogger("edify.notifications.push")

EVENT = "notification.push"
#: A notification older than this is history, not news: a phone that was off
#: for a week is not handed last week's reminders one by one.
FRESH_FOR = timedelta(hours=24)
#: What a phone shows of the body.
BODY_CHARS = 240


# ── Subscriptions ───────────────────────────────────────────────────────────
def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256((endpoint or "").encode("utf-8")).hexdigest()


def device_label(user_agent: str) -> str:
    """ "Android · Chrome" from a user agent: enough for a user to tell
    their phone from their laptop in their own list."""
    ua = user_agent or ""
    system = next(
        (
            name
            for token, name in (
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("Windows", "Windows"),
                ("Mac OS X", "Mac"),
                ("Linux", "Linux"),
            )
            if token in ua
        ),
        "Device",
    )
    browser = next(
        (
            name
            for token, name in (
                ("Edg/", "Edge"),
                ("SamsungBrowser", "Samsung Internet"),
                ("Firefox", "Firefox"),
                ("CriOS", "Chrome"),
                ("Chrome", "Chrome"),
                ("Safari", "Safari"),
            )
            if token in ua
        ),
        "Browser",
    )
    return f"{system} · {browser}"


class InvalidSubscription(ValueError):
    """What the browser sent is not a subscription this server can use."""


def subscribe(user, endpoint: str, p256dh: str, auth: str, user_agent: str = ""):
    """Record that ``user`` wants notifications on this device. A device is
    one row: subscribing again refreshes it, and a different user subscribing
    on the same device takes it over. Returns ``(subscription, created)``."""
    endpoint = (endpoint or "").strip()
    if not webpush.allowed_endpoint(endpoint):
        raise InvalidSubscription("That is not a browser push service address.")
    try:
        public = webpush._unb64url(p256dh)
        secret = webpush._unb64url(auth)
    except Exception as exc:  # noqa: BLE001 — any undecodable key is refused
        raise InvalidSubscription("The subscription keys are not readable.") from exc
    if len(public) != 65 or public[0] != 4 or len(secret) != 16:
        raise InvalidSubscription("The subscription keys are not the right shape.")
    subscription, created = PushSubscription.objects.update_or_create(
        endpoint_hash=endpoint_hash(endpoint),
        defaults={
            "user_id": user.id,
            "endpoint": endpoint,
            "p256dh": p256dh.strip(),
            "auth": auth.strip(),
            "user_agent": (user_agent or "")[:255],
            "device_label": device_label(user_agent),
            "last_seen_at": timezone.now(),
            "revoked_at": None,
            "revoked_reason": "",
            "failure_count": 0,
            "last_error": "",
        },
    )
    return subscription, created


def unsubscribe(user, endpoint: str, reason: str = "turned_off") -> int:
    """This device no longer wants ``user``'s notifications (turned off in
    the app, or the user signed out on it)."""
    return PushSubscription.objects.filter(
        endpoint_hash=endpoint_hash((endpoint or "").strip()),
        user_id=user.id,
        revoked_at__isnull=True,
    ).update(revoked_at=timezone.now(), revoked_reason=reason[:64])


def live_subscriptions(user_id):
    return PushSubscription.objects.filter(user_id=user_id, revoked_at__isnull=True)


# ── What a phone is sent ────────────────────────────────────────────────────
def open_url(notification_id: str) -> str:
    """Where a tap on the notification goes: the one address that marks it
    read and resolves its destination (never the destination itself, so a
    route that moves does not strand a message already on a phone)."""
    return f"/notifications/{notification_id}/open"


def payload_for(notification: Notification) -> dict:
    body = " ".join((notification.body or "").split())
    if len(body) > BODY_CHARS:
        body = body[: BODY_CHARS - 1].rstrip() + "…"
    return {
        "id": notification.id,
        "title": notification.title,
        "body": body,
        "url": open_url(notification.id),
        # One notification, one entry in the phone's tray: a re-send with
        # the same tag replaces it.
        "tag": f"edify-{notification.id}",
        "category": notification.category,
        "priority": notification.priority,
        "at": (notification.last_reminded_at or notification.created_at).isoformat(),
    }


# ── Queueing ────────────────────────────────────────────────────────────────
def enqueue(notification: Notification) -> list[str]:
    """One durable event for each of the recipient's devices; the keys of
    those written. Inside the caller's transaction: no notification, no
    push."""
    if not webpush.configured():
        return []
    from apps.outbox.services import enqueue_many

    subscriptions = list(
        live_subscriptions(notification.recipient_id).values_list("id", flat=True)
    )
    if not subscriptions:
        return []
    round_ = notification.reminder_count or 0
    items = [
        (
            {"notificationId": notification.id, "subscriptionId": subscription_id},
            f"push:{notification.id}:{round_}:{subscription_id}",
        )
        for subscription_id in subscriptions
    ]
    enqueue_many(EVENT, items)
    return [key for _payload, key in items]


@receiver(post_save, sender=Notification, dispatch_uid="notifications.push_on_save")
def _push_on_save(sender, instance, created, update_fields=None, **_kwargs):
    """Every new notification, and every re-fire of one (the service bumps
    ``reminder_count`` when the same unresolved condition comes round again);
    never a read, a resolve or a change of priority."""
    if not created and "reminder_count" not in (update_fields or ()):
        return
    if instance.status != "unread" or instance.resolved_at:
        return
    try:
        keys = enqueue(instance)
    except Exception:  # noqa: BLE001 — a phone copy never undoes the notice
        logger.exception("push could not be queued for %s", instance.id)
        return
    if keys and getattr(settings, "WEBPUSH_EAGER", True):
        transaction.on_commit(lambda: deliver_soon(keys))


# ── Delivery ────────────────────────────────────────────────────────────────
@register(
    EVENT,
    idempotency_note=(
        "A replay sends the same notification to the same device with the "
        "same tag and topic: the push service replaces a copy still waiting "
        "and the device replaces the one it shows, so the user sees one. A "
        "notification already read, resolved or a day old is not sent at all."
    ),
)
def handle_push(payload: dict) -> None:
    notification = Notification.objects.filter(id=payload.get("notificationId")).first()
    subscription = PushSubscription.objects.filter(
        id=payload.get("subscriptionId")
    ).first()
    if notification is None or subscription is None or subscription.revoked_at:
        return
    if subscription.user_id != notification.recipient_id:
        # The device was signed in to by someone else since.
        return
    if notification.status != "unread" or notification.resolved_at:
        # Read in the app, or the work was done, before the phone was told.
        return
    told = notification.last_reminded_at or notification.created_at
    if told < timezone.now() - FRESH_FOR:
        return
    try:
        webpush.send(
            webpush.Target(
                subscription.endpoint, subscription.p256dh, subscription.auth
            ),
            payload_for(notification),
            ttl=int(FRESH_FOR.total_seconds()),
            urgency="high" if notification.priority in ("high", "urgent") else "normal",
            topic=notification.id,
        )
    except webpush.PushGone as exc:
        # Permission withdrawn, app removed or subscription expired.
        PushSubscription.objects.filter(id=subscription.id).update(
            revoked_at=timezone.now(),
            revoked_reason="gone",
            last_error=str(exc)[:255],
        )
    except webpush.PushRejected as exc:
        # The same request will be refused again: recorded, not retried.
        logger.warning("push refused for %s: %s", subscription.id, exc)
        PushSubscription.objects.filter(id=subscription.id).update(
            failure_count=subscription.failure_count + 1, last_error=str(exc)[:255]
        )
    else:
        PushSubscription.objects.filter(id=subscription.id).update(
            last_success_at=timezone.now(), failure_count=0, last_error=""
        )
    # `PushUnavailable` is not caught: the outbox retries it with backoff.


def deliver(keys: list[str]) -> dict:
    """Run the queued events of ``keys`` now, as the outbox's drain would:
    claimed with SKIP LOCKED so the scheduler's drain and this never send the
    same one, each in its own transaction, a failure left pending for the
    drain's next attempt."""
    from apps.outbox.models import OutboxEvent, OutboxStatus
    from apps.outbox.services import CLAIM_SECONDS, _finish

    now = timezone.now()
    with transaction.atomic():
        claimed = list(
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(
                idempotency_key__in=keys,
                status=OutboxStatus.PENDING,
                next_attempt_at__lte=now,
            )
            .values_list("id", "payload")
        )
        OutboxEvent.objects.filter(id__in=[pk for pk, _p in claimed]).update(
            status=OutboxStatus.PROCESSING,
            locked_by="push-eager",
            locked_until=now + timedelta(seconds=CLAIM_SECONDS),
        )
    sent = failed = 0
    for event_id, payload in claimed:
        try:
            with transaction.atomic():
                handle_push(payload)
        except Exception as exc:  # noqa: BLE001 — recorded; the drain retries
            _finish(event_id, error=f"{type(exc).__name__}: {exc}")
            failed += 1
        else:
            _finish(event_id, error=None)
            sent += 1
    return {"sent": sent, "failed": failed}


def deliver_soon(keys: list[str]) -> None:
    """Send without making the request that raised the notification wait on
    a push service: a short-lived thread, which gives its database
    connection back when it is done. Anything it does not finish is the
    drain's within the minute."""

    def run() -> None:
        try:
            deliver(keys)
        except Exception:  # noqa: BLE001
            logger.exception("eager push delivery failed")
        finally:
            connections.close_all()

    threading.Thread(target=run, name="edify-push", daemon=True).start()


# ── Opening one ─────────────────────────────────────────────────────────────
#: The record a notification is about, by the kind it names: the model and
#: the fields its id may be written in. A kind not listed is taken to exist —
#: this only ever answers "certainly gone".
_RECORDS = {
    "activity": ("activities.Activity", ("id",)),
    "school": ("schools.School", ("id", "school_id")),
    "cluster": ("clusters.Cluster", ("id",)),
    "project": ("projects.Project", ("id",)),
    "message": ("messaging.Message", ("id",)),
    "partner": ("partners.Partner", ("id",)),
    "partnerassignment": ("partners.PartnerAssignment", ("id",)),
    "partner_assignment": ("partners.PartnerAssignment", ("id",)),
}


def record_gone(notification: Notification) -> bool:
    """Is the record the notification is about certainly gone (deleted, or
    never there)?"""
    from django.apps import apps
    from django.db.models import Q

    kind = (notification.context_type or "").lower()
    context_id = notification.context_id or ""
    if kind not in _RECORDS or not context_id:
        return False
    label, fields = _RECORDS[kind]
    model = apps.get_model(label)
    match = Q()
    for field in fields:
        match |= Q(**{field: context_id})
    records = model._default_manager.filter(match)
    if any(f.name == "deleted_at" for f in model._meta.fields):
        records = records.filter(deleted_at__isnull=True)
    return not records.exists()


def clear_gone(notifications) -> list:
    """``notifications`` without those whose record is certainly gone, which
    are resolved on the way: a list a reader is shown never holds a link
    that leads nowhere, and the notice is kept as history."""
    kept, gone = [], []
    for notification in notifications:
        (gone if record_gone(notification) else kept).append(notification)
    if gone:
        Notification.objects.filter(
            id__in=[n.id for n in gone], resolved_at__isnull=True
        ).update(resolved_at=timezone.now())
    return kept


def open_destination(notification: Notification, *, host: str, secure: bool) -> dict:
    """Handle a tap: mark the notification read and say where to go.

    ``{"url", "gone"}``: the destination, or — when the record is gone or the
    route is not one of the application's — the notification centre with
    ``gone`` set, the notification resolved so it leaves the active list."""
    from urllib.parse import urlsplit

    from django.urls import Resolver404, resolve
    from django.utils.http import url_has_allowed_host_and_scheme

    now = timezone.now()
    fields = []
    if notification.status == "unread":
        notification.status = "read"
        notification.read_at = now
        fields += ["status", "read_at"]
    route = notification.target_route or ""
    gone = not route or not route.startswith("/") or route.startswith("//")
    if not gone:
        gone = not url_has_allowed_host_and_scheme(
            route, allowed_hosts={host}, require_https=secure
        )
    if not gone:
        try:
            resolve(urlsplit(route).path)
        except Resolver404:
            gone = True
    if not gone:
        gone = record_gone(notification)
    if gone and notification.resolved_at is None:
        # Nothing left to act on: it is handled, and kept as history.
        notification.resolved_at = now
        fields.append("resolved_at")
    if fields:
        notification.save(update_fields=[*fields, "updated_at"])
    return {"url": "/notifications?gone=1" if gone else route, "gone": gone}
