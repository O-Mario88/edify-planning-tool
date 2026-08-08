from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class ReportsResponsiveLayoutContractTest(SimpleTestCase):
    """Dense reporting views compose to the screen instead of looking zoomed."""

    def test_report_canvas_aligns_with_the_topbar_and_uses_canonical_headings(self):
        template = _read("templates/pages/reports/index.html")
        css = _read("static/css/platform.css")

        self.assertNotIn("max-w-[1500px]", template)
        self.assertNotIn("mx-auto", template)
        self.assertIn("edify-page-header edify-report-header", template)
        self.assertIn("edify-page-header__lead", template)
        self.assertNotIn("edify-report-header__layout", template)
        self.assertIn(
            '<label for="reports-fiscal-year">Financial year</label>', template
        )
        self.assertIn('id="reports-timeline-title"', template)
        self.assertIn('id="reports-core-targets-title"', template)
        self.assertIn('id="reports-matrix-title"', template)
        self.assertIn('id="reports-insights-title"', template)
        self.assertIn("edify-report-period__heading", template)
        self.assertIn("edify-report-panel--trend lg:col-span-8", template)
        self.assertIn("edify-report-insight-rail lg:col-span-4", template)
        self.assertNotIn("edify-report-panel--trend lg:col-span-6", template)
        self.assertIn("inline-size: 100% !important;", css)
        self.assertIn("max-inline-size: none !important;", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertIn("align-items: stretch !important;", css)
        self.assertIn(".edify-report-insight-rail {", css)
        self.assertIn(
            "padding-inline: 0.75rem !important;",
            css,
        )

    def test_reports_page_has_no_fixed_desktop_rail_or_equal_height_charts(self):
        template = _read("templates/pages/reports/index.html")

        for responsive_hook in (
            "edify-report-workspace",
            "edify-report-timeline",
            "edify-report-summary-grid",
            "edify-report-matrix__table",
            "edify-report-insight-grid",
            "edify-report-trend-chart",
        ):
            self.assertIn(responsive_hook, template)

        self.assertNotIn("min-w-[1400px]", template)
        self.assertNotIn("min-w-[1200px]", template)
        self.assertNotIn("h-60 w-full", template)
        self.assertNotIn("&rarr;", template)
        self.assertIn("items-start", template)

    def test_report_layout_uses_container_width_and_intrinsic_panel_heights(self):
        css = _read("static/css/platform.css")

        self.assertIn("container: edify-report / inline-size", css)
        self.assertIn("@container edify-report (max-width: 72rem)", css)
        self.assertIn("@container edify-report (max-width: 48rem)", css)
        self.assertIn("@container edify-report (max-width: 30rem)", css)
        self.assertIn(".edify-report-insight-grid {", css)
        self.assertIn("align-items: start !important;", css)
        self.assertIn("block-size: auto !important;", css)
        self.assertIn("min-inline-size: 70rem !important;", css)

    def test_period_timelines_wrap_across_report_and_target_pages(self):
        adapter = _read("static/css/consistency.css")
        targets = _read("templates/partials/targets/my_body.html")

        self.assertIn("edify-kpi-strip--timeline", targets)
        self.assertIn(
            "grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr)) !important;",
            adapter,
        )
        self.assertNotIn("flex: 1 0 12.5rem !important;", adapter)
        self.assertNotIn("overflow-x: auto !important;", adapter)

    def test_shared_section_nav_scrolls_only_when_the_active_link_is_hidden(self):
        partial = _read("templates/partials/_section_nav.html")
        components = _read("static/css/components.css")

        self.assertIn("activeEnd > $el.clientWidth", partial)
        self.assertNotIn("active.offsetLeft - 120", partial)
        self.assertIn("font-size: var(--edify-text-micro-size);", components)
