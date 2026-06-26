"""Fund-requests endpoints — /api/fund-requests/*."""
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
PAYMENT = [Permission.PAYMENT_ACT.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class FundRequestListSubmitView(APIView):
    @property
    def required_permissions(self):
        return APPROVE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_requests(_q(request), request.user))

    def post(self, request: Request) -> Response:
        return Response(services.submit(request.data, request.user), status=201)


class FundRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, request_id: str) -> Response:
        return Response(services.get_one(request_id, request.user))


class FundRequestRegenerateWeeklyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request) -> Response:
        return Response(services.regenerate("weekly", request.user))


class FundRequestRegenerateMonthlyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request) -> Response:
        return Response(services.regenerate("monthly", request.user))


def _action_view(fn, perm):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = perm

        def post(self, request: Request, request_id: str) -> Response:
            return Response(fn(request_id, request.data, request.user))

    return _V


ApproveView = _action_view(services.approve, APPROVE)
ReturnView = _action_view(services.return_request, APPROVE)
RejectView = _action_view(services.reject, APPROVE)
DisburseView = _action_view(services.disburse, PAYMENT)
AccountView = _action_view(services.submit_accountability, VIEW)


class AccountApproveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, request_id: str) -> Response:
        return Response(services.review_accountability(request_id, "approve", request.data, request.user))


class AccountReturnView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = APPROVE

    def post(self, request: Request, request_id: str) -> Response:
        return Response(services.review_accountability(request_id, "return", request.data, request.user))
