"""Shared file-storage helper for PD evidence + certificates.

Reuses the platform's upload validation (`assert_safe_upload` — extension,
MIME, and magic-byte checks) and storage convention (uuid-named files under a
configured directory), but writes to its own subdirectory rather than
`EVIDENCE_STORAGE_DIR` — `EvidenceRecord.activity` is a required FK, so PD
files (which have no Activity) cannot go through `evidence.services.record_upload`."""

from __future__ import annotations

import os
import uuid

from django.conf import settings

from apps.core.exceptions import BadRequest
from apps.evidence.validation import assert_safe_upload


def pd_storage_dir() -> str:
    base = getattr(settings, "EVIDENCE_STORAGE_DIR", None) or str(
        settings.BASE_DIR / "uploads" / "evidence"
    )
    d = os.path.join(os.path.dirname(base.rstrip("/")), "professional_development")
    os.makedirs(d, exist_ok=True)
    return d


def _chunks(file_obj, size=1024 * 1024):
    while True:
        chunk = file_obj.read(size)
        if not chunk:
            break
        yield chunk


def store_pd_file(file_obj) -> dict:
    """Validate + persist an uploaded PD file. Returns the fields needed to
    populate a ProfessionalDevelopmentEvidence/Certificate row."""
    if not file_obj:
        raise BadRequest("A file is required.")
    original_name = getattr(file_obj, "name", "upload")
    mime_type = getattr(file_obj, "content_type", "") or ""
    head = file_obj.read(512)
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    ext = assert_safe_upload(
        original_name=original_name, mime_type=mime_type, head=head, size=size
    )
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(pd_storage_dir(), stored_name)
    with open(dest, "wb") as out:
        for chunk in _chunks(file_obj):
            out.write(chunk)
    return {
        "uri": stored_name, "original_name": original_name,
        "mime_type": mime_type or None, "file_extension": ext, "file_size": size,
    }
