#!/usr/bin/env python3
"""Move repeated static Edify token declarations out of template style attrs.

Only complete, static declarations are converted. Dynamic data visualisations,
Alpine FOUC guards, custom properties, and per-record widths intentionally
remain inline because CSS classes cannot safely represent their runtime value.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STYLE_ATTRIBUTE = re.compile(
    r"(?P<open><[A-Za-z][^>]*?)(?P<space>\s+)style=\"(?P<style>[^{}\"]*)\"",
    re.DOTALL,
)
CLASS_ATTRIBUTE = re.compile(r'class="(?P<classes>[^"]*)"')


DECLARATIONS = {
    "background:var(--edify-surface)": ("edify-surface",),
    "background-color:var(--edify-surface)": ("edify-surface",),
    "background:var(--edify-surface-muted)": ("edify-surface-muted",),
    "background-color:var(--edify-surface-muted)": ("edify-surface-muted",),
    "background:var(--edify-surface-raised)": ("edify-surface-raised",),
    "background-color:var(--edify-surface-raised)": ("edify-surface-raised",),
    "background:var(--edify-primary)": ("edify-primary-solid",),
    "background-color:var(--edify-primary)": ("edify-primary-solid",),
    "background:var(--edify-accent)": ("edify-primary-solid",),
    "background-color:var(--edify-accent)": ("edify-primary-solid",),
    "background:var(--edify-primary-hover)": ("edify-primary-solid",),
    "background-color:var(--edify-primary-hover)": ("edify-primary-solid",),
    "background:var(--edify-accent-light)": ("edify-primary-soft",),
    "background-color:var(--edify-accent-light)": ("edify-primary-soft",),
    "background:var(--edify-success-light)": ("edify-success-soft",),
    "background-color:var(--edify-success-light)": ("edify-success-soft",),
    "background:var(--edify-warning-light)": ("edify-warning-soft",),
    "background-color:var(--edify-warning-light)": ("edify-warning-soft",),
    "background:var(--edify-danger-light)": ("edify-danger-soft",),
    "background-color:var(--edify-danger-light)": ("edify-danger-soft",),
    "background:var(--edify-info-light)": ("edify-info-soft",),
    "background-color:var(--edify-info-light)": ("edify-info-soft",),
    "color:var(--edify-text)": ("edify-text",),
    "color:var(--edify-text-muted)": ("edify-text-muted",),
    "color:var(--edify-text-subtle)": ("edify-text-subtle",),
    "color:var(--edify-accent)": ("edify-primary-text",),
    "color:var(--edify-accent,var(--edify-chart-blue))": ("edify-primary-text",),
    "color:var(--edify-primary-active)": ("edify-primary-text",),
    "color:var(--edify-on-accent)": ("edify-primary-on-solid",),
    "color:var(--edify-success)": ("edify-success-text",),
    "color:var(--edify-warning)": ("edify-warning-text",),
    "color:var(--edify-danger)": ("edify-danger-text",),
    "color:var(--edify-info)": ("edify-info-text",),
    "border-color:var(--edify-border)": ("edify-border",),
    "border-color:var(--edify-border-strong)": ("edify-border-strong",),
    "border-color:var(--edify-success-border)": ("edify-success-border",),
    "border-color:var(--edify-warning-border)": ("edify-warning-border",),
    "border-color:var(--edify-danger-border)": ("edify-danger-border",),
    "border-color:var(--edify-info-border)": ("edify-info-border",),
    "border:1pxsolidvar(--edify-border)": ("border", "edify-border"),
    "border:1pxsolidvar(--edify-success-border)": ("border", "edify-success-border"),
    "border:1pxsolidvar(--edify-warning-border)": ("border", "edify-warning-border"),
    "border:1pxsolidvar(--edify-danger-border)": ("border", "edify-danger-border"),
    "border:1pxsolidvar(--edify-info-border)": ("border", "edify-info-border"),
    "border-top:1pxsolidvar(--edify-border)": ("border-t", "edify-border-top"),
    "border-bottom:1pxsolidvar(--edify-border)": ("border-b", "edify-border-bottom"),
    "box-shadow:var(--edify-shadow-sm)": ("edify-shadow-sm",),
    "box-shadow:var(--edify-shadow-md)": ("edify-shadow-md",),
    "font-variant-numeric:tabular-nums": ("tabular-nums",),
    "text-align:center": ("text-center",),
    "text-align:right": ("text-right",),
}


def _normalise(declaration: str) -> str:
    property_name, value = declaration.split(":", 1)
    normalised_value = re.sub(r"\s+", "", value).lower().replace("!important", "")
    return f"{property_name.strip().lower()}:{normalised_value}"


def _with_classes(open_tag: str, classes: list[str]) -> str:
    class_match = CLASS_ATTRIBUTE.search(open_tag)
    if class_match:
        existing = class_match.group("classes").split()
        merged = " ".join(dict.fromkeys([*existing, *classes]))
        return (
            open_tag[: class_match.start("classes")]
            + merged
            + open_tag[class_match.end("classes") :]
        )
    return open_tag + ' class="' + " ".join(classes) + '"'


def _migrate_attribute(match: re.Match[str]) -> str:
    open_tag = match.group("open")
    style = match.group("style")
    declarations = [part.strip() for part in style.split(";") if part.strip()]
    migrated_classes: list[str] = []
    remaining: list[str] = []

    has_primary_surface = any(
        _normalise(declaration)
        in {
            "background:var(--edify-primary)",
            "background-color:var(--edify-primary)",
            "background:var(--edify-accent)",
            "background-color:var(--edify-accent)",
            "background:var(--edify-primary-hover)",
            "background-color:var(--edify-primary-hover)",
        }
        for declaration in declarations
        if ":" in declaration
    )

    for declaration in declarations:
        if ":" not in declaration:
            remaining.append(declaration)
            continue
        if (
            has_primary_surface
            and _normalise(declaration) == "color:var(--edify-surface-raised)"
        ):
            migrated_classes.append("edify-primary-on-solid")
            continue
        replacement = DECLARATIONS.get(_normalise(declaration))
        if replacement:
            migrated_classes.extend(replacement)
        else:
            remaining.append(declaration)

    if not migrated_classes:
        return match.group(0)

    updated = _with_classes(open_tag, migrated_classes)
    if remaining:
        return f'{updated}{match.group("space")}style="{"; ".join(remaining)}"'
    return updated


def _template_files() -> list[Path]:
    return sorted((ROOT / "templates").rglob("*.html"))


def _migrate_markup(markup: str) -> tuple[str, int]:
    migrated = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal migrated
        replacement = _migrate_attribute(match)
        if replacement != match.group(0):
            migrated += 1
        return replacement

    return STYLE_ATTRIBUTE.sub(replace, markup), migrated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report remaining transformable styles")
    mode.add_argument("--write", action="store_true", help="migrate transformable styles")
    args = parser.parse_args()

    remaining: list[str] = []
    changed: list[Path] = []
    for path in _template_files():
        markup = path.read_text(encoding="utf-8")
        updated, count = _migrate_markup(markup)
        if not count:
            continue
        if args.write:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
        else:
            remaining.append(f"{path.relative_to(ROOT)} ({count})")

    if args.write:
        print(f"Migrated {len(changed)} templates.")
        return 0
    if remaining:
        print("Transformable inline token styles found:\n" + "\n".join(remaining))
        return 1
    print("No transformable static token styles found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
