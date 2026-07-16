"""
Evidence service — the file pipeline: secure upload, list, hardened file
serving, accept/return review, and on-demand DOCX→PDF rendition.

Files stored on local disk under EVIDENCE_STORAGE_DIR (absolute, persistent in
production). Downloads send hardened headers and object-authorize the parent
activity. A quarantined file is never downloadable.
"""

from __future__ import annotations

import logging
import os
import uuid

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import EvidenceKind, EvidenceStatus
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.scoping import resolve_user_scope

from .models import EvidenceRecord
from .validation import assert_safe_upload


VALID_KINDS = {k.value for k in EvidenceKind}
# Sources that can be converted into the standardized PDF preview (images are
# handled separately via Pillow; see prepare_inline_view).
CONVERTIBLE_EXTENSIONS = {".docx", ".doc", ".xlsx", ".xls", ".csv"}
logger = logging.getLogger(__name__)


def _assert_activity_in_scope(activity: Activity, principal) -> None:
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        # The Accountant is a country-scope role but its evidence reach is
        # narrower than its scope: read-only (it holds no EVIDENCE_REVIEW
        # permission, so review() is already unreachable) and limited to
        # evidence needed for financial clearance — activities with money
        # movement. Plain unfunded records stay out of its reach.
        if getattr(principal, "active_role", "") == "Accountant":
            has_finance = (
                activity.payment_status not in ("", "none", None)
                or activity.advance_requests.exists()
            )
            if not has_finance:
                raise Forbidden(
                    "Accountant evidence access is limited to activities "
                    "with financial involvement."
                )
        return
    if scope.staff_ids and activity.responsible_staff_id in scope.staff_ids:
        return
    if scope.partner_ids and activity.assigned_partner_id in scope.partner_ids:
        return
    if scope.school_ids and activity.school_id in scope.school_ids:
        return
    if scope.cluster_ids and activity.cluster_id in scope.cluster_ids:
        return
    raise Forbidden("Activity outside your scope.")


def evidence_dir() -> str:
    d = settings.EVIDENCE_STORAGE_DIR
    os.makedirs(d, exist_ok=True)
    return d


