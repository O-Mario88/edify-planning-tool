"""One content line (owner, 2026-10-02).

"Fix all the padding on every card so that everything is well aligned. Look
at content inside cards, table padding, tabs, content inside kpi strips; look
at all screens and apply across the platform." And: "tabs inside the cards
should be aligned with the content inside the cards."

Measured on 710 cards across 324 pages before the change, a table card
started its content 12px from its edge, a plain card 16px, a band inside a
padded card 32px, and a tab strip in an edge-to-edge card sat on the edge.
Every card now starts its content ``--edify-card-inset`` in.

``e2e/one-content-line.spec.js`` measures the rule in a browser. These hold
the source it rests on, so a later edit that puts a literal inset back, or
takes a part of the rule out, fails here with the reason beside it.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
CSS = ROOT / "static" / "css"


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text()


def _section(css: str, start: str) -> str:
    """The text of ``css`` from the comment that opens ``start``."""
    at = css.index(start)
    return css[at:]


def _block(css: str, selector_ends: str) -> str:
    """The declarations of the first rule whose selector ends with this."""
    at = css.index(selector_ends + " {") + len(selector_ends) + 2
    return css[at : css.index("}", at)]


class TheTokensTest(SimpleTestCase):
    def test_the_line_is_one_token(self):
        tokens = _read("static", "css", "design-system.css")
        self.assertIn(
            "--edify-card-inset: var(--edify-surface-padding-inline);", tokens
        )
        self.assertIn("--edify-surface-padding-inline: 1rem;", tokens)

    def test_what_is_left_to_pay_is_set_only_inside_main(self):
        """A drawer's table is in no card: its outer cells keep the cell
        padding through the fallback."""
        css = _read("static", "css", "consistency.css")
        line = _section(css, "/* ═══ ONE CONTENT LINE")
        self.assertIn(
            "main,\nmain .edify-structured-surface {\n"
            "  --edify-section-inset: var(--edify-card-inset);",
            line,
        )
        self.assertNotIn("--edify-section-inset", _read("static/css/tokens.css"))
        self.assertNotIn(
            "--edify-section-inset:", _read("static", "css", "design-system.css")
        )


class TablesTest(SimpleTestCase):
    def setUp(self):
        self.css = _read("static", "css", "consistency.css")

    def test_every_cell_names_its_two_sides(self):
        self.assertIn(
            "  --edify-cell-start: var(--edify-table-cell-padding-inline);\n"
            "  --edify-cell-end: var(--edify-table-cell-padding-inline);\n"
            "  padding-inline: var(--edify-cell-start) var(--edify-cell-end) "
            "!important;",
            self.css,
        )

    def test_the_outer_cells_of_a_row_take_what_is_left_to_pay(self):
        for place, side in (("first-child", "start"), ("last-child", "end")):
            with self.subTest(place=place):
                self.assertRegex(
                    self.css,
                    r":is\(thead, tbody\) > tr > :is\(td, th\):"
                    + place
                    + r" \{\n  --edify-cell-"
                    + side
                    + r": var\(--edify-section-inset, "
                    r"var\(--edify-table-cell-padding-inline\)\);",
                )

    def test_a_density_sets_the_sides_not_the_padding(self):
        """A compact or truncated table writing ``padding-inline: 0.5rem``
        itself put its first column 8px from the card's edge again."""
        for selector in (
            "table.edify-table--compact:not(.sr-only) :is(thead, tbody) :is(td, th)",
            "table.edify-table--truncate:not(.sr-only):not(.edify-visually-hidden) "
            ":is(thead, tbody, tfoot) :is(th, td)",
        ):
            with self.subTest(selector=selector[:30]):
                block = _block(self.css, selector)
                self.assertIn("--edify-cell-start: 0.5rem;", block)
                self.assertIn("--edify-cell-end: 0.5rem;", block)
                self.assertIn(
                    "padding-inline: var(--edify-cell-start) var(--edify-cell-end)",
                    block,
                )

    def test_a_band_reads_the_same_variable(self):
        self.assertIn(
            "padding: .375rem max(var(--edify-section-inset, "
            "var(--edify-card-inset)), var(--edify-table-cell-padding-inline)) "
            "!important;",
            self.css,
        )

    def test_a_heading_that_is_the_band_may_bleed(self):
        """``margin: 0 !important`` on it kept the band inside the padding."""
        at = self.css.index(
            ":is(h2, h3, h4).edify-table-titlebar.edify-table-titlebar"
            ".edify-table-titlebar {"
        )
        block = self.css[at : self.css.index("}", at)]
        self.assertIn("margin-block: 0 !important;", block)
        self.assertNotRegex(block, r"\n  margin: 0 !important;")

    def test_pagers_and_group_heads_start_on_the_line(self):
        pager = _read("static", "css", "components", "mobile-micro-ux.css")
        self.assertEqual(
            pager.count("padding: 0.5rem var(--edify-section-inset, 0.75rem)"), 2
        )
        components = _read("static", "css", "components.css")
        self.assertIn(
            "calc(var(--edify-section-inset, 0.75rem) - 3px)",
            _block(components, ".edify-group-head > th"),
        )


