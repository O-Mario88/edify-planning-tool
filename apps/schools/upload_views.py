"""
File-upload endpoints:
  POST /api/schools/upload          — multipart school onboarding (CSV / XLSX)
  GET  /api/uploads                 — list upload batches (scoped)
  GET  /api/uploads/<id>            — one batch + truthful breakdown
  GET  /api/uploads/<id>/rows       — per-row results for a batch
"""
from __future__ import annotations

from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope

from .models import UploadBatch
from .upload_service import upload_school_file

UPLOAD = [Permission.SCHOOL_UPLOAD.value]


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class SchoolFileUploadView(APIView):
    """POST /api/schools/upload — raw file (field `file`), optional `update_existing`."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        file = request.FILES.get("file")
        if file is None:
            raise BadRequest("A file is required (multipart field 'file').")
        update_existing = _truthy(request.data.get("update_existing", False))
        result = upload_school_file(file, request.user, update_existing=update_existing)
        return Response(result, status=200 if result["success"] else 422)


def _scoped_batches(principal):
    scope = resolve_user_scope(principal)
    qs = UploadBatch.objects.all()
    if scope.country_scope:
        return qs
    return qs.filter(uploaded_by=principal.user_id)


def _serialize_batch(b: UploadBatch) -> dict:
    return {
        "id": b.id,
        "uploadType": b.upload_type,
        "source": b.source,
        "fileName": b.original_file_name or b.file_name,
        "uploadedBy": b.uploaded_by,
        "status": b.status,
        "totalRows": b.total_rows,
        "createdRows": b.created_rows,
        "updatedRows": b.updated_rows,
        "skippedRows": b.skipped_rows,
        "failedRows": b.failed_rows,
        "duplicateRows": b.duplicate_rows,
        "errorSummary": b.error_summary,
        "createdAt": b.created_at.isoformat() if b.created_at else None,
    }


class UploadBatchListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def get(self, request: Request) -> Response:
        qs = _scoped_batches(request.user)
        upload_type = request.query_params.get("type")
        if upload_type:
            qs = qs.filter(upload_type=upload_type)
        return Response([_serialize_batch(b) for b in qs[:200]])


class UploadBatchDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def get(self, request: Request, batch_id: str) -> Response:
        batch = _scoped_batches(request.user).filter(id=batch_id).first()
        if not batch:
            raise NotFoundError("Upload batch not found.")
        return Response(_serialize_batch(batch))


class UploadBatchRowsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def get(self, request: Request, batch_id: str) -> Response:
        batch = _scoped_batches(request.user).filter(id=batch_id).first()
        if not batch:
            raise NotFoundError("Upload batch not found.")
        rows = batch.row_results.all()
        status_filter = request.query_params.get("status")
        if status_filter:
            rows = rows.filter(status=status_filter)
        return Response([
            {
                "rowNumber": r.row_number,
                "schoolId": r.school_id,
                "status": r.status,
                "errorMessage": r.error_message,
                "rawData": r.raw_data_json,
            }
            for r in rows
        ])


class UploadBatchActionView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = UPLOAD

    def post(self, request: Request, batch_id: str, action: str) -> Response:
        from apps.schools.models import UploadBatch
        batch = _scoped_batches(request.user).filter(id=batch_id).first()
        if not batch:
            raise NotFoundError("Upload batch not found.")

        if action == "validate":
            if batch.status != "uploaded":
                raise BadRequest("Batch must be in 'uploaded' status to validate.")
            has_failures = batch.row_results.filter(status="failed").exists()
            batch.status = "completed_with_errors" if has_failures else "validated"
            batch.save()

        elif action == "reject":
            reason = request.data.get("reason", "").strip()
            batch.status = "rejected"
            if reason:
                batch.error_summary = reason
            batch.save()

        elif action == "import":
            if batch.status == "imported":
                return Response(_serialize_batch(batch))
            if batch.status not in ("validated", "completed_with_errors", "uploaded"):
                raise BadRequest("Batch must be validated to import.")
            
            if batch.upload_type == "schools":
                from apps.schools.upload_service import import_school_batch
                import_school_batch(batch, request.user)
            elif batch.upload_type == "ssa":
                from apps.ssa.upload_service import import_ssa_batch
                import_ssa_batch(batch, request.user)
            
            batch.status = "imported"
            batch.save()
        else:
            raise BadRequest("Invalid action.")

        return Response(_serialize_batch(batch))


__all__ = [
    "SchoolFileUploadView",
    "UploadBatchListView",
    "UploadBatchDetailView",
    "UploadBatchRowsView",
    "UploadBatchActionView",
]
