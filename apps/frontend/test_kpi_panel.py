"""The KPI tray is one panel, not a row of squares.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"I want all the KPI Designs system wide (in the entire app) to be redesigned
like the referenced photos… remove the current square designs but keep the
gradients. I want Tiles overhauls platform-wide not just one page or one role
and make it professionally enterprise grade. The blue color you see should only
apply on blue mode the rest of the modes should retain their themes."

The references are this platform's own login strip: ONE panel, its metrics
separated by hairlines, each led by a mark, with a small-caps label, the number,
and a single caption line. What the app had instead was a tray of individually
bordered, rounded, shadowed and separately washed cards — 124 of them.

WHAT THESE TESTS HOLD

The anatomy (one panel, no tile chrome, a mark, caps labels, one caption line),
the mechanism that draws the hairlines without knowing the column count, and
the rule that keeps every theme its own: the chrome is expressed in tokens, and
only the blue theme's tokens are the reference's blues.
"""

from django.test import SimpleTestCase

from .test_design_system_quality import _read


class KpiPanelAnatomyTest(SimpleTestCase):
    def test_the_tray_is_the_panel_and_the_tile_carries_no_chrome(self):
        css = _read("static/css/components.css")

        # The panel: border, radius, gradient — the gradients the owner asked
        # to keep, now on one surface instead of on every tile.
        self.assertIn("border: 1px solid var(--edify-kpi-panel-border);", css)
        self.assertIn("background-image: linear-gradient(", css)

        # The tile: none of the four things that made it a square.
        block = css[css.index("THE KPI PANEL IS THE LAST WORD ON TILE CHROME") :]
        self.assertIn("border-radius: 0 !important;", block)
        self.assertIn("background-color: transparent !important;", block)
        self.assertIn("background-image: none !important;", block)
        self.assertIn("box-shadow: none !important;", block)

    def test_the_hairlines_are_drawn_by_clipping_not_by_counting_columns(self):
        """Every tile carries a rule on two edges and the grid clips the
        outermost ones. That is what lets the same two declarations serve a
        four-up row, a 4x2 grid and a one-up phone tray without any rule
        knowing which it is."""

        css = _read("static/css/components.css")
        item = css[
            css.index(".kpi-strip.kpi-strip--executive .kpi-strip__item {") :
        ]
        item = item[: item.index("\n}")]
        self.assertIn("border-inline-start: 1px solid var(--edify-kpi-divider);", item)
        self.assertIn("border-block-start: 1px solid var(--edify-kpi-divider);", item)
        self.assertIn("margin-inline-start: -1px;", item)
        self.assertIn("margin-block-start: -1px;", item)

        grid = css[
            css.index(".kpi-strip.kpi-strip--executive .kpi-strip__grid {") :
        ]
        grid = grid[: grid.index("\n}")]
        self.assertIn("gap: 0;", grid)
        self.assertIn("overflow: clip;", grid)

    def test_the_mark_leads_the_metric(self):
        css = _read("static/css/components.css")
        body = css[
            css.index(".kpi-strip.kpi-strip--executive .kpi-strip__item-body {") :
        ]
        body = body[: body.index("\n}")]
        self.assertIn('"icon label"', body)
        self.assertIn('"icon value"', body)
        self.assertIn('"icon meta"', body)

        # Shown, not hidden — the old executive tile spent that corner on a
        # pill and switched the mark off entirely.
        self.assertNotIn(
            ".kpi-strip.kpi-strip--executive .kpi-strip__icon-container {\n  display: none;",
            css,
        )
        self.assertIn("grid-area: icon;", css)

    def test_the_label_is_small_caps_and_the_caption_is_one_line(self):
        css = _read("static/css/components.css")
        label = css[
            css.index(".kpi-strip.kpi-strip--executive .kpi-strip__label {") :
        ]
        label = label[: label.index("\n}")]
        self.assertIn("text-transform: uppercase;", label)
        self.assertIn("font-size: var(--edify-text-micro-size);", label)

        meta = css[css.index(".kpi-strip.kpi-strip--executive .kpi-strip__meta {") :]
        meta = meta[: meta.index("\n}")]
        self.assertIn("display: flex;", meta)
        self.assertIn("grid-area: meta;", meta)

    def test_the_movement_reads_as_text_rather_than_a_chip(self):
        css = _read("static/css/components.css")
        self.assertIn(
            ".kpi-strip.kpi-strip--executive .kpi-strip__grid > .kpi-strip__item .kpi-strip__trend {",
            css,
        )
        trend = css[
            css.index(
                ".kpi-strip.kpi-strip--executive .kpi-strip__grid > .kpi-strip__item .kpi-strip__trend {"
            ) :
        ]
        trend = trend[: trend.index("\n}")]
        self.assertIn("border: 0;", trend)
        self.assertIn("background: none;", trend)

    def test_the_component_puts_the_movement_on_the_caption_line(self):
        markup = _read("templates/components/kpi_strip.html")
        # The mark is what the topline holds now; the pill moved down beside
        # the helper it qualifies.
        topline = markup[markup.index('<span class="kpi-strip__topline">') :]
        topline = topline[: topline.index("</span>\n")]
        self.assertIn("kpi-strip__icon-container", topline)
        self.assertNotIn("kpi-strip__trend", topline)

        meta = markup[markup.index('<span class="kpi-strip__meta">') :]
        meta = meta[: meta.index("</span>\n        </span>")]
        self.assertIn("kpi-strip__trend", meta)
        self.assertIn("kpi-strip__helper", meta)
        # The reference's caption opens with the arrow.
        self.assertIn('kpi-strip__trend--fresh">↗ Current<', meta)


class KpiPanelThemeTest(SimpleTestCase):
    def test_the_chrome_is_tokens_so_each_theme_keeps_its_own_colour(self):
        """"The blue color you see should only apply on blue mode the rest of
        the modes should retain their themes." So the panel names tokens, and
        each theme answers with its own values."""

        css = _read("static/css/components.css")
        self.assertNotIn("rgba(147, 205, 241", css)  # the reference's navy blues
        self.assertNotIn("rgba(131, 196, 234", css)  # live only in the theme
        self.assertIn("var(--edify-kpi-panel-border)", css)
        self.assertIn("var(--edify-kpi-divider)", css)
        self.assertIn("var(--edify-kpi-panel-sheen)", css)

        tokens = _read("static/css/design-system.css")
        # Defined once for the default theme, and again for each theme that
        # needs its own answer.
        self.assertEqual(tokens.count("--edify-kpi-panel-border:"), 3)
        self.assertEqual(tokens.count("--edify-kpi-divider:"), 3)
        blue = tokens[tokens.index(":root.theme-blue {") :]
        blue = blue[: blue.index("\n}")]
        self.assertIn("--edify-kpi-panel-border: rgba(147, 205, 241, 0.3);", blue)
        self.assertIn("--edify-kpi-divider: rgba(131, 196, 234, 0.22);", blue)

    def test_the_dark_themes_do_not_put_the_cards_back(self):
        css = _read("static/css/consistency.css")
        dark = css[
            css.index('.theme-dark .kpi-strip__item[class*="kpi-strip__item--"] {') :
        ]
        dark = dark[: dark.index("\n}")]
        self.assertIn("background-color: transparent !important;", dark)
        self.assertIn("box-shadow: none !important;", dark)
        self.assertIn(
            ':is(.theme-blue, .theme-dark) .kpi-strip.kpi-strip--executive .kpi-strip__item {',
            css,
        )
