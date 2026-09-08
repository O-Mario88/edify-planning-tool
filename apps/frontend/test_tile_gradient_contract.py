"""Every tile carries the accent wash, and nothing quietly repaints it.

Owner, 2026-09-05: "the tile gradient design is never implemented
system-wide". A sweep of 24 pages found 71 of 124 KPI tiles and all 15
hand-built stat tiles rendering flat white beside washed neighbours. None of
it was a design decision — four different rules were repainting tiles as
plain card surfaces, and a tile with no tone had no accent to paint with.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class EveryTileHasAnAccentTest(SimpleTestCase):
    def test_a_tile_without_a_tone_still_has_an_accent(self):
        """A tile rendered with no tone — the Work Plan's six — matched no
        accent rule, so the gradient declaration was dropped for an unset
        variable and the tile came out white."""
        css = _read("static/css/components.css")
        block = css.split(".kpi-strip__item {", 1)[1]
        self.assertIn(
            "--kpi-accent", css.split("Every tile, not only a toned one", 1)[1][:400]
        )
        self.assertIn("border-color: color-mix(in srgb, var(--kpi-accent)", block)

    def test_the_hand_built_tile_defaults_to_neutral_not_transparent(self):
        css = _read("static/css/consistency.css")
        block = css.split("main .edify-stat-tile.edify-stat-tile {", 1)[1][:700]
        self.assertIn("--kpi-accent: var(--edify-text-muted", block)
        self.assertNotIn("--kpi-accent: transparent", block)


class NoSurfaceRuleRepaintsATileTest(SimpleTestCase):
    """The four rules that were flattening tiles, each named where it lives.

    A tile is not a content card, not a nested card, and not a grid child to
    be stripped. Each of these rules had a legitimate job and simply had no
    reason to claim a tile.
    """

    def test_the_borderless_surface_contracts_exempt_tiles(self):
        for path in ("static/css/consistency.css", "static/css/platform.css"):
            with self.subTest(path=path):
                self.assertIn(
                    ":not(.kpi-strip__item):not(.edify-stat-tile)", _read(path)
                )

    def test_the_nested_card_rule_exempts_tiles(self):
        css = _read("static/css/consistency.css")
        rule = css.split("A tile is not a nested card", 1)[1][:400]
        self.assertIn(".kpi-strip__item, .edify-stat-tile,", rule)

    def test_a_dense_strip_tints_with_a_colour_not_the_shorthand(self):
        """`background:` resets `background-image`, so a strip of six or more
        tiles lost every gradient — 68 of the 124 tiles on the platform."""
        css = _read("static/css/components.css")
        rule = css.split("background-COLOR, not the shorthand", 1)[1][:600]
        self.assertIn("background-color: color-mix(", rule)
        self.assertNotRegex(rule, r"\n\s+background: color-mix\(")
