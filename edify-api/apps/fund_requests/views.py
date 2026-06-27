"""Fund-requests endpoints — /api/fund-requests/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services
from . import advance_service

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
    required_permissions = PAYMENT

    def post(self, request: Request, request_id: str) -> Response:
        return Response(services.review_accountability(request_id, "approve", request.data, request.user))


class AccountReturnView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def post(self, request: Request, request_id: str) -> Response:
        return Response(services.review_accountability(request_id, "return", request.data, request.user))


# ── Weekly advance-request endpoints ─────────────────────────────────────────
# The responsible user confirms their own advances (VIEW perm — the actor is the
# owner). Disbursement/accountability/reimbursement are PAYMENT (Accountant).
def _advance_view(fn, perm, takes_data=True):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = perm

        def post(self, request: Request, advance_id: str) -> Response:
            data = request.data if takes_data else {}
            return Response(fn(advance_id, data, request.user))

    return _V


class AdvanceQueuesView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def get(self, request: Request) -> Response:
        return Response(advance_service.accountant_queues())


# Responsible-user confirmation actions (the owner confirms their own advance).
class ConfirmAdvanceView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, advance_id: str) -> Response:
        return Response(advance_service.confirm_advance(advance_id, request.user))


class SelfFundedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, advance_id: str) -> Response:
        return Response(advance_service.self_funded(advance_id, request.user))


class NotRequestedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, advance_id: str) -> Response:
        return Response(advance_service.not_requested(advance_id, request.user))


# Accountant actions (PAYMENT permission).
AdvanceDisburseView = _advance_view(advance_service.disburse, PAYMENT)
AdvanceAccountView = _advance_view(advance_service.submit_accountability, VIEW)
AdvanceAccountApproveView = _advance_view(advance_service.approve_accountability, PAYMENT, takes_data=False)
AdvanceReimburseSubmitView = _advance_view(advance_service.submit_reimbursement, VIEW)
AdvanceReimburseView = _advance_view(advance_service.reimburse, PAYMENT)
