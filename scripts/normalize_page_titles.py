#!/usr/bin/env python3
"""Give every route-level H1 the shared Edify page-title contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
H1 = re.compile(r"<h1(?P<attributes>\s[^>]*)?>", re.IGNORECASE)
CLASS = re.compile(r'class="(?P<classes>[^"]*)"')


def _replace(match: re.Match[str]) -> str:
    attributes = match.group("attributes") or ""
    if "edify-page-title" in attributes:
        return match.group(0)
    class_match = CLASS.search(attributes)
    if class_match:
        classes = " ".join(
            dict.fromkeys([*class_match.group("classes").split(), "edify-page-title"])
        )
        attributes = (
            attributes[: class_match.start("classes")]
            + classes
            + attributes[class_match.end("classes") :]
        )
    else:
        attributes += ' class="edify-page-title"'
    return f"<h1{attributes}>"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()

    missing: list[str] = []
    changed: list[Path] = []
    for path in sorted((ROOT / "templates/pages").rglob("*.html")):
        markup = path.read_text(encoding="utf-8")
        updated, count = H1.subn(_replace, markup)
        if not count:
            continue
        if updated == markup:
            continue
        if args.write:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
        else:
            missing.append(path.relative_to(ROOT).as_posix())

    if args.write:
        print(f"Normalized {len(changed)} route templates.")
        return 0
    if missing:
        print("Page titles missing the shared class:\n" + "\n".join(missing))
        return 1
    print("Every route-level H1 uses edify-page-title.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
