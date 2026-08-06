"""Flags endpoints — /api/flags/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

# Flags are the CD→PL quality-escalation channel. The page equivalent
# ("quality_checks") is limited to IA/CD/PL/Admin — all analytics holders.
# Deliberately NOT planning.view: Partner roles hold that, and a partner has
# no business on the quality board. Row-level visibility is narrowed again
# inside the service (flags_visible_to), so analytics roles with no flag
# relationship get an empty list rather than someone else's escalations.
FLAG_ACCESS = [Permission.ANALYTICS_VIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class FlagListRaiseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = FLAG_ACCESS

    def get(self, request: Request) -> Response:
        return Response(services.list_flags(_q(request), request.user))

    def post(self, request: Request) -> Response:
        return Response(services.raise_flag(request.data, request.user), status=201)


class FlagProgramLeadsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = FLAG_ACCESS

    def get(self, request: Request) -> Response:
        return Response(services.program_leads(request.user))


class FlagUpdateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = FLAG_ACCESS

    def patch(self, request: Request, flag_id: str) -> Response:
        return Response(services.update_flag(flag_id, request.data, request.user))
