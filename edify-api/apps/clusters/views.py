"""Clusters endpoints — /api/clusters/*."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.CLUSTER_VIEW.value]
ASSIGN = [Permission.CLUSTER_ASSIGN.value]


class ClusterListCreateView(APIView):
    """GET /api/clusters (list) + POST /api/clusters (create) — same path."""

    @property
    def required_permissions(self):
        return ASSIGN if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_clusters(request.user))

    def post(self, request: Request) -> Response:
        return Response(services.create_cluster(request.data, request.user), status=201)


class ClusterSubCountiesWithoutView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.sub_counties_without_clusters(request.user))


class ClusterPlanningView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.cluster_planning(request.user))


class ClusterCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.create_cluster(request.data, request.user), status=201)


class ClusterFromSchoolView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.create_from_school(request.data, request.user), status=201)


class ClusterAssignView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request) -> Response:
        return Response(services.assign(request.data, request.user))


class ClusterIntelligenceView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, cluster_id: str) -> Response:
        return Response(services.cluster_intelligence(cluster_id, request.user))


class ClusterSchoolsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, cluster_id: str) -> Response:
        return Response(services.cluster_schools(cluster_id, request.user))


class ClusterRecommendationsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, school_id: str) -> Response:
        return Response(services.recommendations(school_id, request.user))


class ClusterEligibleForSchoolView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, school_id: str) -> Response:
        return Response(services.eligible_for_school(school_id, request.user))
