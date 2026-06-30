"""Activities endpoints — /api/activities/* (the 21-state field-work lifecycle)."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import EdifyPagination
from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

PLANNING_VIEW = [Permission.PLANNING_VIEW.value]
ASSIGN = [Permission.ACTIVITY_ASSIGN.value]
COMPLETE = [Permission.ACTIVITY_COMPLETE.value]
IA_VERIFY = [Permission.IA_VERIFY.value]
PAYMENT = [Permission.PAYMENT_ACT.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class ActivityListCreateView(APIView):
    """GET /api/activities (list) + POST /api/activities (create)."""

    pagination_class = EdifyPagination

    @property
    def required_permissions(self):
        return ASSIGN if self.request.method == "POST" else PLANNING_VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        qs = services.list_activities(_q(request), request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, self)
        return paginator.get_paginated_response([services._serialize(a) for a in page])

    def post(self, request: Request) -> Response:
        return Response(services.create(request.data, request.user), status=201)


class ActivityPaymentQueueView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def get(self, request: Request) -> Response:
        return Response(services.payment_queue(request.user))


def _action_view(action_fn, perm):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = perm

        def post(self, request: Request, activity_id: str) -> Response:
            return Response(action_fn(activity_id, request.data, request.user))

    return _V


# State-transition endpoints (POST /:id/<action>).
StartCompletionView = _action_view(services.start_completion, COMPLETE)
CompleteView = _action_view(services.complete, COMPLETE)
IaConfirmView = _action_view(services.ia_confirm, IA_VERIFY)
RescheduleView = _action_view(services.reschedule, ASSIGN)
ReassignView = _action_view(services.reassign, ASSIGN)
CancelView = _action_view(services.cancel, ASSIGN)
DeferView = _action_view(services.defer, ASSIGN)


class ActivityClearPaymentView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PAYMENT

    def post(self, request: Request, activity_id: str) -> Response:
        return Response(services.clear_payment(activity_id, request.user))


class ScheduleSchoolVisitView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        from apps.planning.services import schedule_school_visit
        return Response(schedule_school_visit(request.data, request.user), status=201)


class ScheduleClusterActivityView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        from apps.planning.services import schedule_cluster_activity
        return Response(schedule_cluster_activity(request.data, request.user), status=201)


class SchedulePartnerVisitView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        from apps.planning.services import assign_school_visit_to_partner
        return Response(assign_school_visit_to_partner(request.data, request.user), status=201)


class ActivityDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PLANNING_VIEW

    def get(self, request: Request, activity_id: str) -> Response:
        return Response(services.get_activity(activity_id, request.user))

    def patch(self, request: Request, activity_id: str) -> Response:
        return Response(services.patch_activity(activity_id, request.data, request.user))
