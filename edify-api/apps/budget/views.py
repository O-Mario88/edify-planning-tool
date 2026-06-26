"""Budget endpoints — /api/budget/* (the cost spine)."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PLANNING_VIEW.value]
COST_MANAGE = [Permission.COST_SETTINGS_MANAGE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class CostSettingsView(APIView):
    """GET (list, PLANNING_VIEW) + POST (upsert, COST_SETTINGS_MANAGE)."""

    @property
    def required_permissions(self):
        return COST_MANAGE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_cost_settings(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.upsert_cost_setting(request.data, request.user))


class CostSettingsHistoryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        key = request.query_params.get("key", "")
        return Response(services.cost_setting_history(key, request.user))


class CostingPreviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request) -> Response:
        return Response(services.cost_preview(request.data, request.user))


class BudgetFromScheduleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.from_schedule(request.user, _q(request)))


class BudgetWeeklyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.weekly(request.user, _q(request)))


class BudgetBoardView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.board(request.user, _q(request)))