class CardsTest(SimpleTestCase):
    def setUp(self):
        self.css = _read("static", "css", "consistency.css")
        self.line = _section(self.css, "/* ═══ ONE CONTENT LINE")

    def test_a_plain_card_has_paid(self):
        at = self.css.index("  padding: var(--edify-surface-padding) !important;")
        self.assertIn(
            "--edify-section-inset: 0px;", self.css[at : self.css.index("}", at)]
        )

    def test_a_padded_card_pays_what_is_left_and_its_table_bleeds(self):
        self.assertIn("  padding-inline: var(--edify-section-inset);", self.line)
        self.assertIn(
            "> :is(.edify-table-titlebar, [data-table-scroll-region], "
            '.edify-record-table-wrap):not([class~="border"]) {\n'
            "  margin-inline: calc(-1 * var(--edify-section-inset));",
            self.line,
        )
        # The children of the padding have nothing left to pay: on the
        # children, because the card's own padding reads the value it was
        # given.
        self.assertIn(
            "> :not(.edify-table-titlebar, [data-table-scroll-region], "
            ".edify-record-table-wrap) {\n  --edify-section-inset: 0px;",
            self.line,
        )

    def test_the_padded_families_are_named(self):
        for family in (".rpl-card", ".hrd-card", ".pto-panel", ".hr-today-queue"):
            with self.subTest(family=family):
                self.assertIn(family, self.line)

    def test_a_shell_s_sections_tabs_and_text_take_the_inset(self):
        self.assertRegex(
            self.line,
            r"> :is\(\n  header, footer, summary, \.context-metrics,[^{]*\{\n"
            r"  padding-inline: var\(--edify-section-inset\);",
        )
        self.assertRegex(
            self.line,
            r"> :is\(\n  nav, \[role=\"tablist\"\], \.edify-tab-container, "
            r"p, h2, h3, h4\n\):not\([^{]*\{\n"
            r"  margin-inline: var\(--edify-section-inset\);",
        )

    def test_a_tab_strip_keeps_the_inset_on_a_phone(self):
        """On a phone a filled row took ``margin-inline: 0 !important``. The
        fill rule reads a variable, and a tab strip in a shell sets it."""
        self.assertRegex(
            self.line,
            r"> :is\(nav, \[role=\"tablist\"\], \.edify-tab-container\) \{\n"
            r"  --edify-fill-inset: var\(--edify-section-inset\);",
        )
        fill = _read("static", "css", "components", "interactions.css")
        self.assertIn("margin-inline: var(--edify-fill-inset, 0px) !important;", fill)
        self.assertIn(
            "inline-size: calc(100% - 2 * var(--edify-fill-inset, 0px)) !important;",
            fill,
        )

    def test_the_rule_adds_no_override_and_no_substring_selector(self):
        """The UI audit holds ``!important`` and ``[class*=…]`` to a ceiling
        (test_component_adoption). The rule out-ranks what it replaces by
        naming the card, or hands an existing rule a variable to read."""
        self.assertEqual(re.findall(r"!important;", self.line), [])
        self.assertNotIn("[class*=", self.line)

    def test_a_row_of_cards_drawn_as_one_pays_once(self):
        # The card rule pads with the token, so the flattened child changes
        # the token; the card under it is a card again.
        self.assertIn(
            "  --edify-surface-padding: var(--edify-surface-padding-block) 0px;\n"
            "  padding-inline: 0;\n}",
            self.css,
        )
        self.assertIn("main .edify-tile-grid > * > * {", self.css)
        self.assertIn(
            "main .edify-tile-grid > .edify-structured-surface {\n"
            "  --edify-section-inset: 0px;",
            self.line,
        )

    def test_no_new_inset_is_a_literal(self):
        """12, 20 and 32px are how the cards drifted apart."""
        declarations = re.findall(
            r"(?:padding|margin)-inline(?:-start|-end)?:\s*([^;]+);", self.line
        )
        self.assertTrue(declarations)
        for value in declarations:
            with self.subTest(value=value):
                self.assertNotRegex(value, r"\d+(\.\d+)?(px|rem)")


