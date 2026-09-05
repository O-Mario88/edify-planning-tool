from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _reports_source() -> str:
    """The page and the panel it includes, as one document.

    Reports became a tab of the one Analytics page (2026-09-05): the body lives
    in the panel and the standalone page is a frame around the same panel.
    """

    return "\n".join(
        (
            _read("templates/pages/reports/index.html"),
            _read("templates/partials/analytics/panels/reports.html"),
        )
    )


class ReportsResponsiveLayoutContractTest(SimpleTestCase):
    """Dense reporting views compose to the screen instead of looking zoomed."""

    def test_report_canvas_aligns_with_the_topbar_and_uses_canonical_headings(self):
        template = _reports_source()
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

    def test_the_period_matrix_moved_to_the_target_pages(self):
        """"Cumulative progress by time period" belongs with the targets it
        measures: My Target carries it as an accordion, and Team Target inside
        each team member's row (owner, 2026-09-05)."""

        self.assertNotIn("edify-report-matrix__table", _reports_source())
        self.assertNotIn("Cumulative progress by time period", _reports_source())
        shared = _read("templates/partials/targets/_period_matrix.html")
        self.assertIn("Cumulative progress by time period", shared)
        for path in (
            "templates/partials/targets/my_body.html",
            "templates/partials/targets/team/body.html",
        ):
            self.assertIn("partials/targets/_period_matrix.html", _read(path), path)

    def test_reports_page_has_no_fixed_desktop_rail_or_equal_height_charts(self):
        template = _reports_source()

        for responsive_hook in (
            "edify-report-workspace",
            "edify-report-timeline",
            "components/kpi_strip.html",
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

    def test_my_target_opens_on_the_progress_table_not_period_cards(self):
        """Six period cards of the weighted roll-up said "0 / 0" six times when
        nothing was agreed; the page opens on the progress table with every
        priority instead (owner, 2026-09-05)."""
        targets = _read("templates/partials/targets/my_body.html")

        self.assertNotIn("target-period-progression", targets)
        self.assertLess(
            targets.index("partials/targets/_period_matrix.html"),
            targets.index("partials/targets/strategic_priority_overview.html"),
        )

    def test_shared_section_nav_scrolls_only_when_the_active_link_is_hidden(self):
        partial = _read("templates/partials/_section_nav.html")
        components = _read("static/css/components.css")

        self.assertIn("activeEnd > $el.clientWidth", partial)
        self.assertNotIn("active.offsetLeft - 120", partial)
        self.assertIn("font-size: var(--edify-text-micro-size);", components)
