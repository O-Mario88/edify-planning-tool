"""Regression contract for the platform-wide floating drawer system.

The visual redesign is intentionally centralized.  A drawer implemented with
raw fixed-position utilities can look acceptable on its author's screen while
missing mobile sizing, focus visibility, dark-theme tokens, safe-area padding
and reduced-motion behavior everywhere else.  These tests keep new input
drawers on one of the supported surfaces instead of allowing that drift back.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "templates"
DRAWER_CSS = ROOT / "static" / "css" / "drawers.css"
BASE_DRAWER = TEMPLATES / "components" / "drawers" / "base_drawer.html"

SUPPORTED_SURFACE_MARKERS = (
    "components/drawers/base_drawer.html",
    "edify-popup-dialog",
    "edify-form-dialog__surface",
)

# These two files are bodies rendered inside a shell owned by their calling
# page; neither creates a floating surface itself.
BODY_ONLY_DRAWER_PARTIALS = {
    TEMPLATES / "partials" / "leave" / "request_leave_drawer.html",
    TEMPLATES / "partials" / "oversight" / "filter_drawer.html",
}


class EnterpriseDrawerSystemTests(SimpleTestCase):
    def test_canonical_shell_has_modal_and_focus_contract(self):
        markup = BASE_DRAWER.read_text(encoding="utf-8")

        for contract in (
            "data-edify-drawer",
            'role="dialog"',
            'aria-modal="true"',
            'aria-labelledby="drawer-title"',
            'aria-describedby="drawer-subtitle"',
            '@keydown.tab="trapFocus($event)"',
            "window.__edifyDrawerBackground?.lock()",
            "previousFocus = document.activeElement",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, markup)

    def test_canonical_shell_uses_the_enterprise_header_hierarchy(self):
        markup = BASE_DRAWER.read_text(encoding="utf-8")

        for class_name in (
            "drawer-header__identity",
            "drawer-header__mark",
            "drawer-header__eyebrow",
            "drawer-header__title-row",
            "drawer-header__subtitle",
        ):
            with self.subTest(class_name=class_name):
                self.assertIn(class_name, markup)

    def test_every_input_drawer_uses_a_supported_surface(self):
        offenders: list[str] = []
        for path in sorted(TEMPLATES.rglob("*drawer*.html")):
            if path in BODY_ONLY_DRAWER_PARTIALS:
                continue
            markup = path.read_text(encoding="utf-8", errors="replace")
            if not any(
                tag in markup for tag in ("<form", "<input", "<select", "<textarea")
            ):
                continue
            if not any(marker in markup for marker in SUPPORTED_SURFACE_MARKERS):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(
            offenders,
            [],
            "Floating input drawers must extend base_drawer or opt into the "
            "legacy/page-local enterprise bridge: " + ", ".join(offenders),
        )

    def test_shared_shell_is_the_dominant_platform_implementation(self):
        canonical = [
            path
            for path in TEMPLATES.rglob("*.html")
            if "components/drawers/base_drawer.html"
            in path.read_text(encoding="utf-8", errors="replace")
        ]
        self.assertGreaterEqual(
            len(canonical),
            60,
            "The shared drawer shell has been bypassed by a broad rewrite.",
        )

    def test_enterprise_css_covers_controls_actions_and_responsiveness(self):
        css = DRAWER_CSS.read_text(encoding="utf-8")

        for contract in (
            ".drawer-header__mark",
            ".drawer-body label:not(:has(",
            'input[type="datetime-local"]',
            ".drawer-footer",
            ".edify-popup-dialog__surface",
            ".edify-form-dialog__surface",
            "env(safe-area-inset-bottom)",
            "font-size: 1rem",
            "@media (pointer: coarse)",
            "@media (prefers-reduced-motion: reduce)",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, css)

    def test_primary_drawer_action_keeps_legible_ink(self):
        css = DRAWER_CSS.read_text(encoding="utf-8")
        enterprise = css.split("EDIFY ENTERPRISE DRAWER FOUNDATION", 1)[1]

        self.assertIn("color: var(--edify-on-accent, #fff) !important", enterprise)
        self.assertIn(".btn-premium-primary:hover:not(:disabled)", enterprise)
