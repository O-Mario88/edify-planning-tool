"""One tab design, owned by platform.css, used by every page.

The app had three: segmented pills on some pages, an underlined rail on
others, and bare flex rows elsewhere — several pages overriding the shared
contract by hand. The contract now describes the underlined rail, and pages
are not allowed to paint their own.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_CSS = ROOT / "static" / "css" / "platform.css"
TEMPLATES = ROOT / "templates"

# Container backgrounds/padding and button-ish classes on a tab are the marks
# of a page painting its own tab strip.
CONTAINER_PAINT = re.compile(
    r'role="tablist"[^>]*class="[^"]*'
    r'(bg-slate-\d|bg-white|rounded-surface|rounded-control|\bp-1\b|border\b)'
)
TAB_PAINT = re.compile(
    r'role="tab"(?:[^>]|\n)*?class="[^"]*(btn-premium|edify-primary-solid|shadow-sm)'
)


class TabContractTest(TestCase):
    def setUp(self):
        self.css = PLATFORM_CSS.read_text()

    def test_the_contract_is_an_underlined_rail_not_a_segmented_pill(self):
        block = self.css.split('main :where([role="tablist"]', 1)[1].split("}", 1)[0]
        self.assertIn("border-block-end: 1px solid var(--edify-border)", block)
        self.assertIn("background: transparent", block)
        self.assertIn("border-radius: 0", block)

    def test_the_selected_tab_is_marked_by_an_underline(self):
        block = self.css.split(
            'main :where([role="tab"][aria-selected="true"]', 1
        )[1].split("}", 1)[0]
        self.assertIn("border-block-end-color: var(--edify-accent)", block)
        self.assertIn("background: transparent", block)
        self.assertIn("box-shadow: none", block)

    def test_night_mode_uses_a_readable_blue_for_the_selected_label(self):
        """--edify-accent as text on the night surface falls under AA."""
        block = self.css.split(
            '.theme-dark main :where([role="tab"][aria-selected="true"]', 1
        )[1].split("}", 1)[0]
        self.assertIn("color: var(--edify-info)", block)


class NoPageStylesItsOwnTabsTest(TestCase):
    def test_no_template_paints_its_own_tab_strip(self):
        offenders = []
        for path in TEMPLATES.rglob("*.html"):
            src = path.read_text()
            if 'role="tablist"' not in src:
                continue
            rel = str(path.relative_to(ROOT))
            if CONTAINER_PAINT.search(src):
                offenders.append(f"{rel} (tablist container)")
            if TAB_PAINT.search(src):
                offenders.append(f"{rel} (tab button)")
        self.assertEqual(
            offenders,
            [],
            "pages painting their own tabs instead of using the platform "
            f"contract: {offenders}",
        )
