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
  off (`PushSubscription`): a browser (Web Push, `webpush`) or the Edify app
  on Android or iPhone (Firebase, `fcm`; brief of 2026-10-23).
* **Whether** — the recipient's push setting (`NotificationPreference`;
  urgent notices are sent regardless, as for email), an active account, and
  a role that can still open what the notification is about. Each copy is a
  `NotificationDelivery` row that says what became of it.
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

from . import apns, fcm, webpush
from .models import (
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    PushKind,
    PushSubscription,
)

logger = logging.getLogger("edify.notifications.push")

EVENT = "notification.push"
#: A notification older than this is history, not news: a phone that was off
#: for a week is not handed last week's reminders one by one.
FRESH_FOR = timedelta(hours=24)
#: What a phone shows of the body.
BODY_CHARS = 240
#: Tries before a copy is given up as failed. The outbox allows more, so the
#: copy always ends in a state of its own rather than a dead letter.
MAX_ATTEMPTS = 6
#: States a queued copy can still be sent from (``sending``: a worker died
#: mid-send; the tag and topic make a repeat replace the first).
_SENDABLE = (
    DeliveryStatus.QUEUED,
    DeliveryStatus.RETRY_SCHEDULED,
    DeliveryStatus.SENDING,
)


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


#: The phone systems the Edify app runs on, as the app names them.
APP_PLATFORMS = {"android": PushKind.ANDROID, "ios": PushKind.IOS}
_APP_DEVICE = {PushKind.ANDROID: "Android", PushKind.IOS: "iPhone"}


def register_app(user, token: str, platform: str, user_agent: str = ""):
    """Record that ``user`` wants notifications in the Edify app on this
    phone, by the token the app was given: Firebase's, or on an iPhone built
    without Firebase, Apple's own (sent straight to Apple, `apns`, where the
    deployment has its key). One phone is one row, as for a browser. Returns
    ``(subscription, created)``."""
    token = (token or "").strip()
    kind = APP_PLATFORMS.get((platform or "").strip().lower())
    if kind is None:
        raise InvalidSubscription("That is not a phone the Edify app runs on.")
    apple = kind == PushKind.IOS and apns.valid_token(token)
    if apple and not apns.configured():
        raise InvalidSubscription("Apple's own token needs this server's APNs key.")
    if not apple and not fcm.valid_token(token):
        raise InvalidSubscription("That is not a device token for the Edify app.")
    return PushSubscription.objects.update_or_create(
        endpoint_hash=endpoint_hash(token),
        defaults={
            "user_id": user.id,
            "kind": kind,
            "endpoint": token,
            "p256dh": "",
            "auth": "",
            "user_agent": (user_agent or "")[:255],
            "device_label": f"{_APP_DEVICE[kind]} · Edify app",
            "last_seen_at": timezone.now(),
            "revoked_at": None,
            "revoked_reason": "",
            "failure_count": 0,
            "last_error": "",
        },
    )


def live_subscriptions(user_id):
    return PushSubscription.objects.filter(user_id=user_id, revoked_at__isnull=True)


def ready_kinds() -> tuple[str, ...]:
    """The kinds of device this deployment can send to now."""
    kinds = (PushKind.WEB,) if webpush.configured() else ()
    if fcm.configured():
        kinds += (PushKind.ANDROID,)
    if fcm.configured() or apns.configured():
        kinds += (PushKind.IOS,)
    return kinds


def app_ready(platform: str = "") -> bool:
    """Whether the Edify app can be told here: on that kind of phone
    ("android", "ios"), or with none named, on some phone. Apple's key reaches
    iPhones only; Firebase reaches both."""
    kind = APP_PLATFORMS.get((platform or "").strip().lower())
    if kind is None:
        return fcm.configured() or apns.configured()
    return kind in ready_kinds()


def app_platforms() -> dict[str, bool]:
    """Which phones the Edify app can be told on here, for the page."""
    kinds = ready_kinds()
    return {name: kind in kinds for name, kind in APP_PLATFORMS.items()}


def _through_apple(subscription) -> bool:
    """An iPhone that gave Apple's own token is sent to Apple directly."""
    return subscription.kind == PushKind.IOS and apns.valid_token(subscription.endpoint)


def ready(subscription) -> bool:
    """Whether this one device can be sent to now: its kind, and for an
    iPhone, the service its token belongs to."""
    if subscription.kind not in ready_kinds():
        return False
    if subscription.kind == PushKind.IOS:
        return apns.configured() if _through_apple(subscription) else fcm.configured()
    return True


