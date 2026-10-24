"""Notifications endpoints — /api/notifications/*."""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services

logger = logging.getLogger("edify.notifications.email")


class NotificationRecentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.recent(request.user))


class NotificationRailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.rail(request.user))


class NotificationCountsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.counts(request.user))


class NotificationUnreadCountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.unread_count(request.user))


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        return Response(services.mark_all_read(request.user))


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, notification_id: str) -> Response:
        return Response(services.mark_read(notification_id, request.user))


class NotificationResolveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, notification_id: str) -> Response:
        return Response(services.resolve(notification_id, request.user))


# ── Phone notifications (apps.notifications.push) ───────────────────────────
class PushConfigView(APIView):
    """What a browser needs to subscribe: whether push is on here and the
    public key to subscribe with; and the ids still unread, so a device can
    clear from its tray what was read somewhere else."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        from . import fcm, push, webpush

        return Response(
            {
                "enabled": webpush.configured(),
                # The Edify app on a phone is told through Firebase instead.
                "app": fcm.configured(),
                "key": webpush.application_server_key(),
                "devices": push.live_subscriptions(request.user.id).count(),
                "unread": services.unread_ids(request.user),
            }
        )


class PushSubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        from . import push, webpush

        if not webpush.configured():
            return Response({"ok": False, "reason": "not_configured"}, status=409)
        keys = request.data.get("keys") or {}
        try:
            subscription, created = push.subscribe(
                request.user,
                request.data.get("endpoint", ""),
                keys.get("p256dh", ""),
                keys.get("auth", ""),
                request.META.get("HTTP_USER_AGENT", ""),
            )
        except push.InvalidSubscription:
            # A fixed sentence: what the browser sent is not echoed back, and
            # neither is anything about why it was refused.
            return Response(
                {"ok": False, "reason": "That is not a usable push subscription."},
                status=400,
            )
        if created and request.data.get("announce", True):
            # The first message a device gets proves the whole path to it.
            services.announce_push_enabled(request.user, subscription)
        return Response(
            {"ok": True, "created": created, "device": subscription.device_label}
        )


class PushUnsubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        from . import push

        reason = "signed_out" if request.data.get("reason") == "signed_out" else ""
        removed = push.unsubscribe(
            request.user, request.data.get("endpoint", ""), reason or "turned_off"
        )
        return Response({"ok": True, "removed": removed})


class AppRegisterView(APIView):
    """The Edify app on a phone hands over the device token Firebase gave it
    (static/js/native-push.js), once permission is granted after sign-in."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        from . import fcm, push

        if not fcm.configured():
            return Response({"ok": False, "reason": "not_configured"}, status=409)
        try:
            device, created = push.register_app(
                request.user,
                request.data.get("token", ""),
                request.data.get("platform", ""),
                request.META.get("HTTP_USER_AGENT", ""),
            )
        except push.InvalidSubscription:
            # A fixed sentence, as for a browser: nothing sent is echoed.
            return Response(
                {"ok": False, "reason": "That is not a usable device token."},
                status=400,
            )
        if created:
            services.announce_push_enabled(request.user, device)
        return Response({"ok": True, "created": created, "device": device.device_label})


class AppUnregisterView(APIView):
    """The app turned off on this phone, or the user signed out in it."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        from . import push

        reason = "signed_out" if request.data.get("reason") == "signed_out" else ""
        removed = push.unsubscribe(
            request.user, request.data.get("token", ""), reason or "turned_off"
        )
        return Response({"ok": True, "removed": removed})


# ── What the email provider reports (apps.notifications.email_delivery) ─────
@csrf_exempt  # Signed by the provider instead; a browser never posts here.
@require_POST
def email_provider_events(request):
    """Delivered, bounced and complained events from Resend.

    Nobody signs in to send these, so the signature is the whole of the
    check: an event that is unsigned, signed with another secret, or more
    than five minutes old is refused, and none is accepted until the signing
    secret is set.
    """
    from . import email_delivery

    secret = getattr(settings, "RESEND_WEBHOOK_SECRET", "")
    if not secret:
        return JsonResponse({"ok": False, "reason": "not_configured"}, status=503)
    body = request.body
    if not email_delivery.signature_is_valid(
        secret,
        message_id=request.headers.get("svix-id", ""),
        timestamp=request.headers.get("svix-timestamp", ""),
        signatures=request.headers.get("svix-signature", ""),
        body=body,
    ):
        logger.warning("refused an unsigned or stale email provider event")
        return JsonResponse({"ok": False}, status=401)
    try:
        event = json.loads(body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    if not isinstance(event, dict):
        return JsonResponse({"ok": False}, status=400)
    email_delivery.apply_provider_event(event)
    # Acknowledged whether or not it moved anything, so the provider does
    # not resend an event about a message this server does not know.
    return HttpResponse(status=200)
