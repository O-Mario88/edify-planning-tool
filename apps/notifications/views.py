"""Notifications endpoints — /api/notifications/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


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
        from . import push, webpush

        return Response(
            {
                "enabled": webpush.configured(),
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