# ── Who may be sent one ─────────────────────────────────────────────────────
def is_mandatory(notification: Notification) -> bool:
    """An urgent notice is pushed whatever the recipient's setting says."""
    return notification.priority == "urgent"


def turned_off(notification: Notification) -> bool:
    if is_mandatory(notification):
        return False
    return NotificationPreference.objects.filter(
        user_id=notification.recipient_id, push_enabled=False
    ).exists()


def active_recipient(user_id: str):
    """The recipient, or None when the account is gone or deactivated."""
    from apps.accounts.models import User

    user = User.objects.filter(id=user_id).first()
    if user is None or not user.is_active or getattr(user, "deleted_at", None):
        return None
    return user


def can_open(user, notification: Notification) -> bool:
    """Can ``user``'s role open what the notification leads to? A role
    changed since it was raised may no longer reach the page."""
    from apps.core.permissions import can_open_url

    route = notification.target_route or ""
    return not route or can_open_url(user, route)


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
    """One delivery row and one durable event for each of the recipient's
    devices this deployment can reach; the keys of the events written.
    Inside the caller's transaction: no notification, no push.

    A copy the recipient turned off is recorded as ``suppressed`` and not
    queued; a deactivated account is sent nothing at all."""
    kinds = ready_kinds()
    if not kinds or active_recipient(notification.recipient_id) is None:
        return []
    from apps.outbox.services import enqueue_many

    subscriptions = [
        device.id
        for device in live_subscriptions(notification.recipient_id)
        .filter(kind__in=kinds)
        .only("id", "kind", "endpoint")
        # An iPhone's token belongs to Firebase or to Apple: queued only
        # where that one is set up.
        if ready(device)
    ]
    if not subscriptions:
        return []
    round_ = notification.reminder_count or 0
    off = turned_off(notification)
    items = []
    for subscription_id in subscriptions:
        _delivery, created = NotificationDelivery.objects.get_or_create(
            notification_id=notification.id,
            channel=DeliveryChannel.PUSH,
            round=round_,
            target=subscription_id,
            defaults={
                "recipient_id": notification.recipient_id,
                "status": DeliveryStatus.SUPPRESSED if off else DeliveryStatus.QUEUED,
            },
        )
        if created and not off:
            items.append(
                (
                    {
                        "notificationId": notification.id,
                        "subscriptionId": subscription_id,
                        "round": round_,
                    },
                    f"push:{notification.id}:{round_}:{subscription_id}",
                )
            )
    if items:
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
        # A savepoint of its own: a failure here never poisons the
        # transaction that raised the notification.
        with transaction.atomic():
            keys = enqueue(instance)
    except Exception:  # noqa: BLE001 — a phone copy never undoes the notice
        logger.exception("push could not be queued for %s", instance.id)
        return
    if keys and getattr(settings, "WEBPUSH_EAGER", True):
        transaction.on_commit(lambda: deliver_soon(keys))


# ── Delivery ────────────────────────────────────────────────────────────────
def _record(delivery, status: str, **fields) -> None:
    """Move a copy on; nothing for an event queued before copies were kept."""
    if delivery is None:
        return
    now = timezone.now()
    if status == DeliveryStatus.FAILED:
        fields.setdefault("failed_at", now)
    if "last_error" in fields:
        fields["last_error"] = (fields["last_error"] or "")[:255]
    NotificationDelivery.objects.filter(id=delivery.id).update(
        status=status, updated_at=now, **fields
    )


def _why_not(notification: Notification, subscription) -> tuple[str, str] | None:
    """Why this copy must not be sent now, as ``(status, sentence)``; None
    when it may be."""
    skipped = DeliveryStatus.SKIPPED
    if subscription.revoked_at:
        return skipped, "The device was turned off before it was sent."
    if subscription.user_id != notification.recipient_id:
        return skipped, "Someone else has since signed in on the device."
    if notification.status != "unread" or notification.resolved_at:
        return skipped, "Read in the app, or the work was done, before it was sent."
    told = notification.last_reminded_at or notification.created_at
    if told < timezone.now() - FRESH_FOR:
        return skipped, "More than a day old by the time it could be sent."
    if not ready(subscription):
        return skipped, "Push to this kind of device is not set up here."
    user = active_recipient(notification.recipient_id)
    if user is None:
        return skipped, "The recipient's account is no longer active."
    if not can_open(user, notification):
        return skipped, "The recipient's role cannot open what it is about."
    if turned_off(notification):
        return DeliveryStatus.SUPPRESSED, "Turned off by the recipient."
    return None


