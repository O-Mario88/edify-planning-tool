"""Filters endpoints — /api/filters/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class FilterOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.options(request.user))


class FilterCountsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.counts(_q(request), request.user))


class CoreHeaderSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.core_header_summary(request.user))
