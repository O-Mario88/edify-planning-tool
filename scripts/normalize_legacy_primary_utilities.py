#!/usr/bin/env python3
"""Replace legacy Tailwind blue/indigo utilities with Edify primary states.

The platform previously used framework palette names as its primary visual
language.  This codemod deliberately changes only blue and indigo utilities;
semantic green, amber, red, and information styles remain untouched.  Run it
in ``--check`` mode in CI, or with ``--write`` after deliberately reviewing
new legacy usages.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UTILITY = re.compile(
    r"(?<![\w-])"
    r"(?P<variant>hover:file:|focus-visible:|focus-within:|group-hover:|focus:|hover:|file:)?"
    r"(?P<kind>bg|text|border|ring|outline)-(?:blue|indigo)-"
    r"(?P<shade>\d+)(?:/(?P<alpha>\d+))?"
    r"(?![\w-])"
)


def _base_utility(kind: str, shade: int, alpha: str | None) -> str:
    """Return a semantic class for one unmodified utility."""

    soft = shade <= 200
    if alpha:
        if kind == "bg":
            return f"edify-primary-{'soft-alpha' if soft else 'tint'}-{alpha}"
        if kind == "border":
            return f"edify-primary-border-alpha-{alpha}"
        if kind == "ring":
            return f"edify-primary-ring-{alpha}"
        if kind == "text":
            return f"edify-primary-text-alpha-{alpha}"

    return {
        "bg": "edify-primary-soft" if soft else "edify-primary-solid",
        "text": "edify-primary-on-solid" if shade <= 300 else "edify-primary-text",
        "border": "edify-primary-border",
        "ring": "edify-primary-ring",
        "outline": "edify-primary-focus-visible",
    }[kind]


def _replacement(match: re.Match[str]) -> str:
    variant = match.group("variant") or ""
    kind = match.group("kind")
    shade = int(match.group("shade"))
    alpha = match.group("alpha")
    base = _base_utility(kind, shade, alpha)

    if not variant:
        return base
    if variant in {"focus:", "focus-within:"}:
        return "edify-primary-focus"
    if variant == "focus-visible:":
        return "edify-primary-focus-visible"
    if variant == "group-hover:":
        return (
            "edify-primary-group-hover-soft"
            if kind == "bg"
            else "edify-primary-group-hover-text"
        )
    if variant == "file:":
        return "edify-primary-file-soft" if kind == "bg" else "edify-primary-file-text"
    if variant == "hover:file:":
        return "edify-primary-file-soft-hover"
    if variant == "hover:":
        if kind == "bg":
            return "edify-primary-soft-hover" if shade <= 200 else "edify-primary-hover"
        if kind == "text":
            return "edify-primary-text-hover"
        if kind == "border":
            return "edify-primary-border-hover"
        return base
    raise ValueError(f"Unhandled utility variant: {variant}")


def _frontend_sources() -> list[Path]:
    templates = list((ROOT / "templates").rglob("*.html"))
    browser_code = [
        path
        for directory in (ROOT / "apps", ROOT / "static")
        for pattern in ("*.py", "*.js", "*.ts")
        for path in directory.rglob(pattern)
        if "test" not in path.name
    ]
    return sorted(set(templates + browser_code))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report remaining utilities")
    mode.add_argument("--write", action="store_true", help="migrate matching source files")
    args = parser.parse_args()

    offenders: list[str] = []
    changed: list[Path] = []
    for path in _frontend_sources():
        content = path.read_text(encoding="utf-8")
        migrated, count = UTILITY.subn(_replacement, content)
        if not count:
            continue
        if args.write:
            path.write_text(migrated, encoding="utf-8")
            changed.append(path)
        else:
            offenders.append(f"{path.relative_to(ROOT)} ({count})")

    if args.write:
        print(f"Migrated {len(changed)} files.")
        return 0
    if offenders:
        print("Legacy primary utilities found:\n" + "\n".join(offenders))
        return 1
    print("No legacy blue/indigo primary utilities found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
