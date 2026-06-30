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
