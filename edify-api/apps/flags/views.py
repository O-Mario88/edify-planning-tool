"""Flags endpoints — /api/flags/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class FlagListRaiseView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.list_flags(_q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.raise_flag(request.data, request.user), status=201)


class FlagProgramLeadsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.program_leads(request.user))


class FlagUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, flag_id: str) -> Response:
        return Response(services.update_flag(flag_id, request.data, request.user))
