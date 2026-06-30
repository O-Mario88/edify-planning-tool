"""Reports endpoints — /api/reports/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services


class ReportListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ANALYTICS_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.list_reports(request.user))


class ReportGenerateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ANALYTICS_VIEW.value]

    def post(self, request: Request) -> Response:
        return Response(services.generate(request.data, request.user), status=201)


class ReportDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ANALYTICS_VIEW.value]

    def get(self, request: Request, report_id: str) -> Response:
        return Response(services.get_one(report_id, request.user))