class TheFamiliesTest(SimpleTestCase):
    def test_family_cards_read_the_token(self):
        pages = _read("static", "css", "pages.css")
        for selector in (".rpl-card", ".hrd-card"):
            with self.subTest(selector=selector):
                block = _block(pages, selector)
                self.assertIn("padding: 1rem var(--edify-card-inset);", block)
                self.assertIn("--edify-card-gap: 0.875rem;", block)
        self.assertIn("--pto-panel-padding: var(--edify-card-inset);", pages)
        self.assertIn("--tt-panel-pad: var(--edify-card-inset);", pages)
        self.assertIn(
            "padding: var(--edify-card-inset) !important;",
            _read("static", "css", "platform.css"),
        )

    def test_the_project_and_cluster_card_is_a_shell(self):
        platform = _read("static", "css", "platform.css")
        self.assertIn(
            "padding: 1.1rem var(--edify-card-inset);",
            _block(platform, ".cluster-card__summary"),
        )
        details = _block(platform, ".cluster-card__details")
        self.assertIn("padding: 1.25rem var(--edify-card-inset);", details)
        self.assertIn("--edify-section-inset: 0px;", details)
        self.assertIn(
            ".cluster-card__details > .edify-structured-surface {\n"
            "  margin-inline: calc(-1 * var(--edify-card-inset));",
            platform,
        )
        for name in (
            "partials/clusters/cluster_card.html",
            "partials/projects/project_card.html",
        ):
            with self.subTest(template=name):
                self.assertIn(
                    'data-edify-padding="flush"', _read("templates", *name.split("/"))
                )

    def test_shells_the_card_rule_padded_twice_say_they_are_shells(self):
        for name in (
            "pages/schools/index.html",
            "partials/finance/fund_workspace.html",
        ):
            with self.subTest(template=name):
                self.assertIn(
                    'data-edify-padding="flush"', _read("templates", *name.split("/"))
                )

    def test_directory_rows_start_on_the_line(self):
        mobile = _read("static", "css", "components", "mobile-micro-ux.css")
        self.assertIn("padding: 0.3rem var(--edify-card-inset) !important;", mobile)
        self.assertIn(
            "padding: 0.25rem var(--edify-card-inset) !important;",
            _read("static", "css", "components", "interactions.css"),
        )


class ThePageScriptTest(SimpleTestCase):
    def setUp(self):
        self.js = _read("static", "js", "micro-ux.js")

    def test_a_part_of_a_card_is_not_a_card(self):
        self.assertIn(
            'surface.matches(\'[class*="-card__"], [class*="-panel__"], '
            '[class*="-tile__"]\')',
            self.js,
        )
        self.assertIn("var structured = !part && ", self.js)

    def test_an_unmarked_shell_is_found_by_its_sections(self):
        self.assertIn(r"/(^|\s)px-\d/.test(names)", self.js)
        self.assertIn(r"/(^|\s)border-[bt](\s|$)/.test(names)", self.js)

    def test_the_card_carries_the_marks_the_stylesheet_reads(self):
        """consistency.css keeps relationships explicit (no relational
        selector), so the script says which card is nested, which opens with
        its band and which closes with its table."""
        for mark in (
            "data-edify-nested",
            "data-edify-band-first",
            "data-edify-table-last",
        ):
            with self.subTest(mark=mark):
                self.assertIn(
                    f"surface.toggleAttribute('{mark}', structured && ", self.js
                )
                self.assertIn(mark, _read("static", "css", "consistency.css"))


class TheStripOfFiguresTest(SimpleTestCase):
    def test_figures_and_helpers_share_rows(self):
        css = _read("static", "css", "components.css")
        at = css.index("@supports (grid-template-rows: subgrid)")
        block = css[at : at + 1400]
        self.assertIn("--kpi-rail-display: grid;", block)
        self.assertIn("display: var(--kpi-rail-display, flex) !important;", css)
        self.assertIn("grid-template-rows: auto auto 1fr;", block)
        self.assertIn("grid-template-rows: subgrid;", block)
        # Nine facts or more keep the scrolling row.
        self.assertIn(":not(:has(> .context-metrics__fact:nth-child(9)))", block)


class TheBuiltStylesTest(SimpleTestCase):
    def test_the_served_bundle_carries_the_rule(self):
        """Pages load static/build/css; a rule left out of the build is a
        rule nobody sees."""
        for name, needle in (
            ("consistency.css", "--edify-section-inset"),
            ("design-system.css", "--edify-card-inset"),
            ("components.css", "subgrid"),
            ("pages.css", "--edify-card-gap"),
            ("platform.css", "cluster-card__details"),
        ):
            with self.subTest(sheet=name):
                self.assertIn(needle, _read("static", "build", "css", name))
