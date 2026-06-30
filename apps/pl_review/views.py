"""PL review endpoints — /api/pl/review-queue/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services


class PlReviewQueueView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.queue(request.user))


class PlReviewConfirmView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def post(self, request: Request, activity_id: str) -> Response:
        return Response(services.confirm(activity_id, request.user))


class PlReviewReturnView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def post(self, request: Request, activity_id: str) -> Response:
        return Response(services.return_activity(activity_id, request.data, request.user))
