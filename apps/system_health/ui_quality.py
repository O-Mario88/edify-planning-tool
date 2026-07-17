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
_ELEMENT_ID = re.compile(r'\bid=["\']([\w:-]+)["\']')
_HTMX_TARGET = re.compile(r'hx-target=["\']#([\w:-]+)["\']')
_EMPTY_HTMX = re.compile(
    r"""hx-(?:get|post|put|patch|delete)=["']\s*["']""", re.I
)
_CLIENT_ONLY_SUCCESS = re.compile(
    r"""<form\b(?:(?!>).)*@submit\.prevent\s*=\s*["'][^"']*alert\s*\(""",
    re.I | re.S,
)
_UNSAFE_INLINE_JSON = re.compile(
    r"""(?:x-data\s*=\s*"[^"]*\{\{[^}]+\|safe\s*\}\}|x-data\s*=\s*'[^']*\{\{[^}]+\|safe\s*\}\})""",
    re.I,
)
_BUTTON = re.compile(r"<button\b[^>]*>", re.I | re.S)
_BUTTON_BEHAVIOR = re.compile(
    r"""(?:hx-(?:get|post|put|patch|delete)
        |@(?:click|change|submit)
        |x-on:
        |type=["'](?:submit|reset)["']
        |\bform=
        |\bdisabled\b
        |\bdata-[\w-]+)""",
    re.I | re.X,
)


def _walk_templates():
    for dirpath, _, files in os.walk(TEMPLATES_DIR):
        for fn in files:
            if fn.endswith(".html"):
                path = os.path.join(dirpath, fn)
                yield (
                    path.replace(str(settings.BASE_DIR) + os.sep, ""),
                    open(path, encoding="utf-8", errors="ignore").read(),
                )


def ui_quality_checks() -> dict:
    from django.urls import Resolver404, resolve

    emoji_files, mock_files, dead_links = [], [], []
    static_series, light_grids, uncompiled = [], [], []
    missing_targets, inert_buttons = [], []
    empty_htmx, client_only_success, unsafe_inline_json = [], [], []

    try:
        compiled_css = open(MAIN_CSS, encoding="utf-8", errors="ignore").read()
    except OSError:
        compiled_css = ""

    templates = list(_walk_templates())
    template_ids = {
        element_id
        for _, source in templates
        for element_id in _ELEMENT_ID.findall(source)
    }

    seen_links: set[str] = set()
    for rel, src in templates:
        if _EMOJI.search(src):
            emoji_files.append(rel)
        if _MOCK.search(src):
            mock_files.append(rel)
        if _STATIC_SERIES.search(src):
            static_series.append(rel)
        if _LIGHT_GRID.search(src):
            light_grids.append(rel)
        if _CLIENT_ONLY_SUCCESS.search(src):
            client_only_success.append(rel)
        if _UNSAFE_INLINE_JSON.search(src):
            unsafe_inline_json.append(rel)
        for match in _EMPTY_HTMX.finditer(src):
            empty_htmx.append((rel, src.count("\n", 0, match.start()) + 1))
        for m in _XL.finditer(src):
            cls = m.group(1)
            escaped = "." + cls.replace(":", "\\:").replace("[", "\\[").replace(
                "]", "\\]"
            ).replace("/", "\\/").replace(".", "\\.")
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
        for target in _HTMX_TARGET.findall(src):
            if target not in template_ids and "components/" not in rel:
                missing_targets.append((rel, f"#{target}"))
        if "templates/components/" not in rel:
            for button in _BUTTON.finditer(src):
                opening_tag = button.group(0)
                # A Django comparison can contain ">" before the HTML tag
                # closes, making a regex-only opening-tag parse ambiguous.
                if "{%" in opening_tag:
                    continue
                if not _BUTTON_BEHAVIOR.search(opening_tag) or _EMPTY_HTMX.search(
                    opening_tag
                ):
                    line = src.count("\n", 0, button.start()) + 1
                    inert_buttons.append((rel, line))

    def check(key, label, items, severity, fix):
        return {
            "key": key,
            "label": label,
            "count": len(items),
            "severity": severity if items else "ok",
            "items": items[:10],
            "fix": fix,
        }

    return {
        "checks": [
            check(
                "mock_smells",
                "Templates with mock/sample data markers",
                mock_files,
                "blocking",
                "Replace with backend data or a premium empty state.",
            ),
            check(
                "emojis",
                "Templates using emojis instead of SVG icons",
                emoji_files,
                "warning",
                "Swap to professional inline SVG line icons (1em, currentColor).",
            ),
            check(
                "dead_links",
                "Static links/HX targets that do not resolve",
                dead_links,
                "blocking",
                "Point the button/link at a registered route or remove it.",
            ),
            check(
                "missing_htmx_targets",
                "HTMX controls targeting a missing element",
                missing_targets,
                "blocking",
                "Target a rendered container or remove the partial-update behavior.",
            ),
            check(
                "inert_buttons",
                "Buttons with no action, form behavior, or disabled state",
                inert_buttons,
                "blocking",
                "Connect the control to a real action or render non-interactive text.",
            ),
            check(
                "empty_htmx_actions",
                "HTMX controls with an empty mutation or navigation URL",
                empty_htmx,
                "blocking",
                "Bind the control to a real authorized endpoint or remove it.",
            ),
            check(
                "client_only_success",
                "Forms that claim success without a server mutation",
                client_only_success,
                "blocking",
                "Submit a validated CSRF-protected request and render server errors.",
            ),
            check(
                "unsafe_inline_json",
                "Backend JSON interpolated directly into Alpine attributes",
                unsafe_inline_json,
                "blocking",
                "Use json_script and parse the payload from a registered component.",
            ),
            check(
                "static_chart_series",
                "Charts with hardcoded numeric series",
                static_series,
                "blocking",
                "Bind ApexCharts series to backend context variables.",
            ),
            check(
                "uncompiled_variants",
                "Responsive classes missing from compiled CSS",
                uncompiled,
                "warning",
                "Rebuild Tailwind or switch to a compiled variant (lg:).",
            ),
            check(
                "light_only_grids",
                "Charts with light-only gridline colors",
                light_grids,
                "warning",
                "Use a translucent gridline (e.g. #94a3b833) readable in both themes.",
            ),
        ],
    }


__all__ = ["ui_quality_checks"]