def _send(subscription, notification: Notification) -> str:
    """One message to one device; the provider's message id, if it gives
    one."""
    urgent = notification.priority in ("high", "urgent")
    ttl = int(FRESH_FOR.total_seconds())
    if subscription.kind == PushKind.WEB:
        webpush.send(
            webpush.Target(
                subscription.endpoint, subscription.p256dh, subscription.auth
            ),
            payload_for(notification),
            ttl=ttl,
            urgency="high" if urgent else "normal",
            topic=notification.id,
        )
        return ""
    if _through_apple(subscription):
        apns.send(
            subscription.endpoint,
            payload_for(notification),
            priority=notification.priority,
            collapse_id=notification.id,
            expires_in=ttl,
        )
        return ""
    return fcm.send(
        subscription.endpoint,
        payload_for(notification),
        ttl=ttl,
        urgent=urgent,
        collapse=notification.id,
    )


@register(
    EVENT,
    idempotency_note=(
        "A replay of a copy already accepted, failed or skipped does nothing "
        "(its delivery row says so). A replay of one still sending sends the "
        "same notification to the same device with the same tag and topic "
        "(collapse id on a phone app): the push service replaces a copy "
        "still waiting and the device replaces the one it shows."
    ),
    # It waits on a push service: outside any transaction, so a copy's
    # "retry scheduled" survives the retry it asks for.
    atomic=False,
)
def handle_push(payload: dict) -> None:
    notification = Notification.objects.filter(id=payload.get("notificationId")).first()
    subscription = PushSubscription.objects.filter(
        id=payload.get("subscriptionId")
    ).first()
    if notification is None or subscription is None:
        return
    delivery = NotificationDelivery.objects.filter(
        notification_id=notification.id,
        channel=DeliveryChannel.PUSH,
        round=payload.get("round", notification.reminder_count or 0),
        target=subscription.id,
    ).first()
    if delivery is not None and delivery.status not in _SENDABLE:
        return
    refusal = _why_not(notification, subscription)
    if refusal is not None:
        _record(delivery, refusal[0], last_error=refusal[1])
        return

    attempts = (delivery.attempts if delivery else 0) + 1
    _record(delivery, DeliveryStatus.SENDING, attempts=attempts)
    try:
        message_id = _send(subscription, notification)
    except webpush.PushGone as exc:
        # Permission withdrawn, app removed, or token or subscription
        # expired: never tried again.
        PushSubscription.objects.filter(id=subscription.id).update(
            revoked_at=timezone.now(),
            revoked_reason="gone",
            last_error=str(exc)[:255],
        )
        _record(delivery, DeliveryStatus.FAILED, last_error=f"Device gone: {exc}")
    except webpush.PushRejected as exc:
        # The same request will be refused again: recorded, not retried.
        logger.warning("push refused for %s: %s", subscription.id, exc)
        PushSubscription.objects.filter(id=subscription.id).update(
            failure_count=subscription.failure_count + 1, last_error=str(exc)[:255]
        )
        _record(delivery, DeliveryStatus.FAILED, last_error=str(exc))
    except webpush.PushUnavailable as exc:
        if attempts < MAX_ATTEMPTS:
            _record(delivery, DeliveryStatus.RETRY_SCHEDULED, last_error=str(exc))
            raise  # the outbox tries again with backoff
        _record(delivery, DeliveryStatus.FAILED, last_error=str(exc))
    else:
        PushSubscription.objects.filter(id=subscription.id).update(
            last_success_at=timezone.now(), failure_count=0, last_error=""
        )
        _record(
            delivery,
            DeliveryStatus.ACCEPTED,
            provider_message_id=(message_id or "")[:128],
            sent_at=timezone.now(),
            last_error="",
        )


def deliver(keys: list[str]) -> dict:
    """Run the queued events of ``keys`` now, as the outbox's drain would
    (claimed with SKIP LOCKED, so the drain and this never send the same
    one; a failure is left pending for the drain's next attempt)."""
    from apps.outbox.services import run_now

    result = run_now(keys, worker_id="push-eager")
    return {"sent": result["succeeded"], "failed": result["failed"]}


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