def infer_kind_from_upload(file_obj, default: str = EvidenceKind.PHOTO) -> str:
    """Best-effort EvidenceKind from a just-uploaded file's name/content-type.

    EvidenceKind only distinguishes "photo" from "pdf" by file shape (the
    other members are caller-asserted document *purposes*, e.g. attendance
    form). PDFs and Word documents are non-image evidence and should be
    stored as "pdf", not defaulted to "photo" just because that was the only
    kind a caller ever passed.
    """
    name = (getattr(file_obj, "name", "") or "").lower()
    content_type = (getattr(file_obj, "content_type", "") or "").lower()
    if name.endswith((".pdf", ".doc", ".docx")) or content_type in (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return EvidenceKind.PDF
    return default


def _scan_upload(path: str) -> tuple[str, str | None]:
    """Best-effort malware scan via a ClamAV daemon (clamd), if configured.

    Returns (scan_status, threat_name) where scan_status is one of
    clean|infected|skipped. Mirrors _try_docx_to_pdf's graceful-degradation
    pattern below: no CLAMAV_HOST configured, the clamd package missing, a
    connection failure, or any other scanner problem all degrade to
    ("skipped", None) rather than raising -- a scan must never block an
    upload, and "skipped" is always a safe, honest, pre-existing state for
    this field.
    """
    host = getattr(settings, "CLAMAV_HOST", None)
    if not host:
        return "skipped", None
    try:
        import clamd
    except ImportError:
        return "skipped", None
    try:
        client = clamd.ClamdNetworkSocket(
            host=host,
            port=getattr(settings, "CLAMAV_PORT", 3310),
            timeout=getattr(settings, "CLAMAV_TIMEOUT_SECONDS", 10),
        )
        with open(path, "rb") as fh:
            result = client.instream(fh)
        status, reason = result.get("stream", ("ERROR", None))
        if status == "OK":
            return "clean", None
        if status == "FOUND":
            return "infected", reason
        return "skipped", None
    except Exception as exc:  # noqa: BLE001 -- a scan failure must not block the upload
        logger.warning("Evidence malware scan unavailable (%s): %s", path, exc)
        return "skipped", None


def record_upload(*, principal, activity_id: str, kind: str, file_obj) -> dict:
    """Secure multipart upload. Validates extension + MIME + magic-byte sniff."""
    if not file_obj:
        raise BadRequest("A file is required.")
    if kind not in VALID_KINDS:
        raise BadRequest(f"Invalid evidence kind: {kind}")
    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not activity:
        raise NotFoundError("Activity not found")
    _assert_activity_in_scope(activity, principal)

    original_name = getattr(file_obj, "name", "upload")
    mime_type = getattr(file_obj, "content_type", "") or ""
    # Read the head for the magic-byte sniff.
    head = file_obj.read(512)
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    ext = assert_safe_upload(
        original_name=original_name, mime_type=mime_type, head=head, size=size
    )

    # Persist to disk under a unique filename.
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(evidence_dir(), stored_name)
    with open(dest, "wb") as out:
        for chunk in _chunks(file_obj):
            out.write(chunk)

    scan_status, threat_name = _scan_upload(dest)

    if scan_status == "infected":
        # Keep the record + quarantined file on disk for security review
        # (file_for() already refuses to serve anything quarantined), but
        # never let it become usable evidence or advance the activity.
        EvidenceRecord.objects.create(
            activity=activity,
            kind=kind,
            uri=stored_name,
            original_name=original_name,
            mime_type=mime_type or None,
            file_extension=ext,
            file_size=size,
            uploaded_by=principal.user_id,
            uploader_role=principal.active_role,
            scan_status="infected",
            quarantined=True,
            status=EvidenceStatus.REJECTED,
            review_note=f"Automatically quarantined: malware scan flagged '{threat_name}'.",
            preview_status="not_required",
        )
        raise BadRequest(
            "This file was flagged as a security threat by the malware scanner "
            "and has been rejected. Contact IT if you believe this is an error."
        )

    is_pdf = ext == ".pdf" or mime_type == "application/pdf"
    is_image = mime_type.startswith("image/")
    # Convertible-to-PDF sources: office docs via LibreOffice, images via
    # Pillow (§6 mandate: consistent PDF viewing experience — a PDF renders
    # directly; everything else gets a generated PDF preview on demand,
    # original always preserved). Images stay "ready" for the native inline
    # view AND are convertible when the standardized PDF is requested.
    is_convertible = ext in CONVERTIBLE_EXTENSIONS or is_image
    preview_status = (
        "ready"
        if (is_pdf or is_image)
        else ("pending" if is_convertible else "not_required")
    )

    record = EvidenceRecord.objects.create(
        activity=activity,
        kind=kind,
        uri=stored_name,
        original_name=original_name,
        mime_type=mime_type or None,
        file_extension=ext,
        file_size=size,
        uploaded_by=principal.user_id,
        uploader_role=principal.active_role,
        scan_status=scan_status,  # clean|skipped -- see _scan_upload
        preview_status=preview_status,
    )
    # Bump the activity's evidence status.
    activity.evidence_status = "uploaded"
    activity.save(update_fields=["evidence_status", "updated_at"])
    return _serialize(record)


def _chunks(file_obj, chunk_size=64 * 1024):
    file_obj.seek(0)
    while True:
        data = file_obj.read(chunk_size)
        if not data:
            break
        yield data


def evidence_records_for_activity(activity_id: str, principal):
    """Scope-checked EvidenceRecord queryset for server-rendered templates.

    Same authorization + quarantine rules as list_for_activity, but returns
    model instances — templates read snake_case attributes (original_name,
    file_size, created_at, notes), and feeding them the camelCase API dicts
    silently rendered every field blank."""
    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not activity:
        raise NotFoundError("Activity not found.")
    _assert_activity_in_scope(activity, principal)
    return EvidenceRecord.objects.filter(activity=activity).exclude(quarantined=True)


def list_for_activity(activity_id: str, principal) -> list[dict]:
    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not activity:
        raise NotFoundError("Activity not found.")
    _assert_activity_in_scope(activity, principal)
    qs = EvidenceRecord.objects.filter(activity=activity).exclude(quarantined=True)
    return [_serialize(e) for e in qs]


def file_for(record_id: str, principal, *, download: bool = False):
    """Stream a stored file with hardened headers. Object-authorizes the activity."""
    record = EvidenceRecord.objects.filter(id=record_id).first()
    if not record:
        raise NotFoundError("Evidence not found.")
    _assert_activity_in_scope(record.activity, principal)
    if record.quarantined:
        raise BadRequest("This file has been quarantined and cannot be viewed.")
    path = os.path.join(evidence_dir(), record.uri)
    if not os.path.exists(path):
        raise NotFoundError("File not found on disk.")
    record.view_count += 1
    record.save(update_fields=["view_count"])
    response = FileResponse(
        open(path, "rb"), content_type=record.mime_type or "application/octet-stream"
    )
    disposition = (
        "attachment"
        if download
        else (
            "inline"
            if (record.mime_type or "").startswith("image/")
            or record.mime_type == "application/pdf"
            else "attachment"
        )
    )
    response["Content-Disposition"] = (
        f'{disposition}; filename="{record.original_name or record.uri}"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'"
    response["X-Frame-Options"] = "DENY"
    return response


def review(record_id: str, data: dict, principal) -> dict:
    """Accept or return evidence -> drives the activity's evidence_status."""
    record = EvidenceRecord.objects.filter(id=record_id).first()
    if not record:
        raise NotFoundError("Evidence not found.")
    _assert_activity_in_scope(record.activity, principal)
    action = data.get("action")
    if action == "accept":
        record.status = "accepted"
        record.activity.evidence_status = "accepted"
    elif action == "return":
        record.status = "returned"
        record.activity.evidence_status = "returned"
    else:
        raise BadRequest("action must be accept or return.")
    record.reviewed_by = principal.user_id
    record.reviewed_at = timezone.now()
    record.review_note = data.get("note")
    record.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    record.activity.save(update_fields=["evidence_status"])
    return _serialize(record)


def prepare_inline_view(record_id: str, principal) -> dict:
    """Trigger/cached PDF rendition for convertible sources (§6 mandate:
    standardized PDF preview). Office docs + spreadsheets convert via
    headless LibreOffice; images via Pillow. The original file is never
    modified — the rendition is a separate sibling file."""
    record = EvidenceRecord.objects.filter(id=record_id).first()
    if not record:
        raise NotFoundError("Evidence not found.")
    _assert_activity_in_scope(record.activity, principal)
    if record.pdf_rendition_storage_key:
        return {
            "previewStatus": "ready",
            "viewKind": "pdf_rendition",
            "renditionId": record.id,
        }
    is_image = (record.mime_type or "").startswith("image/")
    if record.file_extension == ".pdf":
        return {"previewStatus": "ready", "viewKind": "pdf"}
    if record.file_extension not in CONVERTIBLE_EXTENSIONS and not is_image:
        return {"previewStatus": record.preview_status, "viewKind": _view_kind(record)}
    converted = _try_image_to_pdf(record) if is_image else _try_office_to_pdf(record)
    return {
        "previewStatus": "ready" if converted else record.preview_status,
        "viewKind": "pdf_rendition" if converted else _view_kind(record),
        "renditionId": record.id if converted else None,
    }


def _save_rendition(record: EvidenceRecord, pdf_name: str) -> None:
    record.pdf_rendition_storage_key = pdf_name
    record.pdf_rendition_status = "ready"
    record.preview_status = "ready"
    record.pdf_rendition_at = timezone.now()
    record.save(
        update_fields=[
            "pdf_rendition_storage_key",
            "pdf_rendition_status",
            "preview_status",
            "pdf_rendition_at",
        ]
    )


def _fail_rendition(record: EvidenceRecord, error: str) -> None:
    record.preview_status = "failed"
    record.pdf_rendition_error = error[:500]
    record.save(update_fields=["preview_status", "pdf_rendition_error"])


def _try_office_to_pdf(record: EvidenceRecord) -> bool:
    """DOCX/DOC/XLSX/XLS/CSV → PDF via headless LibreOffice (best-effort)."""
    import shutil
    import subprocess

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        _fail_rendition(record, "LibreOffice not installed")
        return False
    src = os.path.join(evidence_dir(), record.uri)
    out_dir = evidence_dir()
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", out_dir, src],
            check=True,
            capture_output=True,
            timeout=60,
        )
        pdf_name = os.path.splitext(record.uri)[0] + ".pdf"
        if os.path.exists(os.path.join(out_dir, pdf_name)):
            _save_rendition(record, pdf_name)
            return True
    except Exception as exc:  # noqa: BLE001
        _fail_rendition(record, str(exc))
    return False


# Kept under its historical name for any external callers/tests.
_try_docx_to_pdf = _try_office_to_pdf


def _try_image_to_pdf(record: EvidenceRecord) -> bool:
    """JPEG/PNG/WebP → single-page PDF via Pillow (best-effort). The image
    keeps rendering natively in thumbnails; this provides the standardized
    PDF view the evidence viewer offers for every document type."""
    try:
        from PIL import Image

        src = os.path.join(evidence_dir(), record.uri)
        pdf_name = os.path.splitext(record.uri)[0] + ".pdf"
        dest = os.path.join(evidence_dir(), pdf_name)
        with Image.open(src) as img:
            img.convert("RGB").save(dest, "PDF")
        _save_rendition(record, pdf_name)
        return True
    except Exception as exc:  # noqa: BLE001
        _fail_rendition(record, str(exc))
        return False


def rendition_for(record_id: str, principal):
    """Stream the cached PDF rendition."""
    record = EvidenceRecord.objects.filter(id=record_id).first()
    if not record or not record.pdf_rendition_storage_key:
        raise NotFoundError("PDF rendition not available.")
    _assert_activity_in_scope(record.activity, principal)
    path = os.path.join(evidence_dir(), record.pdf_rendition_storage_key)
    if not os.path.exists(path):
        raise NotFoundError("Rendition file not found.")
    response = FileResponse(open(path, "rb"), content_type="application/pdf")
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _view_kind(record: EvidenceRecord) -> str:
    if record.file_extension in (".jpg", ".jpeg", ".png", ".webp"):
        return "image"
    if record.file_extension == ".pdf":
        return "pdf"
    if record.file_extension in (".docx", ".doc"):
        return "docx"
    return "download"


def _serialize(e: EvidenceRecord) -> dict:
    return {
        "id": e.id,
        "activityId": e.activity_id,
        "kind": e.kind,
        "originalName": e.original_name,
        "mimeType": e.mime_type,
        "fileExtension": e.file_extension,
        "fileSize": e.file_size,
        "status": e.status,
        "previewStatus": e.preview_status,
        "uploadedBy": e.uploaded_by,
        "uploaderRole": e.uploader_role,
        "viewCount": e.view_count,
        "reviewedBy": e.reviewed_by,
        "reviewNote": e.review_note,
    }
