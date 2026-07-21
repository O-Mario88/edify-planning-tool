"""HR endpoints — /api/hr/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

ROSTER = [Permission.STAFF_PERFORMANCE_VIEW.value]
LEAVE = [Permission.LEAVE_PLANNER_VIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class HrRosterView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ROSTER

    def get(self, request: Request) -> Response:
        return Response(services.roster(request.user))


class HrLeaveListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = LEAVE

    def get(self, request: Request) -> Response:
        return Response(services.list_leave(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        attachment_file = request.FILES.get("attachment")
        return Response(
            services.request_leave(request.data, request.user, attachment_file),
            status=201,
        )


class HrLeaveCalendarView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = LEAVE

    def get(self, request: Request) -> Response:
        return Response(
            services.approved_leave_calendar(request.user, _q(request))
        )


def _review_view(decision: str):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = LEAVE

        def post(self, request: Request, leave_id: str) -> Response:
            return Response(services.review_leave(leave_id, decision, request.user))

    return _V


LeaveApproveView = _review_view("approved")
LeaveRejectView = _review_view("rejected")
