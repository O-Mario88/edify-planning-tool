"""Static contracts for the app-wide borderless surface design."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class GlobalSurfaceRefreshTest(SimpleTestCase):
    def test_every_theme_defines_borderless_elevated_card_tokens(self):
        tokens = _read("static/css/design-system.css")

        self.assertGreaterEqual(tokens.count("--edify-card-border: transparent"), 3)
        self.assertGreaterEqual(tokens.count("--edify-card-shadow:"), 3)
        self.assertGreaterEqual(tokens.count("--edify-card-shadow-hover:"), 3)
        self.assertGreaterEqual(tokens.count("--page-header-border: transparent"), 3)

    def test_shared_bridge_covers_legacy_and_modern_surface_families(self):
        bridge = _read("static/css/consistency.css")
        contract = bridge.split("GLOBAL BORDERLESS SURFACE CONTRACT", 1)[1].split(
            "Drawers and modal panels", 1
        )[0]

        for selector in (
            ".card:not(.card-alert)",
            ".premium-card",
            ".panel",
            ".edify-kpi-card",
            ".edify-tile",
            '[class*="-card"]',
            '[class*="-panel"]',
            '[class*="-tile"]',
            "div.edify-surface",
            "div.bg-white",
            "div.rounded-surface.border",
        ):
            self.assertIn(selector, contract)

        self.assertIn("border-color: var(--edify-card-border) !important", contract)
        self.assertIn("box-shadow: var(--edify-card-shadow) !important", contract)

    def test_functional_boundaries_and_forced_colors_remain_visible(self):
        tokens = _read("static/css/design-system.css")
        bridge = _read("static/css/consistency.css")

        self.assertIn("@media (forced-colors: active)", tokens)
        self.assertIn("--edify-card-border: CanvasText", tokens)
        self.assertIn("--page-header-border: CanvasText", tokens)
        self.assertIn("border: 1px solid var(--edify-card-border) !important", bridge)
        self.assertIn("border-color: var(--edify-border) !important", bridge)

    def test_messages_consumes_the_global_contract_without_page_css(self):
        page = _read("templates/pages/messages/index.html")

        self.assertNotIn("css/pages/messages.css", page)
        self.assertIn("data-edify-tablist", page)
        self.assertIn("data-edify-tab", page)
