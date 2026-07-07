"""Partners endpoints — /api/partners/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PARTNER_VIEW.value]
MANAGE = [Permission.PARTNER_MANAGE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class PartnerListOnboardView(APIView):
    @property
    def required_permissions(self):
        return MANAGE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_partners(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.onboard(request.data, request.user), status=201)


class PartnerEligibleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.eligible(_q(request)))


class PartnerMeView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.my_partner(request.user))


class PartnerMeActivitiesView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.my_activities(request.user))


class PartnerMeScheduleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def post(self, request: Request, activity_id: str) -> Response:
        return Response(
            services.schedule_activity(activity_id, request.data, request.user)
        )


class PartnerUpdateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def patch(self, request: Request, partner_id: str) -> Response:
        return Response(services.update(partner_id, request.data, request.user))
