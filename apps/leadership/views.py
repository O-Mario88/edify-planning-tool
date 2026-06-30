"""Leadership Decision Engine endpoints — /api/leadership/decision-engine/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.LEADERSHIP_ENGINE_VIEW.value]
REVIEW = [Permission.LEADERSHIP_DECISION_REVIEW.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class LeadershipBoardsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW
    def get(self, request): return Response(services.boards(request.user, _q(request)))


class LeadershipSnapshotView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW
    def get(self, request): return Response(services.snapshot(request.user, _q(request)))


class LeadershipInsightView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW
    def get(self, request, insight_id): return Response(services.get_insight(insight_id))


class LeadershipInsightMemoView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW
    def get(self, request, insight_id): return Response(services.memo(insight_id))


class LeadershipInsightReviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = REVIEW
    def post(self, request, insight_id): return Response(services.review(insight_id, request.data, request.user))


class LeadershipInsightNoteView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW
    def post(self, request, insight_id): return Response(services.add_note(insight_id, request.data, request.user), status=201)


class LeadershipRecomputeView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = REVIEW
    def post(self, request): return Response(services.recompute(request.data or _q(request), request.user))
