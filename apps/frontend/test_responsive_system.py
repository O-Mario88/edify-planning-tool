"""The responsive system: one fluid type scale and one final layer.

The owner's responsive standard (2026-09-23) asks for one governed token
system with fluid type between approved minimum and maximum sizes, one-line
controls, tables that scroll with their identity column in view, a sheet for
drawers on a phone, and a workspace that never scrolls sideways — in shared
layers, not page patches. These tests pin the parts that are easy to undo by
adding one more rule somewhere else; the browser behaviour is measured by
e2e/responsive-contract.spec.js and e2e/responsive-matrix.spec.js.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "static/css/design-system.css"
LAYER = ROOT / "static/css/components/responsive-system.css"
MICRO_UX_CSS = ROOT / "static/css/components/mobile-micro-ux.css"
MICRO_UX_JS = ROOT / "static/js/micro-ux.js"
BASE = ROOT / "templates/base.html"

CLAMP = re.compile(
    r"clamp\(\s*(?P<min>[\d.]+)rem\s*,\s*(?P<base>[\d.]+)rem\s*\+\s*"
    r"(?P<slope>[\d.]+)vw\s*,\s*(?P<max>[\d.]+)rem\s*\)"
)
REM = 16


def _token(css: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*([^;]+);", css)
    assert match, name
    return match.group(1).strip()


def _size(css: str, name: str, width: int) -> float:
    """The px size a token resolves to at a viewport `width`."""
    value = _token(css, name)
    alias = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if alias:
        return _size(css, alias.group(1), width)
    value = value.replace("var(--edify-text-floor)", _token(css, "--edify-text-floor"))
    match = CLAMP.fullmatch(value)
    assert match, f"{name} is not a fluid clamp: {value}"
    low, base, slope, high = (
        float(match.group(k)) for k in ("min", "base", "slope", "max")
    )
    return min(max(low * REM, base * REM + slope * width / 100), high * REM)


class FluidTypeScaleTest(SimpleTestCase):
    STEPS = (
        "--edify-text-display-size",
        "--edify-text-heading-size",
        "--edify-text-title-size",
        "--edify-text-body-size",
        "--edify-text-label-size",
        "--edify-text-micro-size",
    )
    WIDTHS = (320, 360, 390, 430, 768, 834, 1024, 1280, 1366, 1440, 1920, 2560)

    def setUp(self):
        self.css = TOKENS.read_text()

    def test_every_step_is_a_clamp_between_approved_sizes(self):
        for step in self.STEPS + (
            "--edify-text-hero-size",
            "--edify-text-tile-value-size",
        ):
            with self.subTest(step=step):
                self.assertRegex(_token(self.css, step), r"^clamp\(")

    def test_the_hierarchy_holds_at_every_width(self):
        """Title above body above caption — at 320px as much as at 2560px."""
        for width in self.WIDTHS:
            sizes = [_size(self.css, step, width) for step in self.STEPS]
            with self.subTest(width=width, sizes=sizes):
                self.assertEqual(sizes, sorted(sizes, reverse=True))
                self.assertEqual(len(set(sizes)), len(sizes))

    def test_nothing_falls_below_the_floor_or_grows_without_bound(self):
        floor = float(_token(self.css, "--edify-text-floor").removesuffix("rem")) * REM
        self.assertEqual(floor, 12)
        for step in self.STEPS:
            with self.subTest(step=step):
                self.assertGreaterEqual(_size(self.css, step, 320), floor)
                self.assertEqual(
                    _size(self.css, step, 2560), _size(self.css, step, 4000)
                )

    def test_phones_do_not_get_desktop_headings(self):
        self.assertLessEqual(_size(self.css, "--edify-text-display-size", 390), 20.5)
        self.assertGreater(_size(self.css, "--edify-text-display-size", 1440), 23)

    def test_kpi_values_stay_inside_the_compact_strip(self):
        self.assertLessEqual(_size(self.css, "--edify-text-tile-value-size", 2560), 24)

    def test_component_roles_alias_the_scale(self):
        for role, step in (
            ("--edify-text-card-heading-size", "var(--edify-text-heading-size)"),
            ("--edify-text-card-title-size", "var(--edify-text-title-size)"),
            ("--edify-text-table-size", "var(--edify-text-label-size)"),
            ("--edify-text-table-heading-size", "var(--edify-text-micro-size)"),
        ):
            with self.subTest(role=role):
                self.assertEqual(_token(self.css, role), step)

    def test_no_stylesheet_redeclares_the_scale_per_breakpoint(self):
        """One scale: a breakpoint that re-declares a step is a second scale."""
        declaration = re.compile(r"--edify-text-[a-z-]+-size\s*:")
        for path in sorted((ROOT / "static/css").rglob("*.css")):
            if path == TOKENS or path.name in {"main.css", "tokens.css"}:
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(declaration.search(path.read_text()))


class ResponsiveLayerTest(SimpleTestCase):
    def setUp(self):
        self.css = LAYER.read_text()

    def test_the_layer_loads_after_every_layout_layer(self):
        """Only the pointer-response layer (interactions.css) comes later."""
        base = BASE.read_text()
        links = re.findall(r'<link rel="stylesheet" href="[^"]*?([\w/-]+\.css)', base)
        self.assertTrue(links[-2].endswith("components/responsive-system.css"), links)
        self.assertTrue(links[-1].endswith("components/interactions.css"), links)

    def test_controls_stay_on_one_line_in_the_workspace_and_in_drawers(self):
        block = self.css[self.css.index("1. One-line controls") :]
        self.assertIn(":is(.edify-workspace, #drawer-container)", block)
        self.assertIn("white-space: nowrap;", block)
        # A control with block content is a selection card, not a control.
        self.assertIn(":not(:has(", block)

    def test_status_labels_stay_on_one_line_with_a_full_text_path(self):
        self.assertIn("text-overflow: ellipsis;", self.css)
        self.assertIn("function titleTruncatedLabels", MICRO_UX_JS.read_text())

    def test_the_badge_no_longer_opts_into_wrapping(self):
        components = (ROOT / "static/css/components.css").read_text()
        badge = components[components.index(".edify-badge {") :]
        badge = badge[: badge.index("}")]
        self.assertNotIn("white-space: normal", badge)
        self.assertNotIn("overflow-wrap: anywhere", badge)

    def test_wide_tables_keep_their_identity_column_and_say_they_scroll(self):
        self.assertIn('[data-scroll-state="middle"]', self.css)
        self.assertIn("position: sticky;", self.css)
        self.assertIn("var(--edify-frozen-surface)", self.css)
        self.assertIn("mask-image: linear-gradient(to left, transparent 0", self.css)
        js = MICRO_UX_JS.read_text()
        self.assertIn("Swipe to view more columns", js)
        self.assertIn("function watchScrollRegions", js)
        self.assertIn("learnSwipe", js)

    def test_the_hint_respects_reduced_motion(self):
        block = self.css[self.css.index("@media (prefers-reduced-motion: reduce)") :]
        self.assertIn(".edify-table-scroll-hint", block)
        self.assertIn("animation: none;", block)

    def test_the_workspace_never_scrolls_sideways(self):
        self.assertIn(".edify-workspace {\n  overflow-x: hidden;", self.css)

    def test_the_page_header_stacks_its_actions_on_a_phone(self):
        block = self.css[self.css.index("4. Page header") :]
        self.assertIn("@media (max-width: 47.99rem)", block)
        self.assertIn("flex-wrap: wrap;", block)

    def test_the_layer_uses_tokens_not_raw_colours(self):
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.css))
        self.assertIsNone(re.search(r"\brgba?\(", self.css))

    def test_buttons_take_their_size_from_the_label_token(self):
        micro = MICRO_UX_CSS.read_text()
        self.assertNotIn("font-size: 0.8125rem !important;", micro)
