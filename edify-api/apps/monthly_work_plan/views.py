"""Monthly work-plan endpoints — /api/monthly-work-plan-budget/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PLANNING_VIEW.value]
APPROVE = [Permission.BUDGET_APPROVE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class MwpList(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_budgets(_q(request)))


class MwpDetail(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, budget_id: str) -> Response:
        return Response(services.get_one(budget_id))


class MwpAdminLineAdd(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, budget_id: str) -> Response:
        return Response(services.add_admin_line(budget_id, request.data, request.user), status=201)


class MwpAdminLineRemove(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def delete(self, request: Request, budget_id: str, line_id: str) -> Response:
        return Response(services.remove_admin_line(budget_id, line_id, request.user))


class MwpSubmitToRvp(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, budget_id: str) -> Response:
        return Response(services.submit_to_rvp(budget_id, request.user))


class MwpRvpApprove(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, budget_id: str) -> Response:
        return Response(services.rvp_approve(budget_id, request.data, request.user))


class MwpRvpReturn(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, budget_id: str) -> Response:
        return Response(services.rvp_return(budget_id, request.data, request.user))


class MwpSendToAccountant(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, budget_id: str) -> Response:
        return Response(services.mark_sent_to_accountant(budget_id, request.user))
