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
# Read access is any-of (RequirePermissions semantics): field roles hold
# PLANNING_VIEW, IA holds EVIDENCE_REVIEW, the Accountant holds PAYMENT_ACT.
# IA previously 403'd here, which is what pushed templates into linking raw
# /uploads/ paths that bypassed authorization entirely — never re-narrow this
# without fixing every template link. Object-level scope (including the
# Accountant's finance-only restriction) is enforced in services.file_for /
# list_for_activity, not here.
VIEW = [
    Permission.PLANNING_VIEW.value,
    Permission.EVIDENCE_REVIEW.value,
    Permission.PAYMENT_ACT.value,
]


class EvidenceUploadView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        """A partner's form, through the one door every upload takes
        (apps.evidence.form_document): staff work takes none, and a second
        file is taken only as another page (`anotherPage=yes`)."""
        from . import form_document

        files = [f for f in request.FILES.getlist("file") if f]
        activity_id = request.data.get("activityId", "")
        kind = request.data.get("kind", "visit_form")
        another = str(request.data.get("anotherPage", "")).lower() in (
            "yes",
            "true",
            "1",
        )
        if kind in form_document.FORM_KINDS:
            record = form_document.add_form_pages(
                principal=request.user,
                activity_id=activity_id,
                kind=kind,
                files=files,
                another_page=another,
            )
        else:
            from apps.activities.models import Activity
            from apps.core.exceptions import BadRequest

            if not files:
                raise BadRequest("A file is required.")
            activity = Activity.objects.filter(
                id=activity_id, deleted_at__isnull=True
            ).first()
            if activity is not None:
                form_document.assert_takes_upload(activity)
            record = services.record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind=kind,
                file_obj=files[0],
            )
        return Response(record, status=201)


class EvidenceActivityListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, activity_id: str) -> Response:
        return Response(services.list_for_activity(activity_id, request.user))


class EvidenceFormDocumentView(APIView):
    """The activity's uploaded form as one PDF (owner, 2026-10-14: "View
    Uploaded Visit Form" / "View Uploaded Training Attendance")."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, activity_id: str):
        from . import form_document

        download = request.query_params.get("download", "").lower() == "1"
        return form_document.document_response(
            activity_id, request.user, download=download
        )


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
