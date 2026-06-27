"""Planning endpoints — /api/planning/*."""
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
APPROVE = [Permission.BUDGET_APPROVE.value]
ASSIGN = [Permission.ACTIVITY_ASSIGN.value]
RECALC = [Permission.PLANNING_RECALC.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class PlanningSetupView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.setup(_q(request), request.user))


class PlanningCoreView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.core_planning(_q(request), request.user))


class PlanningPlanBuilderView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.plan_builder(_q(request), request.user))


class PlanningRecomputeView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = RECALC

    def post(self, request: Request, school_id: str) -> Response:
        return Response(services.recompute(school_id, request.user))


class PlanDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, plan_id: str) -> Response:
        return Response(services.get_plan(plan_id, request.user))


class PlanListCreateView(APIView):
    """GET /planning/plans (list) + POST /planning/plans (create) — same path."""

    @property
    def required_permissions(self):
        return CREATE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_plans(_q(request), request.user))

    def post(self, request: Request) -> Response:
        return Response(services.create_plan(request.data, request.user), status=201)


class PlanAddActivityView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = CREATE

    def post(self, request: Request, plan_id: str) -> Response:
        return Response(services.create_plan({"monthIso": None, "activities": [request.data]}, request.user))


def _lifecycle_view(fn, perm):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = perm

        def post(self, request: Request, plan_id: str) -> Response:
            return Response(fn(plan_id, request.data, request.user))

    return _V


PlanSubmitView = _lifecycle_view(services.submit_plan, CREATE)
PlanApproveView = _lifecycle_view(services.approve_plan, APPROVE)
PlanReturnView = _lifecycle_view(services.return_plan, APPROVE)


class ScheduleSchoolVisitView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.schedule_school_visit(request.data, request.user), status=201)


class AssignSchoolVisitToPartnerView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.assign_school_visit_to_partner(request.data, request.user), status=201)


class ScheduleClusterTrainingView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.schedule_cluster_training(request.data, request.user), status=201)


class ScheduleClusterActivityView(APIView):
    """Schedule a cluster activity (Group Training OR Cluster Meeting). The body
    carries activityType ('cluster_training'|'cluster_meeting'), clusterId,
    expectedParticipants, scheduledDate, plannedMonth/Week. The central
    CostingService prices it before the activity is persisted."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.schedule_cluster_activity(request.data, request.user), status=201)
