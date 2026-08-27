"""Static contracts for the app-wide borderless surface design."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class GlobalSurfaceRefreshTest(SimpleTestCase):
    def test_every_theme_defines_its_own_card_surface_tokens(self):
        """No theme may leave a card token to another theme's value.

        This required `--edify-card-border: transparent` in at least three
        blocks, and the dark theme now sets `#2d3d49` instead — a deliberate
        change, because on a dark ground a hairline is what separates stacked
        cards and table rows where a shadow alone does not read. "Borderless"
        was never the property worth protecting; it was one theme's answer to
        it.

        The property worth protecting is that every theme answers. A theme
        that defines the shadow but not the border inherits whatever the
        previous cascade left, and cards then carry the wrong theme's edge —
        the class of bug that is invisible in the theme you happen to be
        developing in. So count definitions, not values, and check the values
        only where a value is actually the contract.
        """
        tokens = _read("static/css/design-system.css")

        for token in (
            "--edify-card-border:",
            "--edify-card-shadow:",
            "--edify-card-shadow-hover:",
            "--page-header-border:",
        ):
            self.assertGreaterEqual(
                tokens.count(token),
                3,
                f"{token} is not defined in every theme — cards will inherit "
                f"another theme's value",
            )

        # The light grounds stay borderless: there, elevation alone separates
        # a card and an added edge reads as a box. Two of the three, because
        # dark is the deliberate exception documented above.
        self.assertGreaterEqual(tokens.count("--edify-card-border: transparent"), 2)

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

    def test_cards_tiles_and_kpis_consume_one_responsive_padding_scale(self):
        tokens = _read("static/css/design-system.css")
        bridge = _read("static/css/consistency.css")
        components = _read("static/css/components.css")

        for token in (
            "--edify-surface-padding-inline:",
            "--edify-surface-padding-block:",
            "--edify-surface-padding:",
            "--edify-surface-padding-compact:",
            "--edify-kpi-padding:",
        ):
            self.assertIn(token, tokens)
        self.assertIn("padding: var(--edify-surface-padding) !important", bridge)
        self.assertIn(':not([data-edify-padding="flush"])', bridge)
        self.assertIn(":not(:has(> :is(", bridge)
        self.assertIn("padding: var(--edify-kpi-padding) !important", bridge)
        self.assertIn("padding: var(--edify-kpi-padding);", components)

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
