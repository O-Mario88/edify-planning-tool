"""Assignment endpoints — /api/assignment/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PLANNING_VIEW.value]
MANAGE = [Permission.STAFF_MANAGE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class AssignmentOptionsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.get_options(_q(request), request.user))


class AssignmentCapacityView(APIView):
    @property
    def required_permissions(self):
        return MANAGE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.get_capacity(_q(request), request.user))

    def post(self, request: Request) -> Response:
        return Response(services.set_capacity(request.data, request.user))
