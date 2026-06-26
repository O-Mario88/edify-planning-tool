"""
Schools endpoints — /api/schools/* (the source-of-truth directory).

Two-layer auth everywhere: JWT + permission (SCHOOL_DIRECTORY_VIEW for the
directory; SCHOOL_VIEW for proposals/type). Scope-constrained inside the service.
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import EdifyPagination
from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services
from .serializers import SchoolDetailSerializer, SchoolRowSerializer

# Permission keys for the directory + operational surfaces.
DIR_VIEW = [Permission.SCHOOL_DIRECTORY_VIEW.value]
SCHOOL_VIEW = [Permission.SCHOOL_VIEW.value]
UPLOAD = [Permission.SCHOOL_UPLOAD.value]
RESOLVE_DUP = [Permission.SCHOOL_RESOLVE_DUPLICATE.value]


def _query_params(request: Request) -> dict:
    # DRF query_params is a QueryDict; flatten to a plain dict.
    return {k: request.query_params.get(k) for k in request.query_params}


class SchoolListCreateView(APIView):
    """GET /api/schools (list) + POST /api/schools (create) — same path, the
    permission differs by method (directory view for reads, upload for writes)."""

    pagination_class = EdifyPagination

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), RequirePermissions()]
        return [IsAuthenticated(), RequirePermissions()]

    def get_required_permissions(self):
        # POST requires SCHOOL_UPLOAD; GET requires SCHOOL_DIRECTORY_VIEW.
        if self.request.method == "POST":
            return UPLOAD
        return DIR_VIEW

    # RequiredPermissions reads `required_permissions` off the view; expose both
    # via a property so it resolves per-method.
    @property
    def required_permissions(self):
        return self.get_required_permissions()

    def get(self, request: Request) -> Response:
        qs = services.list_schools(_query_params(request), request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, self)
        return paginator.get_paginated_response(SchoolRowSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        school = services.create_one(request.data, request.user)
        return Response(SchoolDetailSerializer(school).data, status=201)


class SchoolProposalsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = SCHOOL_VIEW

    def get(self, request: Request) -> Response:
        limit = int(request.query_params.get("limit", 10))
        return Response(services.proposals(request.user, limit=limit))


class SchoolDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = DIR_VIEW

    def get(self, request: Request, school_id: str) -> Response:
        school = services.get_one(school_id, request.user)
        return Response(SchoolDetailSerializer(school).data)


class SchoolWorkflowView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = DIR_VIEW

    def get(self, request: Request, school_id: str) -> Response:
        fy = request.query_params.get("fy")
        return Response(services.workflow(school_id, request.user, fy=fy))


class SchoolNextActionsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = DIR_VIEW

    def get(self, request: Request, school_id: str) -> Response:
        fy = request.query_params.get("fy")
        return Response(services.next_actions(school_id, request.user, fy=fy))


class SchoolBulkUploadView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def post(self, request: Request) -> Response:
        rows = request.data if isinstance(request.data, list) else request.data.get("schools", [])
        return Response(services.bulk_upload(rows, request.user), status=201)


class SchoolClusterAssignView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.CLUSTER_ASSIGN.value]

    def post(self, request: Request, school_id: str) -> Response:
        # Delegate to the clusters app once it lands; for now set the FK directly.
        from apps.clusters.services import assign_school  # type: ignore

        return Response(assign_school(school_id, request.data, request.user))


class SchoolResolveDuplicateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = RESOLVE_DUP

    def post(self, request: Request, school_id: str) -> Response:
        resolution = (request.data or {}).get("resolution", "not_duplicate")
        return Response(services.resolve_duplicate(school_id, resolution, request.user))


class SchoolTypeView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = SCHOOL_VIEW

    def post(self, request: Request, school_id: str) -> Response:
        school_type = (request.data or {}).get("schoolType")
        return Response(services.set_type(request.user, school_id, school_type))
