"""
Evidence service — the file pipeline: secure upload, list, hardened file
serving, accept/return review, and on-demand DOCX→PDF rendition.

Files are stored through the private-upload backend (local disk in development,
DigitalOcean Spaces in production). Downloads send hardened headers and
object-authorize the parent activity. A quarantined file is never downloadable.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.utils.http import content_disposition_header
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import EvidenceKind, EvidenceStatus
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.private_storage import (
    best_effort_delete,
    file_exists,
    local_path,
    materialized_file,
    open_file,
    save_file,
    save_local_file,
    validate_stored_name,
)
from apps.core.scoping import resolve_user_scope

from .models import EvidenceRecord
from .validation import assert_safe_upload


VALID_KINDS = {k.value for k in EvidenceKind}
# Sources that can be converted into the standardized PDF preview (images are
# handled separately via Pillow; see prepare_inline_view).
CONVERTIBLE_EXTENSIONS = {".docx", ".doc", ".xlsx", ".xls", ".csv"}
logger = logging.getLogger(__name__)
EVIDENCE_NAMESPACE = "evidence"


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
    """Compatibility path for local development and path-containment tests."""
    directory = os.path.dirname(
        local_path(EVIDENCE_NAMESPACE, "00000000000000000000000000000000.tmp")
    )
    os.makedirs(directory, exist_ok=True)
    return directory


def evidence_path(stored_name: str) -> str:
    """Resolve a stored file name to an absolute path inside the store.

    Every read and write of an evidence file goes through here. Stored names
    are generated — a uuid4 hex plus an extension taken from an allowlist — so
    this should never reject anything in practice. But the name round-trips
    through a database column, and a path assembled by joining a column onto a
    directory is one bad row or one careless migration away from reading
    anything the process can reach.

    The name is validated against an allowlist rather than screened for the
    characters that would be dangerous: a deny-list has to anticipate every
    encoding of "..", and an allow-list has to anticipate nothing. Separators,
    parent references and a leading dot are all absent from the pattern, so
    none of them can appear. The containment re-check after symlink resolution
    stays as a second, independent barrier.
    """
    validate_stored_name(stored_name, label="evidence")
    return local_path(EVIDENCE_NAMESPACE, stored_name)


def resolve_evidence_kind(file_obj, activity=None, asserted: str | None = None) -> str:
    """What this upload is, for the completion requirement to read.

    Order of trust:

    1. What the person said it is, if they said anything valid.
    2. What the activity type requires — the platform already knows a school
       visit needs a Visit Form, so it should not make someone tell it.
    3. The file's own shape, which only ever distinguishes a PDF from a photo.

    Step 2 is the one that was missing, and its absence made completion
    impossible. `infer_kind_from_upload` can only return PDF or PHOTO, while
    every requirement asks for a purpose — visit form, attendance form, meeting
    minutes. There is no overlap, so for all 20 activity types carrying a
    requirement the gate could never be satisfied: upload the right document,
    get "Required evidence missing: Visit Form", forever.
    """
    valid = {choice for choice, _label in EvidenceKind.choices}
    if asserted and asserted in valid:
        return asserted

    if activity is not None:
        from apps.evidence.requirements import missing_evidence_kinds

        outstanding = missing_evidence_kinds(activity)
        if outstanding:
            # Fill the first gap the activity still has. Someone uploading a
            # document to an activity that is asking for one is almost always
            # uploading that one.
            return outstanding[0]["kind"]

    return infer_kind_from_upload(file_obj)


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

    # Persist through the private storage backend under a unique filename.
    stored_name = f"{uuid.uuid4().hex}{ext}"
    save_file(EVIDENCE_NAMESPACE, stored_name, file_obj)
    try:
        with materialized_file(EVIDENCE_NAMESPACE, stored_name) as local_file:
            scan_status, threat_name = _scan_upload(local_file)
    except Exception:
        best_effort_delete(EVIDENCE_NAMESPACE, stored_name)
        raise

    if scan_status == "infected":
        # Keep the record + quarantined file on disk for security review
        # (file_for() already refuses to serve anything quarantined), but
        # never let it become usable evidence or advance the activity.
        try:
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
                storage_provider=_storage_provider_name(),
            )
        except Exception:
            best_effort_delete(EVIDENCE_NAMESPACE, stored_name)
            raise
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

    try:
        with transaction.atomic():
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
                storage_provider=_storage_provider_name(),
            )
            activity.evidence_status = "uploaded"
            activity.save(update_fields=["evidence_status", "updated_at"])
    except Exception:
        best_effort_delete(EVIDENCE_NAMESPACE, stored_name)
        raise
    return _serialize(record)


def _chunks(file_obj, chunk_size=64 * 1024):
    file_obj.seek(0)
    while True:
        data = file_obj.read(chunk_size)
        if not data:
            break
        yield data


def _storage_provider_name() -> str:
    return "spaces" if getattr(settings, "USE_SPACES_STORAGE", False) else "local"


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
    if not file_exists(EVIDENCE_NAMESPACE, record.uri):
        raise NotFoundError("File not found in private storage.")
    record.view_count += 1
    record.save(update_fields=["view_count"])
    response = FileResponse(
        open_file(EVIDENCE_NAMESPACE, record.uri),
        content_type=record.mime_type or "application/octet-stream",
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
    response["Content-Disposition"] = content_disposition_header(
        disposition == "attachment", record.original_name or record.uri
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
    try:
        with (
            materialized_file(EVIDENCE_NAMESPACE, record.uri) as src,
            tempfile.TemporaryDirectory(prefix="edify-evidence-preview-") as out_dir,
        ):
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    out_dir,
                    src,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            generated = os.path.join(
                out_dir, os.path.splitext(os.path.basename(src))[0] + ".pdf"
            )
            pdf_name = os.path.splitext(record.uri)[0] + ".pdf"
            if os.path.exists(generated):
                save_local_file(EVIDENCE_NAMESPACE, pdf_name, generated)
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

        pdf_name = os.path.splitext(record.uri)[0] + ".pdf"
        with (
            materialized_file(EVIDENCE_NAMESPACE, record.uri) as src,
            tempfile.TemporaryDirectory(prefix="edify-evidence-preview-") as tmp_dir,
        ):
            dest = os.path.join(tmp_dir, "preview.pdf")
            with Image.open(src) as img:
                img.convert("RGB").save(dest, "PDF")
            save_local_file(EVIDENCE_NAMESPACE, pdf_name, dest)
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
    if not file_exists(EVIDENCE_NAMESPACE, record.pdf_rendition_storage_key):
        raise NotFoundError("Rendition file not found.")
    response = FileResponse(
        open_file(EVIDENCE_NAMESPACE, record.pdf_rendition_storage_key),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = content_disposition_header(False, "preview.pdf")
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
