"""Runtime health checks for the private upload store."""

from __future__ import annotations

import os
import shutil
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core.private_storage import (
    delete_file,
    file_exists,
    local_path,
    open_file,
    save_file,
)

# Below this many free bytes, evidence uploads are at imminent risk of
# failing mid-write — flag it before that happens, not after.
_LOW_DISK_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB


def evidence_storage_health() -> dict:
    checks = []
    now = timezone.now()
    uses_spaces = getattr(settings, "USE_SPACES_STORAGE", False)
    writable, write_error = _probe_writable()
    checks.append(
        {
            "key": "evidence_storage_writable",
            "severity": "ok" if writable else "critical",
            "component": "Evidence Storage",
            "current_state": (
                "DigitalOcean Spaces read/write/delete probe succeeded"
                if uses_spaces and writable
                else "Local private storage read/write/delete probe succeeded"
                if writable
                else f"Private storage probe failed: {write_error}"
            ),
            "expected_state": "Successful private object write, read, and delete",
            "last_check": now,
            "owner": "Platform/Ops",
            "recommended_action": "OK"
            if writable
            else (
                "Check Spaces credentials, bucket permissions, endpoint, and availability."
                if uses_spaces
                else "Check the local upload directory permissions and disk health."
            ),
            "resolution_link": "/system-health",
        }
    )

    if writable and not uses_spaces:
        storage_dir = os.path.dirname(
            local_path("evidence", "00000000000000000000000000000000.tmp")
        )
        free_bytes = shutil.disk_usage(storage_dir).free
        low = free_bytes < _LOW_DISK_THRESHOLD_BYTES
        checks.append(
            {
                "key": "evidence_storage_disk_space",
                "severity": "critical" if low else "ok",
                "component": "Evidence Storage",
                "current_state": f"{free_bytes // (1024 * 1024)} MB free",
                "expected_state": f"At least {_LOW_DISK_THRESHOLD_BYTES // (1024 * 1024)} MB free",
                "last_check": now,
                "owner": "Platform/Ops",
                "recommended_action": "OK"
                if not low
                else "Free local disk space before uploads start failing.",
                "resolution_link": "/system-health",
            }
        )

    return {"checks": checks}


def _probe_writable() -> tuple[bool, str | None]:
    """Actually write, read, and delete a private object."""
    probe_name = f"health-check-{uuid.uuid4().hex}.tmp"
    try:
        save_file("health", probe_name, ContentFile(b"ok"))
        if not file_exists("health", probe_name):
            raise OSError("probe object was not visible after write")
        with open_file("health", probe_name) as probe:
            if probe.read() != b"ok":
                raise OSError("probe object content did not match")
        delete_file("health", probe_name)
        if file_exists("health", probe_name):
            raise OSError("probe object remained visible after delete")
        return True, None
    except Exception as exc:  # noqa: BLE001 -- health must report, never crash
        try:
            delete_file("health", probe_name)
        except Exception:  # noqa: BLE001
            pass
        return False, str(exc)
