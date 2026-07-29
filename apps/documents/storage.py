"""Secure storage and PDF preview for document versions.

The security pipeline is `apps.evidence.validation.assert_safe_upload` -- the
same extension allowlist, declared-MIME check, extension/MIME agreement,
magic-byte sniff and active-content block that evidence uploads pass. Reusing it
is deliberate: two file gates drift, and the weaker one becomes the way in.

Two things are extended rather than copied:

* **Presentations.** Training decks are PPT/PPTX, which evidence never accepts.
  The allowlists are widened here, for this store only, with the same
  magic-byte discipline (PPTX is a zip container, PPT is an OLE compound file).
* **Larger files.** A manual is not a photo of a visit form; the ceiling is
  raised for documents and stays where it is for evidence.

Files never leave through a public URL. `document_path` resolves a stored name
against the store's real path and refuses anything that escapes it, so a bad row
or a careless migration cannot turn a database column into an arbitrary read.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid

from django.conf import settings

from apps.core.exceptions import BadRequest
from apps.evidence.validation import (
    ALLOWED_MIME_TYPES,
    EXTENSION_FAMILY,
    assert_safe_upload,
)

logger = logging.getLogger(__name__)

MAX_DOCUMENT_SIZE = 40 * 1024 * 1024  # 40 MB — manuals and decks are large.

# Presentation formats, on top of everything evidence already permits.
PRESENTATION_MIME_TYPES = {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
PRESENTATION_EXTENSION_FAMILY = {".ppt": ["ole"], ".pptx": ["zip"]}

DOCUMENT_MIME_TYPES = ALLOWED_MIME_TYPES | PRESENTATION_MIME_TYPES
DOCUMENT_EXTENSION_FAMILY = {**EXTENSION_FAMILY, **PRESENTATION_EXTENSION_FAMILY}

#: Sources LibreOffice can turn into a PDF preview.
CONVERTIBLE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

_STORED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def document_dir() -> str:
    directory = getattr(settings, "DOCUMENT_STORAGE_DIR", None) or os.path.join(
        settings.EVIDENCE_STORAGE_DIR, "..", "documents"
    )
    directory = os.path.realpath(directory)
    os.makedirs(directory, exist_ok=True)
    return directory


def document_path(stored_name: str) -> str:
    """Resolve a stored name to an absolute path inside the document store.

    Allow-list the name rather than screening for dangerous characters: a
    deny-list has to anticipate every encoding of "..", an allow-list has to
    anticipate nothing.
    """
    if not stored_name or not _STORED_NAME_RE.match(stored_name):
        raise BadRequest("Invalid document file name.")
    base = os.path.realpath(document_dir())
    resolved = os.path.realpath(os.path.join(base, stored_name))
    if resolved != base and not resolved.startswith(base + os.sep):
        raise BadRequest("Invalid document file name.")
    return resolved


def assert_safe_document_upload(
    *, original_name: str, mime_type: str, head: bytes, size: int
) -> str:
    """Validate a document upload; return its normalised extension.

    One gate, widened -- not a second gate. `assert_safe_upload` performs every
    check (extension allow-list, declared MIME, extension/MIME agreement,
    magic-byte sniff, active-content block); this call tells it how much more
    the Document Library permits than the evidence store does.
    """
    return assert_safe_upload(
        original_name=original_name,
        mime_type=mime_type,
        head=head,
        size=size,
        max_size=MAX_DOCUMENT_SIZE,
        extra_mime_types=frozenset(PRESENTATION_MIME_TYPES),
        extra_extension_family=PRESENTATION_EXTENSION_FAMILY,
    )


def store_upload(file_obj) -> dict:
    """Validate and write an upload. Returns the stored file's facts."""
    if not file_obj:
        raise BadRequest("A file is required.")
    original_name = getattr(file_obj, "name", "upload")
    mime_type = getattr(file_obj, "content_type", "") or ""
    size = getattr(file_obj, "size", 0) or 0

    head = file_obj.read(4096)
    file_obj.seek(0)
    ext = assert_safe_document_upload(
        original_name=original_name, mime_type=mime_type, head=head, size=size
    )

    stored_name = f"{uuid.uuid4().hex}{ext}"
    destination = document_path(stored_name)
    digest = hashlib.sha256()
    with open(destination, "wb") as out:
        for chunk in file_obj.chunks():
            digest.update(chunk)
            out.write(chunk)

    scan_status, detail = _scan(destination)
    return {
        "uri": stored_name,
        "original_filename": original_name[:512],
        "mime_type": mime_type[:128],
        "file_extension": ext,
        "file_size": size,
        "checksum": digest.hexdigest(),
        "scan_status": scan_status,
        "scan_detail": detail or "",
    }


