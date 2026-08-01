"""UI quality-control checks (Gold Standard mandate §24).

Static lints computed live from the actual template/CSS source — the same
rules enforced during the design-system pass, kept as permanent regression
guards: mock-data smells, emojis, dead static links, uncompiled responsive
variants, utilities that resolve to no rule at all, static chart series and
un-themed inline hex.
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
_XL = re.compile(r"\b((?:max-)?(?:2xl|xl):[a-z0-9\-\[\]/.]+)")

# `_XL` only ever inspects variant-prefixed classes, so a plain utility that was
# never compiled — `min-w-[170px]`, `scroll-mt-4`, `py-0.2` — passed straight
# through it. These three find those: pull every utility out of a class
# attribute, then confirm it resolves to a real rule.
_CLASS_ATTR = re.compile(r"""\bclass=["']([^"']*)["']""")
#: `text-[11px]`, `lg:grid-cols-[210px_minmax(0,1fr)]`, `bg-black/[.06]`.
_ARBITRARY_UTILITY = re.compile(r"^[A-Za-z0-9:_./-]*-\[[^\]]+\][A-Za-z0-9/._-]*$")
#: `pb-5`, `min-w-10`, `py-0.5` — a scale step, which may or may not exist.
_SCALE_UTILITY = re.compile(r"^(?:[a-z0-9-]+:)*([a-z]+(?:-[a-z]+)*)-(\d+(?:\.\d+)?)$")
#: A class selector in compiled CSS, with its escapes (`.min-w-\[170px\]`).
_CSS_CLASS = re.compile(r"\.((?:\\.|[A-Za-z0-9_-])+)")

#: Utilities whose trailing number indexes a spacing/sizing scale. Restricted to
#: this list because a bare `foo-2` is far more likely to be a hand-written
#: class than a Tailwind one, and a lint that cries wolf gets switched off.
_SCALE_PREFIXES = frozenset(
    """
    p px py pt pr pb pl ps pe
    m mx my mt mr mb ml ms me
    gap gap-x gap-y space-x space-y
    w h size min-w min-h max-w max-h
    top right bottom left inset inset-x inset-y
    scroll-m scroll-mt scroll-mr scroll-mb scroll-ml
    scroll-p scroll-pt scroll-pr scroll-pb scroll-pl
    translate-x translate-y basis indent
    border border-t border-r border-b border-l
    rounded leading z order opacity duration delay
    grid-cols col-span grid-rows row-span
    """.split()
)
# ApexCharts series built from literal numbers instead of template variables.
_STATIC_SERIES = re.compile(r"data:\s*\[\s*\d+\s*(?:,\s*\d+\s*){2,}\]")
_LIGHT_GRID = re.compile(r"borderColor:\s*'#f[0-9a-f]{5}'")
_ELEMENT_ID = re.compile(r'\bid=["\']([\w:-]+)["\']')
_HTMX_TARGET = re.compile(r'hx-target=["\']#([\w:-]+)["\']')
_EMPTY_HTMX = re.compile(r"""hx-(?:get|post|put|patch|delete)=["']\s*["']""", re.I)
_CLIENT_ONLY_SUCCESS = re.compile(
    r"""<form\b(?:(?!>).)*@submit\.prevent\s*=\s*["'][^"']*alert\s*\(""",
    re.I | re.S,
)
_UNSAFE_INLINE_JSON = re.compile(
    r"""(?:x-data\s*=\s*"[^"]*\{\{[^}]+\|safe\s*\}\}|x-data\s*=\s*'[^']*\{\{[^}]+\|safe\s*\}\})""",
    re.I,
)
_BUTTON = re.compile(r"<button\b[^>]*>", re.I | re.S)
_BUTTON_ID = re.compile(r"""\bid=["']([\w:-]+)["']""")

_BUTTON_BEHAVIOR = re.compile(
    r"""(?:hx-(?:get|post|put|patch|delete)
        |@(?:click|change|submit)
        |x-on:
        |type=["'](?:submit|reset)["']
        |\bpopovertarget=
        |\bform=
        |\bdisabled\b
        |\bdata-[\w-]+)""",
    re.I | re.X,
)


def _stylesheet_class_names() -> set[str]:
    """Every class name that resolves to a rule in the shipped CSS.

    The compiled bundle plus the hand-written stylesheets beside it, because a
    utility-shaped class is sometimes defined by hand rather than generated.
    Names are unescaped back to how a template writes them, so a lookup is an
    exact set membership rather than a substring scan of 300KB per class.
    """
    names: set[str] = set()
    css_dir = os.path.join(settings.BASE_DIR, "static", "css")
    try:
        sheets = [os.path.join(css_dir, fn) for fn in sorted(os.listdir(css_dir))]
    except OSError:
        return names
    for path in sheets:
        if not path.endswith(".css"):
            continue
        try:
            source = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for match in _CSS_CLASS.finditer(source):
            names.add(re.sub(r"\\(.)", r"\1", match.group(1)))
    return names


def _template_utilities(source: str):
    """Yield the utility classes a template's class attributes actually use."""
    for attr in _CLASS_ATTR.findall(source):
        # A value carrying template syntax is assembled at render time; the
        # fragments around `{% if %}` are not reliably whole class names.
        if "{" in attr or "}" in attr:
            continue
        for token in attr.split():
            if _ARBITRARY_UTILITY.match(token):
                yield token
                continue
            scale = _SCALE_UTILITY.match(token)
            if scale and scale.group(1) in _SCALE_PREFIXES:
                yield token


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
    unresolved_utilities: list[tuple[str, str]] = []
    seen_utilities: set[tuple[str, str]] = set()

    try:
        compiled_css = open(MAIN_CSS, encoding="utf-8", errors="ignore").read()
    except OSError:
        compiled_css = ""
    stylesheet_classes = _stylesheet_class_names()

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
        if stylesheet_classes:
            for cls in _template_utilities(src):
                if cls in stylesheet_classes or (rel, cls) in seen_utilities:
                    continue
                seen_utilities.add((rel, cls))
                unresolved_utilities.append((rel, cls))
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
                # A button can also be wired by a script in the same
                # template that binds to its id (getElementById /
                # querySelector). That is a real behaviour the attribute
                # vocabulary above cannot see, and treating it as inert
                # would push authors to add a decorative attribute purely to
                # satisfy the lint. Only an id the file ACTUALLY references
                # counts — an unreferenced id still reads as dead.
                bound_by_script = False
                id_match = _BUTTON_ID.search(opening_tag)
                if id_match:
                    button_id = id_match.group(1)
                    bound_by_script = (
                        f"'{button_id}'" in src or f'"{button_id}"' in src
                    ) and src.count(button_id) > 1
                if bound_by_script:
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
                "uncompiled_utilities",
                "Utility classes that resolve to no CSS rule",
                unresolved_utilities,
                "warning",
                "Run npm run build:css, or use a value that exists on the scale "
                "(py-0.2 is not a step; py-0.5 is).",
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
