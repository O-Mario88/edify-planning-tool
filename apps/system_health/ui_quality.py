"""UI quality-control checks (Gold Standard mandate §24).

Static lints computed live from the actual template/CSS source — the same
rules enforced during the design-system pass, kept as permanent regression
guards: mock-data smells, emojis, dead static links, uncompiled responsive
variants, static chart series and un-themed inline hex.
"""

from __future__ import annotations

import os
import re

from django.conf import settings

TEMPLATES_DIR = os.path.join(settings.BASE_DIR, "templates")
MAIN_CSS = os.path.join(settings.BASE_DIR, "static", "css", "main.css")

_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
_MOCK = re.compile(r">\s*(?:Lorem|John Doe|Jane Doe|N\d{2,3}M|\$[\d,]+)\s*<", re.I)
_LINK = re.compile(r'(?:href|hx-get|hx-post)="(/[a-z0-9\-_/]*?)(?:[?#][^"]*)?"')
_XL = re.compile(r"\b((?:2xl|xl):[a-z0-9\-\[\]/.]+)")
# ApexCharts series built from literal numbers instead of template variables.
_STATIC_SERIES = re.compile(r"data:\s*\[\s*\d+\s*(?:,\s*\d+\s*){2,}\]")
_LIGHT_GRID = re.compile(r"borderColor:\s*'#f[0-9a-f]{5}'")


def _walk_templates():
    for dirpath, _, files in os.walk(TEMPLATES_DIR):
        for fn in files:
            if fn.endswith(".html"):
                path = os.path.join(dirpath, fn)
                yield path.replace(str(settings.BASE_DIR) + os.sep, ""), open(
                    path, encoding="utf-8", errors="ignore"
                ).read()


def ui_quality_checks() -> dict:
    from django.urls import Resolver404, resolve

    emoji_files, mock_files, dead_links = [], [], []
    static_series, light_grids, uncompiled = [], [], []

    try:
        compiled_css = open(MAIN_CSS, encoding="utf-8", errors="ignore").read()
    except OSError:
        compiled_css = ""

    seen_links: set[str] = set()
    for rel, src in _walk_templates():
        if _EMOJI.search(src):
            emoji_files.append(rel)
        if _MOCK.search(src):
            mock_files.append(rel)
        if _STATIC_SERIES.search(src):
            static_series.append(rel)
        if _LIGHT_GRID.search(src):
            light_grids.append(rel)
        for m in _XL.finditer(src):
            cls = m.group(1)
            escaped = "." + cls.replace(":", "\\:").replace("[", "\\[").replace(
                "]", "\\]").replace("/", "\\/").replace(".", "\\.")
            if compiled_css and escaped not in compiled_css:
                uncompiled.append((rel, cls))
        for m in _LINK.finditer(src):
            url = m.group(1)
            if url in seen_links or url in ("/", "/logout"):
                continue
            seen_links.add(url)
            try:
                resolve(url or "/")
            except Resolver404:
                # Documentation examples inside component docstrings are not
                # rendered links.
                if "components/" not in rel:
                    dead_links.append((rel, url))

    def check(key, label, items, severity, fix):
        return {
            "key": key, "label": label, "count": len(items),
            "severity": severity if items else "ok",
            "items": items[:10], "fix": fix,
        }

    return {
        "checks": [
            check("mock_smells", "Templates with mock/sample data markers",
                  mock_files, "blocking",
                  "Replace with backend data or a premium empty state."),
            check("emojis", "Templates using emojis instead of SVG icons",
                  emoji_files, "warning",
                  "Swap to professional inline SVG line icons (1em, currentColor)."),
            check("dead_links", "Static links/HX targets that do not resolve",
                  dead_links, "blocking",
                  "Point the button/link at a registered route or remove it."),
            check("static_chart_series", "Charts with hardcoded numeric series",
                  static_series, "blocking",
                  "Bind ApexCharts series to backend context variables."),
            check("uncompiled_variants", "Responsive classes missing from compiled CSS",
                  uncompiled, "warning",
                  "Rebuild Tailwind or switch to a compiled variant (lg:)."),
            check("light_only_grids", "Charts with light-only gridline colors",
                  light_grids, "warning",
                  "Use a translucent gridline (e.g. #94a3b833) readable in both themes."),
        ],
    }


__all__ = ["ui_quality_checks"]
