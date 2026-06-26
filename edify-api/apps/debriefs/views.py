"""Debriefs endpoints — /api/debriefs/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.DAILY_DEBRIEF_VIEW.value, Permission.STAFF_PERFORMANCE_VIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class DebriefListSubmitView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_debriefs(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.submit(request.data, request.user), status=201)


class DebriefTodayView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.today(request.user))


class DebriefDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, debrief_id: str) -> Response:
        return Response(services.get_one(debrief_id, request.user))


class DebriefMergePartnerView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request) -> Response:
        return Response(services.merge_partner_debrief(request.data, request.user), status=201)
