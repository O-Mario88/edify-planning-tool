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
class DisburseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def post(self, request: Request, request_id: str) -> Response:
        from .models import WeeklyFundRequest
        if WeeklyFundRequest.objects.filter(id=request_id).exists():
            from .weekly_service import disburse
            return Response(disburse(request_id, request.data, request.user))
        return Response(services.disburse(request_id, request.data, request.user))
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


# ── Weekly request endpoints ─────────────────────────────────────────────────
from apps.core.exceptions import BadRequest

class WeeklyGenerateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request) -> Response:
        from .weekly_service import generate_weekly_fund_request
        week_start = request.data.get("weekStartDate")
        user_id = request.data.get("responsibleUser", request.user.user_id)
        if not week_start:
            raise BadRequest("weekStartDate is required.")
        wfr = generate_weekly_fund_request(user_id, week_start)
        if wfr:
            from .weekly_service import _serialize_request
            return Response(_serialize_request(wfr))
        return Response({"detail": "No activities scheduled for this week."}, status=200)


class WeeklyRequestListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        from .weekly_service import list_weekly_requests, accountant_weekly_queues
        if request.query_params.get("queues") == "true":
            return Response(accountant_weekly_queues())
        return Response(list_weekly_requests(_q(request), request.user))


class WeeklyRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, request_id: str) -> Response:
        from .weekly_service import get_weekly_request
        return Response(get_weekly_request(request_id, request.user))


class WeeklyRequestConfirmView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, request_id: str) -> Response:
        from .weekly_service import request_advance
        return Response(request_advance(request_id, request.user))


class WeeklyRequestSelfFundedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, request_id: str) -> Response:
        from .weekly_service import self_funded
        return Response(self_funded(request_id, request.user))


class WeeklyRequestNotRequestedView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, request_id: str) -> Response:
        from .weekly_service import not_requested
        return Response(not_requested(request_id, request.user))


class WeeklyRequestDisburseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def post(self, request: Request, request_id: str) -> Response:
        from .weekly_service import disburse
        return Response(disburse(request_id, request.data, request.user))
