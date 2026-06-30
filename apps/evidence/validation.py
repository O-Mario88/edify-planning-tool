"""
Secure file-upload validation — port of file-validation.ts.

Defence in depth: an upload must pass ALL of —
  1) extension allowlist
  2) declared-MIME allowlist
  3) extension <-> declared-MIME agree
  4) magic-byte sniff of real bytes
  5) active-content / executable block
We never trust the client-supplied filename or Content-Type alone.
"""
from __future__ import annotations

import os

from apps.core.exceptions import BadRequest


ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/heic",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    # Browsers sometimes send a generic type for .docx/.xlsx — allowed at the
    # MIME gate, but the magic-byte sniff still pins it to a real signature.
    "application/octet-stream",
}

# Extension -> the content families its bytes are allowed to be.
EXTENSION_FAMILY = {
    ".jpg": ["jpeg"], ".jpeg": ["jpeg"], ".png": ["png"], ".webp": ["webp"],
    ".heic": ["heic"], ".pdf": ["pdf"], ".doc": ["ole"], ".docx": ["zip"],
    ".xls": ["ole"], ".xlsx": ["zip"], ".csv": ["text"],
}

BLOCKED_EXTENSIONS = {".svg", ".html", ".htm", ".xhtml", ".xml", ".js", ".mjs",
                      ".exe", ".bat", ".cmd", ".sh", ".php", ".py", ".jar",
                      ".zip", ".tar", ".gz", ".7z", ".rar"}  # archives blocked as evidence

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# Magic-byte signatures (offset, bytes).
_SIGNATURES = {
    "jpeg": [(0, b"\xff\xd8\xff")],
    "png": [(0, b"\x89PNG\r\n\x1a\n")],
    "pdf": [(0, b"%PDF")],
    "zip": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    "ole": [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
}


def _detect_families(head: bytes) -> list[str]:
    found = []
    for family, sigs in _SIGNATURES.items():
        for offset, sig in sigs:
            if head[offset:offset + len(sig)] == sig:
                found.append(family)
                break
    # Heuristic text detection.
    if not found and head[:64].strip(b"\x00") and not head[:1].isdigit():
        try:
            head[:64].decode("ascii")
            found.append("text")
        except UnicodeDecodeError:
            pass
    return found


def assert_safe_upload(*, original_name: str, mime_type: str, head: bytes, size: int) -> str:
    """Validate an upload. Returns the normalized extension. Raises BadRequest on
    any failure."""
    if size > MAX_FILE_SIZE:
        raise BadRequest("File exceeds the 10 MB limit.")
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise BadRequest(f"File type '{ext}' is not allowed.")
    if ext not in EXTENSION_FAMILY:
        raise BadRequest(f"File extension '{ext or '(none)'}' is not allowed.")
    if mime_type and mime_type not in ALLOWED_MIME_TYPES:
        raise BadRequest(f"Declared content type '{mime_type}' is not allowed.")
    # Gate 3: extension <-> declared-MIME must agree. A .pdf claiming image/png
    # is rejected. octet-stream is exempt (browsers send it generically).
    if mime_type and mime_type != "application/octet-stream":
        _assert_mime_matches_ext(mime_type, ext)
    # Gate 4: magic-byte sniff of real bytes.
    expected_families = EXTENSION_FAMILY[ext]
    actual = _detect_families(head[:512])
    if not any(f in expected_families for f in actual):
        raise BadRequest("The file content does not match its declared type.")
    return ext


# Map declared MIME -> the extensions it may legitimately accompany.
_MIME_TO_EXTS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/heic": {".heic"},
    "application/pdf": {".pdf"},
    "application/msword": {".doc"},
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
    "application/vnd.ms-excel": {".xls"},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
    "text/csv": {".csv"},
}


def _assert_mime_matches_ext(mime_type: str, ext: str) -> None:
    allowed_exts = _MIME_TO_EXTS.get(mime_type)
    if allowed_exts is not None and ext not in allowed_exts:
        raise BadRequest(
            f"The file extension '{ext}' does not match its declared type '{mime_type}'."
        )


__all__ = ["ALLOWED_MIME_TYPES", "MAX_FILE_SIZE", "assert_safe_upload"]
