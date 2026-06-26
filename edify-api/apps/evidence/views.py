"""Evidence endpoints — /api/evidence/*."""
from __future__ import annotations

from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

UPLOAD = [Permission.ACTIVITY_COMPLETE.value]
REVIEW = [Permission.EVIDENCE_REVIEW.value]
VIEW = [Permission.PLANNING_VIEW.value]


class EvidenceUploadView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        file_obj = request.FILES.get("file")
        activity_id = request.data.get("activityId", "")
        kind = request.data.get("kind", "visit_form")
        return Response(services.record_upload(
            principal=request.user, activity_id=activity_id, kind=kind, file_obj=file_obj
        ), status=201)


class EvidenceActivityListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, activity_id: str) -> Response:
        return Response(services.list_for_activity(activity_id, request.user))


class EvidenceFileView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, evidence_id: str):
        download = request.query_params.get("download", "").lower() == "1"
        return services.file_for(evidence_id, request.user, download=download)


class EvidenceReviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = REVIEW

    def post(self, request: Request, evidence_id: str) -> Response:
        return Response(services.review(evidence_id, request.data, request.user))


class EvidencePrepareViewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request, evidence_id: str) -> Response:
        return Response(services.prepare_inline_view(evidence_id, request.user))


class EvidenceRenditionView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, evidence_id: str):
        return services.rendition_for(evidence_id, request.user)
