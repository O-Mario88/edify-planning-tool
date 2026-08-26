"""Platform-wide responsive table anatomy and styling contracts."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)


def _cache_buster(base: str, asset: str) -> str:
    """The ?v= token base.html serves one asset under, or "" if it has none.

    Pinning the literal token made every stylesheet edit red these tests while
    proving nothing about them: a hard-coded string cannot tell whether two
    assets that must ship together actually match, and it goes stale the moment
    anyone bumps it. What the tests are named for is the pairing, so that is
    what they now read.
    """
    match = re.search(re.escape(asset) + r"' %\}\?v=([A-Za-z0-9._-]+)", base)
    return match.group(1) if match else ""


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PlatformResponsiveTableSystemTest(SimpleTestCase):
    def test_scroll_tables_keep_native_anatomy_at_every_breakpoint(self):
        styles = _read("static/css/components/mobile-micro-ux.css")
        selector = (
            ":is(.edify-mobile-table--scroll, .edify-mobile-table--fit, "
            'table[data-mobile-table="fit"])'
        )

        self.assertIn(selector, styles)
        self.assertIn(":is(.edify-workspace, .drawer-body)", styles)
        self.assertIn("display: table !important", styles)
        self.assertIn("> thead {", styles)
        self.assertIn("display: table-header-group !important", styles)
        self.assertIn("> tbody {", styles)
        self.assertIn("display: table-row-group !important", styles)
        self.assertIn("> :is(thead, tbody, tfoot) > tr {", styles)
        self.assertIn("display: table-row !important", styles)
        self.assertIn("> :is(thead, tbody, tfoot) > tr > :is(th, td) {", styles)
        self.assertIn("display: table-cell !important", styles)

    def test_every_data_table_scrolls_and_wide_tables_get_readable_width_tiers(self):
        behavior = _read("static/js/micro-ux.js")
        styles = _read("static/css/components/mobile-micro-ux.css")

        self.assertIn("Every visible table keeps single-line cells", behavior)
        self.assertIn("return table.getAttribute('role') !== 'presentation'", behavior)
        self.assertIn("columnCount > 8 ? 'xwide'", behavior)
        self.assertIn("columnCount > 5 ? 'wide'", behavior)
        self.assertIn('data-edify-table-width="standard"', styles)
        self.assertIn("max(44rem, 100%)", styles)
        self.assertIn('data-edify-table-width="wide"', styles)
        self.assertIn("max(56rem, 100%)", styles)
        self.assertIn('data-edify-table-width="xwide"', styles)
        self.assertIn("max(68rem, 100%)", styles)

    def test_scroll_regions_are_named_keyboard_accessible_and_stable(self):
        behavior = _read("static/js/micro-ux.js")
        styles = _read("static/css/components/mobile-micro-ux.css")

        self.assertIn("ensureTableCaption", behavior)
        self.assertIn("Scrollable table: ", behavior)
        self.assertIn("region.setAttribute('role', 'region')", behavior)
        self.assertIn("region.setAttribute('tabindex', '0')", behavior)
        self.assertIn("overflow: auto", styles)
        self.assertIn("scrollbar-width: thin", styles)

    def test_cceo_table_reuses_its_existing_scroll_region(self):
        template = _read("templates/partials/dashboards/pl/cceo_performance.html")

        self.assertIn("pl-cceo-performance-scroll", template)
        self.assertIn("data-table-scroll-region", template)
        self.assertIn('data-mobile-table="scroll"', template)

    def test_table_assets_are_cache_busted_together(self):
        base = _read("templates/base.html")

        self.assertNotEqual(_cache_buster(base, "mobile-micro-ux.css"), "")
        self.assertEqual(
            _cache_buster(base, "mobile-micro-ux.css"),
            _cache_buster(base, "micro-ux.js"),
        )
