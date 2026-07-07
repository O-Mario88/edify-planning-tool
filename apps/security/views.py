"""Security endpoint — /api/security/health (SYSTEM_ADMIN only)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services


class SecurityHealthView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.SYSTEM_ADMIN.value]

    def get(self, request: Request) -> Response:
        return Response(services.summary())
