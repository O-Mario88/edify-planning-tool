"""SSA endpoints — /api/ssa/*."""
from __future__ import annotations

from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BadRequest

from apps.core.pagination import EdifyPagination
from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.SSA_VIEW.value]
UPLOAD = [Permission.SSA_UPLOAD.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class SsaListUploadView(APIView):
    """GET /api/ssa (list) + POST /api/ssa (upload) — same path."""

    pagination_class = EdifyPagination

    @property
    def required_permissions(self):
        return UPLOAD if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        from .services import _serialize_record

        qs = services.list_records(request.user, _q(request))
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, self)
        return paginator.get_paginated_response([_serialize_record(r) for r in page])

    def post(self, request: Request) -> Response:
        return Response(services.upload(request.data, request.user), status=201)


class SsaSchoolHistoryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, school_id: str) -> Response:
        return Response(services.school_history(school_id, request.user))


class SsaRecommendationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, school_id: str) -> Response:
        return Response(services.recommendation(school_id, request.user))


class SsaVerificationRequirementsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.verification_requirements(request.user, _q(request)))


class SsaVerificationSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.verification_summary(request.user, _q(request)))


class SsaUploadView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def post(self, request: Request) -> Response:
        return Response(services.upload(request.data, request.user), status=201)


class SsaFileUploadView(APIView):
    """POST /api/ssa/upload — multipart SSA file (CSV / XLSX), field `file`."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        from .upload_service import upload_ssa_file

        file = request.FILES.get("file")
        if file is None:
            raise BadRequest("A file is required (multipart field 'file').")
        result = upload_ssa_file(file, request.user)
        return Response(result, status=200 if result["success"] else 422)
