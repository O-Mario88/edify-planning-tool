"""Write immutable release provenance into a built application image.

Keep this as a regular Python file instead of an inline Dockerfile heredoc.
DigitalOcean App Platform builds Dockerfiles with Kaniko, whose handling of
heredoc ``RUN`` instructions differs from the local Docker/BuildKit path.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from apps.core.build_info import static_manifest_digest


def write_build_info(manifest: Path, output: Path) -> dict[str, str]:
    """Hash the collected-static manifest and write the image identity."""

    digest = static_manifest_digest(manifest)
    payload = {
        "commit": os.environ.get("GIT_COMMIT") or "",
        "release": os.environ.get("RELEASE") or "",
        "build_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "static_manifest_hash": digest,
    }
    output.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("/app/staticfiles/staticfiles.json"),
    )
    parser.add_argument("--output", type=Path, default=Path("/app/build-info.json"))
    args = parser.parse_args()

    payload = write_build_info(args.manifest, args.output)
    print(
        "build-info.json written: "
        f"manifest={payload['static_manifest_hash']} output={args.output}"
    )


if __name__ == "__main__":
    main()
