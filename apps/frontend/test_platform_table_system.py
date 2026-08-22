"""Platform-wide responsive table anatomy and styling contracts."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PlatformResponsiveTableSystemTest(SimpleTestCase):
    def test_scroll_tables_keep_native_anatomy_at_every_breakpoint(self):
        styles = _read("static/css/components/mobile-micro-ux.css")
        selector = (
            ':is(.edify-mobile-table--scroll, .edify-mobile-table--fit, '
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

    def test_data_tables_get_readable_width_tiers_instead_of_crushed_cells(self):
        behavior = _read("static/js/micro-ux.js")
        styles = _read("static/css/components/mobile-micro-ux.css")

        self.assertIn("tableColumnCount(table) > 3", behavior)
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

        self.assertIn("mobile-micro-ux.css' %}?v=20260822tables1", base)
        self.assertIn("micro-ux.js' %}?v=20260822tables1", base)
