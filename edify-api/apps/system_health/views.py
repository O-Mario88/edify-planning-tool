"""System-health endpoint — /api/system-health."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services


class SystemHealthView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_RECALC.value]

    def get(self, request: Request) -> Response:
        return Response(services.report())
