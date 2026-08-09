"""One segmented tab design, owned by platform.css, used by every page.

The app had KPI-card tabs, underlined rails, segmented pills and bare flex
rows. The shared contract now owns the muted rail and raised active surface;
pages are not allowed to paint their own.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
PLATFORM_CSS = ROOT / "static" / "css" / "platform.css"
TEMPLATES = ROOT / "templates"

# Container backgrounds/padding and button-ish classes on a tab are the marks
# of a page painting its own tab strip.
#
# Matched in two passes — find the tag, then read its class list — rather than
# with one pattern spanning both. Written as a single expression it nests
# `[^>]*` inside `class="[^"]*`, and a template with a long tag can then make
# the engine backtrack exponentially; CodeQL flags exactly that shape.
CONTAINER_PAINT = re.compile(
    r"bg-slate-\d|bg-white|rounded-surface|rounded-control|\bp-1\b|border\b"
)
TAB_PAINT = re.compile(r"btn-premium|edify-primary-solid|shadow-sm")

# One tag, non-greedy to its own closing bracket. No nested quantifier.
TAG = re.compile(r"<[^<>]*>", re.S)
CLASS_ATTR = re.compile(r'class="([^"]*)"')


def _painted(src: str, role: str, paint: re.Pattern) -> bool:
    """True when any tag carrying `role` has a painting class."""
    marker = f'role="{role}"'
    for tag in TAG.findall(src):
        if marker not in tag:
            continue
        classes = CLASS_ATTR.search(tag)
        if classes and paint.search(classes.group(1)):
            return True
    return False


class TabContractTest(SimpleTestCase):
    def setUp(self):
        self.css = PLATFORM_CSS.read_text()

    def test_the_contract_is_the_canonical_segmented_rail(self):
        contract = self.css.split("Tabs, pills and workflow state", 1)[1]

        self.assertIn('[role="tablist"]', contract)
        self.assertIn("[data-edify-tablist]", contract)
        self.assertIn("display: flex !important", contract)
        self.assertIn("gap: 0.25rem !important", contract)
        self.assertIn("padding: 0.25rem !important", contract)
        self.assertIn("border: 1px solid var(--edify-border) !important", contract)
        self.assertIn("background: var(--edify-surface-muted) !important", contract)
        self.assertIn("border-radius: var(--edify-radius-sm) !important", contract)

    def test_the_selected_tab_is_a_raised_active_surface(self):
        contract = self.css.split("Tabs, pills and workflow state", 1)[1]

        self.assertIn('[role="tab"][aria-selected="true"]', contract)
        self.assertIn('[data-edify-tab][aria-pressed="true"]', contract)
        self.assertIn('[data-edify-tab][aria-current="true"]', contract)
        self.assertIn("background: var(--edify-surface-raised) !important", contract)
        self.assertIn("color: var(--edify-accent) !important", contract)
        self.assertIn("box-shadow: var(--edify-shadow-sm) !important", contract)
        self.assertNotIn("border-block-end-color: var(--edify-accent)", contract)

    def test_specialist_and_role_routed_tabs_share_the_same_contract(self):
        contract = self.css.split("Tabs, pills and workflow state", 1)[1]

        for selector in (
            ".pto-tabs",
            ".sp-period-tabs",
            ".spp-tabs",
            ".tt-segmented",
            ".oversight-entity-tabs",
            ".oversight-entity-tabs__link.is-active",
            ".oversight-entity-tabs__count",
            ".edify-section-nav__clusters",
            ".edify-section-nav__inner",
            ".edify-section-nav__cluster.is-active",
            ".edify-section-nav__link.is-active",
        ):
            self.assertIn(selector, contract)

    def test_analytics_route_navigation_has_no_legacy_underline(self):
        contract = self.css.split("Tabs, pills and workflow state", 1)[1]

        self.assertIn("main .edify-section-nav {", contract)
        self.assertIn("border: 0 !important", contract)
        self.assertIn("border-block-end-color: transparent !important", contract)

    def test_night_mode_uses_a_readable_blue_for_the_selected_label(self):
        """--edify-accent as text on the night surface falls under AA."""
        contract = self.css.split("--edify-accent is a brand blue", 1)[1]
        self.assertIn('[role="tab"][aria-selected="true"]', contract)
        self.assertIn('[data-edify-tab][aria-pressed="true"]', contract)
        self.assertIn("color: var(--edify-info)", contract)
        self.assertIn("background: var(--edify-surface-raised) !important", contract)

    def test_legacy_alpine_tab_rows_opt_into_the_shared_contract(self):
        sources = (
            "templates/pages/messages/index.html",
            "templates/partials/analytics/cd/budget_finance.html",
            "templates/pages/hr/my_performance.html",
            "templates/partials/professional_development/body.html",
            "templates/pages/ssa/upload_preview.html",
        )

        for source in sources:
            markup = (ROOT / source).read_text()
            with self.subTest(source=source):
                self.assertIn("data-edify-tablist", markup)
                self.assertIn("data-edify-tab", markup)
                self.assertIn(":aria-pressed=", markup)


class NoPageStylesItsOwnTabsTest(SimpleTestCase):
    def test_no_template_paints_its_own_tab_strip(self):
        offenders = []
        for path in TEMPLATES.rglob("*.html"):
            src = path.read_text()
            if 'role="tablist"' not in src:
                continue
            rel = str(path.relative_to(ROOT))
            if _painted(src, "tablist", CONTAINER_PAINT):
                offenders.append(f"{rel} (tablist container)")
            if _painted(src, "tab", TAB_PAINT):
                offenders.append(f"{rel} (tab button)")
        self.assertEqual(
            offenders,
            [],
            "pages painting their own tabs instead of using the platform "
            f"contract: {offenders}",
        )
