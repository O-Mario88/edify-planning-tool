"""evidence_storage_health() — System Health checks for persistent evidence
storage (§41: "Storage failure"). Distinct from apps.core.boot_gates'
static-assets boot gate: this is a RUNTIME check (storage can fail after a
clean boot — a volume unmounting, permissions changing, disk filling up),
wired into apps.system_health.services.report() as data["evidenceStorage"].
"""

from __future__ import annotations

import os
import shutil
import uuid

from django.conf import settings
from django.utils import timezone

# Below this many free bytes, evidence uploads are at imminent risk of
# failing mid-write — flag it before that happens, not after.
_LOW_DISK_THRESHOLD_BYTES = 500 * 1024 * 1024  # 500 MB


def evidence_storage_health() -> dict:
    checks = []
    now = timezone.now()
    storage_dir = getattr(settings, "EVIDENCE_STORAGE_DIR", None)

    if not storage_dir:
        checks.append(
            {
                "key": "evidence_storage_configured",
                "severity": "critical",
                "component": "Evidence Storage",
                "current_state": "EVIDENCE_STORAGE_DIR is not set",
                "expected_state": "An absolute, persistent path",
                "last_check": now,
                "owner": "Platform/Ops",
                "recommended_action": "Set EVIDENCE_STORAGE_DIR to a mounted, persistent volume.",
                "resolution_link": "/system-health",
            }
        )
        return {"checks": checks}

    writable, write_error = _probe_writable(storage_dir)
    checks.append(
        {
            "key": "evidence_storage_writable",
            "severity": "ok" if writable else "critical",
            "component": "Evidence Storage",
            "current_state": f"Writable ({storage_dir})"
            if writable
            else f"NOT writable ({storage_dir}): {write_error}",
            "expected_state": "Read/write access to EVIDENCE_STORAGE_DIR",
            "last_check": now,
            "owner": "Platform/Ops",
            "recommended_action": "OK"
            if writable
            else "Check the mounted volume, directory permissions, and disk health.",
            "resolution_link": "/system-health",
        }
    )

    if writable:
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
                else "Free up space or expand the evidence volume before uploads start failing.",
                "resolution_link": "/system-health",
            }
        )

    return {"checks": checks}


def _probe_writable(storage_dir: str) -> tuple[bool, str | None]:
    """Actually attempt a write + delete, rather than just checking
    os.access() — the latter can be wrong under some filesystem/permission
    combinations (e.g. containers, network mounts)."""
    probe_path = os.path.join(storage_dir, f".health-check-{uuid.uuid4().hex}")
    try:
        os.makedirs(storage_dir, exist_ok=True)
        with open(probe_path, "wb") as f:
            f.write(b"ok")
        os.remove(probe_path)
        return True, None
    except OSError as exc:
        return False, str(exc)
