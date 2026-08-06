"""Staff-management endpoints — /api/staff/*.

GET /api/staff              — roster with supervisor + assigned-school count.
POST /api/staff/{id}/assign-supervisor — CD/HR/Admin sets/changes a supervisor.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import supervisor_service

VIEW = [Permission.STAFF_PERFORMANCE_VIEW.value]  # roster read (CD/RVP/PL/HR/Admin)
MANAGE = [Permission.STAFF_MANAGE.value]  # supervisor assignment (CD/HR/Admin)


class StaffListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(supervisor_service.list_staff(request.user))


class AssignSupervisorView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def post(self, request: Request, staff_id: str) -> Response:
        return Response(
            supervisor_service.assign_supervisor(staff_id, request.data, request.user)
        )
