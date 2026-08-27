"""Regression contracts for the platform-wide intrinsic density system."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class PlatformLayoutDensityContractTest(SimpleTestCase):
    def test_shared_layer_removes_duplicate_component_spacing(self):
        css = _read("static/css/consistency.css")

        self.assertIn("CONDENSED PLATFORM LAYOUT CONTRACT", css)
        self.assertIn('main :is([class*="space-y-"], [class*="gap-"])', css)
        self.assertIn("margin-block-end: 0 !important;", css)
        self.assertIn("--edify-content-section-gap: 0.875rem;", css)

    def test_cards_and_orphan_grid_items_use_intrinsic_space(self):
        pages = _read("static/css/pages.css")
        bridge = _read("static/css/consistency.css")
        admin = _read("static/css/admin-dashboard.css")

        row = pages.split(".edify-card-row {", 1)[1].split("}", 1)[0]
        self.assertIn("align-items: start", row)
        self.assertNotIn("stretch", row)
        self.assertIn("block-size: auto", pages)
        self.assertIn("grid-column: 1 / -1;", bridge)
        self.assertIn(".admin-grid", admin)
        self.assertIn("align-items: start", admin)
        self.assertNotIn("grid-auto-flow: dense", bridge)

    def test_executive_kpi_rows_consume_the_full_tray(self):
        css = _read("static/css/components.css")
        balanced = css.split("7 = 4 + 3", 1)[1].split(
            "Phones never scroll a KPI strip", 1
        )[0]

        self.assertIn("grid-template-columns: repeat(12", balanced)
        self.assertIn("grid-column: span 3", balanced)
        self.assertIn("grid-column: span 4", balanced)
        self.assertIn("last-child:nth-child(odd)", css)
        self.assertNotIn("grid-auto-flow: dense", balanced)

    def test_empty_regions_collapse_without_shrinking_data_canvases(self):
        css = _read("static/css/consistency.css")
        density = css.split("CONDENSED PLATFORM LAYOUT CONTRACT", 1)[1]

        self.assertIn('[id$="-errors"]', density)
        self.assertIn(":empty:not(.edify-visually-hidden, .sr-only)", density)
        self.assertIn(".edify-empty-state", density)
        self.assertIn("min-block-size: 0 !important;", density)
        self.assertIn("table tbody > tr:only-child > td[colspan]", density)
        self.assertIn(".spa-table-empty", density)
        self.assertIn(".pto-empty-state", density)
        self.assertIn("[data-empty-state]", density)
        self.assertIn('[class~="py-8"]', density)
        self.assertIn("padding-block: 0 !important;", density)
        for data_canvas in ("canvas", "map", "upload", "chart"):
            self.assertNotIn(f".{data_canvas}", density)

    def test_mobile_and_desktop_page_edges_share_the_compact_rhythm(self):
        css = _read("static/css/consistency.css")
        base = _read("templates/base.html")

        self.assertIn("padding: 1rem var(--edify-page-gutter) !important;", css)
        self.assertIn("padding-block: 0.75rem !important;", css)
        self.assertIn('[class~="sm:p-6"]', css)
        self.assertIn(".space-y-5, .space-y-6", css)
        self.assertIn("20260827density2", base)

    def test_shared_feature_grids_do_not_force_blank_equal_height_surfaces(self):
        platform = _read("static/css/platform.css")
        pages = _read("static/css/pages.css")
        admin = _read("static/css/admin-dashboard.css")
        help_center = _read("static/css/help-center.css")

        for selector in ("main .platform-major-grid", "main .platform-support-grid"):
            rule = platform.split(f"{selector} {{", 1)[1].split("}", 1)[0]
            self.assertIn("align-items: start", rule)
            self.assertNotIn("stretch", rule)

        for selector in (
            ".pto-command-grid",
            ".pto-operations-grid",
            ".tt-rail",
            ".tt-lower-stack",
        ):
            rule = pages.split(f"{selector} {{", 1)[1].split("}", 1)[0]
            self.assertIn("align-items: start", rule)

        self.assertIn(".tt-rail-panel { height: auto;", pages)
        self.assertIn(".tt-lower-stack > * { min-width: 0; height: auto; }", pages)
        self.assertIn(".pto-request-list {\n  min-height: 0;", pages)
        self.assertIn(".admin-priority-schools { min-height: auto; }", admin)
        self.assertIn(".help-topic-grid {", help_center)
        self.assertIn("align-items: start", help_center)
        self.assertIn("min-block-size: 0", help_center)

    def test_knowledge_center_cards_do_not_force_row_height(self):
        index = _read("templates/pages/help/index.html")
        category = _read("templates/pages/help/category.html")

        self.assertIn("grid items-start", index)
        self.assertIn("grid items-start", category)
        self.assertNotIn("block h-full", index)
        self.assertNotIn("block h-full", category)