def _scan(path: str) -> tuple[str, str | None]:
    """Malware scan through the same ClamAV path evidence uses.

    Degrades to "skipped", never to "clean": a file that was not scanned must
    never be labelled as though it were.
    """
    from apps.evidence.services import _scan_upload

    try:
        return _scan_upload(path)
    except Exception as exc:  # noqa: BLE001 — a scanner problem is not a bad file
        logger.warning("Document malware scan unavailable (%s): %s", path, exc)
        return "skipped", None


def build_preview(version) -> str:
    """Produce the in-app PDF rendition for a version. Idempotent.

    A conversion failure is recorded and surfaced -- it never rejects an
    otherwise valid document, because a manual that will not convert is still
    a manual people need.
    """
    from django.utils import timezone

    from apps.documents.models import PreviewStatus

    if version.preview_status == PreviewStatus.READY and version.preview_uri:
        return PreviewStatus.READY  # already done; never convert twice

    ext = (version.file_extension or "").lower()
    source = document_path(version.uri)

    def _finish(status, uri="", error="", pages=None):
        version.preview_status = status
        version.preview_uri = uri
        version.preview_error = error[:500]
        version.preview_generated_at = timezone.now()
        if pages:
            version.page_count = pages
        version.save(
            update_fields=[
                "preview_status",
                "preview_uri",
                "preview_error",
                "preview_generated_at",
                "page_count",
                "updated_at",
            ]
        )
        return status

    if ext == ".pdf":
        # Already the target format — the original *is* the preview.
        return _finish(PreviewStatus.READY, uri=version.uri, pages=_page_count(source))

    if ext in IMAGE_EXTENSIONS:
        try:
            from PIL import Image

            pdf_name = os.path.splitext(version.uri)[0] + ".pdf"
            with Image.open(source) as img:
                img.convert("RGB").save(document_path(pdf_name), "PDF")
            return _finish(PreviewStatus.READY, uri=pdf_name, pages=1)
        except Exception as exc:  # noqa: BLE001
            return _finish(PreviewStatus.FAILED, error=str(exc))

    if ext in CONVERTIBLE_EXTENSIONS:
        import shutil
        import subprocess

        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            return _finish(
                PreviewStatus.FAILED,
                error="LibreOffice is not installed on this host.",
            )
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    document_dir(),
                    source,
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )
            pdf_name = os.path.splitext(version.uri)[0] + ".pdf"
            if os.path.exists(document_path(pdf_name)):
                return _finish(
                    PreviewStatus.READY,
                    uri=pdf_name,
                    pages=_page_count(document_path(pdf_name)),
                )
            return _finish(PreviewStatus.FAILED, error="Converter produced no output.")
        except Exception as exc:  # noqa: BLE001
            return _finish(PreviewStatus.FAILED, error=str(exc))

    return _finish(PreviewStatus.NOT_SUPPORTED)


def _page_count(pdf_path: str) -> int | None:
    """Best-effort page count, for the viewer's navigation."""
    try:
        with open(pdf_path, "rb") as fh:
            return fh.read().count(b"/Type /Page") or None
    except Exception:  # noqa: BLE001
        return None
