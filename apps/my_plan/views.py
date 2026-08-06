"""My-plan endpoint — /api/my-plan."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services


class MyPlanView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        query = {k: request.query_params.get(k) for k in request.query_params}
        return Response(services.get(request.user, query))
