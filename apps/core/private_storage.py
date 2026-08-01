"""Private, durable storage for user-uploaded files.

The database stores generated basenames (never public URLs).  This module adds
the domain namespace and routes every operation through Django's
``private_uploads`` storage alias:

* development/tests: ``uploads/<namespace>/...`` on local disk;
* production: private objects in DigitalOcean Spaces.

Callers that need a real path (ClamAV, Pillow, LibreOffice) use
``materialized_file``.  Remote objects are copied into an isolated temporary
directory and removed afterwards.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from contextlib import contextmanager
from typing import Iterator

from django.core.files import File
from django.core.files.storage import storages

from apps.core.exceptions import BadRequest

PRIVATE_STORAGE_ALIAS = "private_uploads"
logger = logging.getLogger(__name__)
_STORED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


def validate_stored_name(stored_name: str, *, label: str = "file") -> str:
    """Accept only generated basenames; separators and traversal are invalid."""
    if not stored_name or not _STORED_NAME_RE.fullmatch(stored_name):
        raise BadRequest(f"Invalid {label} file name.")
    return stored_name


def private_storage():
    return storages[PRIVATE_STORAGE_ALIAS]


def object_key(namespace: str, stored_name: str) -> str:
    if not _NAMESPACE_RE.fullmatch(namespace or ""):
        raise ValueError("Invalid private storage namespace.")
    return f"{namespace}/{validate_stored_name(stored_name)}"


def save_file(namespace: str, stored_name: str, file_obj) -> str:
    """Save under an exact generated key and refuse unexpected key rewriting."""
    key = object_key(namespace, stored_name)
    storage = private_storage()
    if storage.exists(key):
        raise FileExistsError(f"Private object already exists: {key}")
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    saved_key = storage.save(key, file_obj)
    if saved_key != key:
        # UUID keys should never collide.  A rewritten key indicates either a
        # collision or backend behaviour that would desynchronise the DB URI.
        storage.delete(saved_key)
        raise RuntimeError("Storage backend changed the generated object key.")
    return stored_name


def save_local_file(
    namespace: str,
    stored_name: str,
    local_path: str | os.PathLike[str],
) -> str:
    with open(local_path, "rb") as source:
        return save_file(namespace, stored_name, File(source))


def open_file(namespace: str, stored_name: str, mode: str = "rb"):
    return private_storage().open(object_key(namespace, stored_name), mode)


def file_exists(namespace: str, stored_name: str) -> bool:
    return private_storage().exists(object_key(namespace, stored_name))


def delete_file(namespace: str, stored_name: str) -> None:
    private_storage().delete(object_key(namespace, stored_name))


def best_effort_delete(namespace: str, stored_name: str) -> None:
    """Clean up an orphan without hiding the primary failure."""
    try:
        delete_file(namespace, stored_name)
    except Exception:  # noqa: BLE001 -- preserve the original caller exception
        logger.exception(
            "Failed to clean up private object %s after an upstream failure.",
            object_key(namespace, stored_name),
        )


def local_path(namespace: str, stored_name: str) -> str:
    """Return a guarded local path when the configured backend supports it."""
    key = object_key(namespace, stored_name)
    storage = private_storage()
    path = storage.path(key)
    location = getattr(storage, "location", None)
    if not location:
        raise NotImplementedError("Storage backend does not expose local paths.")
    root = os.path.realpath(str(location))
    resolved = os.path.realpath(path)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise BadRequest("Invalid private storage path.")
    return resolved


@contextmanager
def materialized_file(namespace: str, stored_name: str) -> Iterator[str]:
    """Yield a local path for local or remote private objects."""
    try:
        path = local_path(namespace, stored_name)
    except NotImplementedError:
        path = ""
    if path and os.path.exists(path):
        yield path
        return

    suffix = os.path.splitext(stored_name)[1]
    with tempfile.TemporaryDirectory(prefix="edify-private-object-") as tmp_dir:
        destination = os.path.join(tmp_dir, f"source{suffix}")
        with (
            open_file(namespace, stored_name) as source,
            open(destination, "wb") as target,
        ):
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
        yield destination
