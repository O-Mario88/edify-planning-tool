"""Notification delivery health: is each channel set up, and is it working?

For administrators (the System Health permission). It shows whether a
credential is set, never what it is; what became of the last week's email
and phone copies; and lets an administrator send themselves a notification
through every channel to prove the path end to end.
"""

from __future__ import annotations

import os
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import require_page_permission

#: How far back the counts look.
WINDOW = timedelta(days=7)
_PROBLEM_STATUSES = (
    "failed",
    "bounced",
    "complained",
    "retry_scheduled",
    "not_configured",
)


def _email_channel() -> dict:
    from apps.core.email import mailer

    sender = os.environ.get("EMAIL_FROM") or getattr(settings, "EMAIL_FROM", "")
    return {
        "provider": "Resend" if mailer.is_configured else "None (console only)",
        "configured": mailer.is_configured,
        "api_key_set": bool((os.environ.get("RESEND_API_KEY") or "").strip()),
        "sender": sender,
        "webhook_set": bool(getattr(settings, "RESEND_WEBHOOK_SECRET", "")),
    }


def _push_channel(since) -> dict:
    from apps.notifications import fcm, webpush
    from apps.notifications.models import PushKind, PushSubscription

    live = PushSubscription.objects.filter(revoked_at__isnull=True)
    return {
        "configured": webpush.configured() or fcm.configured(),
        "browsers": webpush.configured(),
        # The Edify app on Android and iPhone, through Firebase.
        "app": fcm.configured(),
        "app_devices": live.exclude(kind=PushKind.WEB).count(),
        "devices": live.count(),
        "people": live.values("user_id").distinct().count(),
        "failing": live.filter(failure_count__gt=0).count(),
        "gone": PushSubscription.objects.filter(
            revoked_at__gte=since, revoked_reason="gone"
        ).count(),
        "last_success": live.aggregate(at=Max("last_success_at"))["at"],
    }


def _email_counts(since) -> list[dict]:
    from apps.notifications.models import DeliveryStatus, NotificationDelivery

    counted = dict(
        NotificationDelivery.objects.filter(channel="email", created_at__gte=since)
        .values("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    return [
        {"status": status, "label": label, "count": counted.get(status, 0)}
        for status, label in DeliveryStatus.choices
    ]


def _recent_problems():
    """Every email copy in trouble, newest first, with its recipient's name
    read in the same query. The page shows it a page at a time, so none is
    hidden behind a cap."""
    from django.db.models import OuterRef, Subquery

    from apps.accounts.models import User
    from apps.notifications.models import NotificationDelivery

    return (
        NotificationDelivery.objects.filter(
            channel="email", status__in=_PROBLEM_STATUSES
        )
        .annotate(
            recipient_name=Subquery(
                User.objects.filter(id=OuterRef("recipient_id")).values("name")[:1]
            )
        )
        .order_by("-updated_at", "-id")
    )


def _queue() -> dict:
    from apps.outbox.models import OutboxEvent

    events = OutboxEvent.objects.filter(
        event_type__in=("notification.email", "notification.push")
    )
    return {
        "pending": events.filter(status__in=("pending", "processing")).count(),
        "dead": events.filter(status="dead").count(),
    }


@require_page_permission("system_health")
def delivery_health_view(request):
    from apps.notifications.models import Notification

    since = timezone.now() - WINDOW
    context = {
        "email": _email_channel(),
        "push": _push_channel(since),
        "in_app_week": Notification.objects.filter(created_at__gte=since).count(),
        "email_counts": _email_counts(since),
        "problems": _recent_problems(),
        "queue": _queue(),
        "test_sent": request.GET.get("test") == "sent",
    }
    return render(request, "pages/system_health/notifications.html", context)


@require_page_permission("system_health")
@require_POST
def send_test_notification_view(request):
    """A notification from the administrator to themselves, through the same
    path as any Send to: the bell, their devices and their inbox. Each one
    is new, so each is sent."""
    from apps.core.models import cuid
    from apps.notifications.services import notify_from_person

    notify_from_person(
        request.user,
        recipient_id=request.user.id,
        context_type="system",
        context_id=cuid(),
        source_event_type="notification_delivery_test",
        defaults={
            "recipient_role": getattr(request.user, "active_role", "") or "",
            "title": "Test notification",
            "body": (
                "You sent this from Notification delivery health to check "
                "that the bell, your devices and your email all receive it."
            ),
            "category": "system",
            "target_route": "/system-health/notifications",
            "action_label": "Open delivery health",
            "priority": "normal",
            "status": "unread",
        },
    )
    return redirect("/system-health/notifications?test=sent")
