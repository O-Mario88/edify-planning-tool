"""Command-center endpoints — /api/command-center/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class CommandCenterTodayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.today(request.user))


class CommandCenterAlertsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.alerts(request.user))


class CommandCenterAlertsSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.alerts_summary(request.user))


class CommandCenterAlertDismissView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, alert_id: str) -> Response:
        return Response(services.dismiss(alert_id, request.data, request.user))
