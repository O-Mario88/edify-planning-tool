"""What artifact is this process actually running?

Nothing could answer that. The image carried no commit, no build time, and no
way to identify the static bundle it was serving, so "did the approved design
reach production?" could only be answered by looking at the page and forming an
opinion. That is how a stale release survives: not because anyone believes the
old build is current, but because there is no cheap way to prove it isn't.

Three facts, in falling order of availability:

* ``static_manifest_hash`` — a digest of the staticfiles manifest baked in at
  image build. Always present, needs no build argument and no CI cooperation,
  and it is the fact that matters most here: two images with the same manifest
  hash serve byte-identical CSS and JavaScript. This alone answers "is
  production serving the bundle I built?".
* ``build_time`` — when the image was built. Always present.
* ``commit`` / ``release`` — passed as Docker build arguments when the builder
  supplies them. Deliberately optional: DigitalOcean App Platform builds this
  Dockerfile without forwarding a commit SHA, so a design that *required* one
  would report "unknown" in the only environment that matters. They are
  reported when known and never fabricated.

Read once at import and cached: this is on the health path, and re-reading a
file per request to answer a question whose answer cannot change within the
life of a process would be its own defect.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("edify.build")

#: Written by the Dockerfile after collectstatic. Absent in local development,
#: which is not an error — it means "not built as an image".
BUILD_INFO_PATH = Path("/app/build-info.json")

UNKNOWN = "unknown"


def static_manifest_digest(manifest: Path) -> str:
    """Hash the manifest's meaning, independent of JSON serialization order.

    Django builds the same ``paths`` mapping with different key insertion
    orders under local Docker and DigitalOcean's Kaniko builder. Hashing the
    raw bytes therefore produced different release identities for identical
    static bundles. Canonical JSON makes this a semantic artifact digest.
    """

    data = json.loads(manifest.read_text(encoding="utf-8"))
    canonical = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


@lru_cache(maxsize=1)
def build_info() -> dict:
    """Provenance for the running artifact. Never raises, never guesses."""
    data: dict = {}
    try:
        if BUILD_INFO_PATH.exists():
            data = json.loads(BUILD_INFO_PATH.read_text())
    except Exception as exc:  # noqa: BLE001 — provenance must not break health
        logger.error("Could not read build info: %s", exc)
        data = {}

    return {
        # App Platform exposes the source revision as a runtime bindable for
        # services. Dockerfile builds cannot consume bindables as build args,
        # so prefer the image value when a CI builder supplied one and fall
        # back to the platform's exact deployed commit at runtime.
        "commit": data.get("commit") or os.environ.get("GIT_COMMIT") or UNKNOWN,
        # DigitalOcean's Dockerfile builder does not forward build arguments,
        # but App Platform can inject an immutable release identifier at
        # runtime.  Prefer the image value when CI supplied it, then fall back
        # to that platform value instead of publishing a misleading
        # ``unknown`` release for the production deployment.
        "release": data.get("release") or os.environ.get("RELEASE") or UNKNOWN,
        "buildTime": data.get("build_time") or UNKNOWN,
        "staticManifestHash": data.get("static_manifest_hash") or _live_manifest_hash(),
        "builtImage": bool(data),
    }


def _live_manifest_hash() -> str:
    """Fall back to hashing the manifest that is actually on disk.

    Used when running outside a built image (local, tests, a management
    command). It
    is the same computation the build performs, so a developer can compare
    their tree against production without building an image first.
    """
    from django.conf import settings

    try:
        manifest = Path(settings.STATIC_ROOT) / "staticfiles.json"
        if not manifest.exists():
            return UNKNOWN
        return static_manifest_digest(manifest)
    except Exception:  # noqa: BLE001
        return UNKNOWN


def asset_hash(path: str) -> str | None:
    """The hashed filename the manifest maps ``path`` to, or None.

    ``path`` is the logical name, e.g. ``css/design-system.css``. This is what
    a release check compares against what production actually serves.
    """
    import hashlib  # noqa: F401  (kept local; see _live_manifest_hash)

    from django.conf import settings

    try:
        manifest = Path(settings.STATIC_ROOT) / "staticfiles.json"
        if not manifest.exists():
            return None
        return json.loads(manifest.read_text())["paths"].get(path)
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "build_info",
    "asset_hash",
    "static_manifest_digest",
    "BUILD_INFO_PATH",
    "UNKNOWN",
]
