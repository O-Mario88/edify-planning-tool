"""Core-schools endpoints — /api/core/* (the Core/Champion pipeline)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PLANNING_VIEW.value]
CREATE = [Permission.PLANNING_CREATE.value]
SSA = [Permission.SSA_UPLOAD.value]


class CoreCandidatesListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_candidates(request.user))


class CoreCandidateVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = SSA

    def post(self, request: Request, school_id: str) -> Response:
        return Response(
            services.verify_candidate(school_id, request.data, request.user), status=201
        )


class CoreCandidateRejectView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = CREATE

    def post(self, request: Request, school_id: str) -> Response:
        return Response(
            services.reject_candidate(school_id, request.data, request.user), status=201
        )


class CoreCandidateOnboardView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = CREATE

    def post(self, request: Request, school_id: str) -> Response:
        return Response(
            services.onboard(school_id, request.data, request.user), status=201
        )


class CorePlansListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_plans(request.user))


class CoreSchoolDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, school_id: str) -> Response:
        return Response(services.get_detail(school_id, request.user))


class CoreSlotActionView(APIView):
    """Polymorphic slot action: POST /core/slots/:slotId/:action."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, slot_id: str, action: str) -> Response:
        return Response(
            services.slot_action(slot_id, action, request.data, request.user)
        )


class CoreFollowUpScheduleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, plan_id: str) -> Response:
        return Response(
            services.schedule_follow_up(plan_id, request.data, request.user)
        )


class CoreFollowUpSsaView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = SSA

    def post(self, request: Request, plan_id: str) -> Response:
        return Response(
            services.upload_follow_up_ssa(plan_id, request.data, request.user)
        )


class CoreChampionAdvanceView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, school_id: str) -> Response:
        return Response(services.advance_champion(school_id, request.user))
