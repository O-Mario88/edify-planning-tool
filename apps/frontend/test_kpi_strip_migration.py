from pathlib import Path
import re

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]
LEGACY_KPI_CLASSES = {
    "admin-kpi",
    "admin-kpi-strip",
    "card-kpi",
    "edify-kpi-card",
    "edify-kpi-strip",
    "hcos-metrics",
    "ia-metric",
    "mobile-home-metric",
    "partner-kpi-card",
    "partner-kpi-grid",
    "sp-kpi",
    "sp-kpi-grid",
    "sp-kpis",
    "spa-kpi",
    "spa-kpi-grid",
    "spp-kpi",
    "spp-kpi-grid",
    "tt-kpi",
    "tt-kpi-strip",
}


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class KpiStripMigrationTests(SimpleTestCase):
    """Keep KPI summaries unified instead of regressing to loose card grids."""

    def test_data_driven_role_dashboards_use_the_shared_component(self):
        for template in (
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/debriefs/dashboard_body.html",
            "templates/partials/hr/pd_dashboard/body.html",
            "templates/partials/professional_development/body.html",
        ):
            source = _read(template)
            self.assertIn("components/kpi_strip.html", source, template)

    def test_previously_bespoke_kpi_surfaces_use_the_shared_component(self):
        for template in (
            "templates/pages/accounts/dashboard.html",
            "templates/pages/hr/my_performance.html",
            # ia/analytics_dashboard.html is not in this list because it uses
            # the real shared component rather than the legacy adapter — the
            # 2026-07-31 consistency mandate migrated its bespoke `ia-metric`
            # tiles onto components/kpi_strip.html. See
            # test_ia_dashboard_design.test_summary_metrics_use_the_one_approved_kpi_component.
            "templates/pages/notifications/index.html",
            "templates/pages/reports/index.html",
            "templates/pages/staff/detail.html",
            "templates/pages/staff/index.html",
            "templates/pages/todos/index.html",
            "templates/partials/analytics/visit_effectiveness_workspace.html",
            "templates/partials/finance/country_budget/root.html",
            "templates/partials/fund_requests/kpis.html",
            "templates/partials/targets/my_body.html",
        ):
            source = _read(template)
            self.assertIn("components/kpi_strip.html", source, template)
            self.assertNotIn("edify-kpi-strip", source, template)

    def test_period_and_timeline_controls_are_not_misclassified_as_kpis(self):
        fund_allocation = _read("templates/pages/finance/fund_allocation.html")
        targets = _read("templates/partials/targets/my_body.html")
        self.assertIn("budget-period-rail", fund_allocation)
        self.assertIn("target-period-progression", targets)
        self.assertNotIn("edify-kpi-strip", fund_allocation)

    def test_no_template_bypasses_the_platform_kpi_renderer(self):
        violations = []
        for template in (ROOT / "templates").rglob("*.html"):
            if template.name == "kpi_card.html":
                continue
            source = template.read_text(encoding="utf-8")
            for marker in (
                "edify-kpi-strip",
                "mobile-home-metric",
                "components/kpi_card.html",
                'variant="context"',
            ):
                if marker in source:
                    violations.append(f"{template.relative_to(ROOT)}: {marker}")
        self.assertEqual(violations, [])

    def test_no_template_renders_a_competing_kpi_class_family(self):
        violations = []
        for template in (ROOT / "templates").rglob("*.html"):
            if template.name == "kpi_card.html":
                continue
            source = template.read_text(encoding="utf-8")
            classes = {
                token
                for value in re.findall(r'class="([^"]*)"', source)
                for token in value.split()
            }
            legacy = sorted(classes & LEGACY_KPI_CLASSES)
            if legacy:
                violations.append(f"{template.relative_to(ROOT)}: {', '.join(legacy)}")
            if (
                template != ROOT / "templates/components/kpi_strip.html"
                and 'data-component="kpi-card"' in source
            ):
                violations.append(
                    f"{template.relative_to(ROOT)}: direct KPI-card markup"
                )
        self.assertEqual(violations, [])

    def test_shared_component_has_one_kpi_tile_visual_path(self):
        source = _read("templates/components/kpi_strip.html")
        styles = _read("static/css/components.css")
        self.assertNotIn('variant == "context"', source)
        self.assertNotIn("kpi-context-summary", source)
        self.assertIn("kpi-strip--executive", source)
        self.assertNotIn(".theme-blue .kpi-strip {", styles)
        self.assertIn(".kpi-strip.kpi-strip--executive {", styles)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr));", styles)
        self.assertIn("background-color: var(--edify-surface);", styles)
        self.assertIn("clip-path: inset(50%);", styles)
        self.assertIn("box-shadow: 0 2px 3px", styles)
        # `--fresh`, not `--neutral`: "Current" reports that the DATA is up
        # to date, which is one meaning on every tile. It is the one pill the
        # per-tile accent tint deliberately does not repaint, and it sits
        # beside "Pending", which means the opposite and stays muted.
        self.assertIn('kpi-strip__trend--fresh">Current', source)
        self.assertIn("{% firstof item.label item.canonical_label %}", source)
        # Two lines, not three. The point of the clamp is that a long label
        # cannot push the number down the card — the value is what the tile
        # exists to show, and three reserved lines of label moved it below
        # the fold on a six-up strip. Clamping still happens; it just happens
        # sooner.
        self.assertIn("-webkit-line-clamp: 2;", styles)
        self.assertIn("white-space: normal;", styles)

    def test_specialised_workspaces_use_the_shared_component_not_an_adapter(self):
        migrated = (
            "templates/pages/dashboards/main.html",
            "templates/pages/hr/module_workspace.html",
            "templates/pages/partners/index.html",
            "templates/partials/analytics/impact_workspace.html",
            "templates/partials/projects/analytics_workspace.html",
            "templates/partials/projects/my_plan_workspace.html",
            "templates/partials/projects/planning_workspace.html",
            "templates/partials/ssa/performance_workspace.html",
            "templates/partials/targets/team/body.html",
        )
        legacy_markers = (
            "admin-kpi-strip",
            "partner-kpi-grid",
            "tt-kpi-strip",
            "sp-kpis",
            "sp-kpi-grid",
            "spp-kpi-grid",
            "spa-kpi-grid",
            "hcos-metrics",
        )
        for template in migrated:
            source = _read(template)
            self.assertIn("components/kpi_strip.html", source, template)
            for marker in legacy_markers:
                self.assertNotIn(marker, source, f"{template}: {marker}")

    def test_role_dashboards_render_one_kpi_component_per_page(self):
        for template in (
            "templates/pages/dashboards/main.html",
            "templates/pages/dashboards/cceo.html",
            "templates/pages/dashboards/rvp.html",
            "templates/pages/ia/analytics_dashboard.html",
        ):
            source = _read(template)
            self.assertEqual(
                source.count("components/kpi_strip.html"),
                1,
                f"{template} must not duplicate KPI DOM for mobile and desktop",
            )

        for template in (
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/hr/body.html",
            "templates/partials/dashboards/pl/body.html",
        ):
            source = _read(template)
            self.assertEqual(
                source.count("components/kpi_strip.html"),
                1,
                f"{template} must not duplicate KPI DOM for mobile and desktop",
            )

    def test_weekly_fund_requests_have_no_monthly_kpi_tray(self):
        root = _read("templates/partials/fund_requests/root.html")
        monthly = _read("templates/partials/fund_requests/monthly_preview.html")
        self.assertNotIn("partials/fund_requests/kpis.html", root)
        self.assertNotIn("components/kpi_strip.html", root)
        self.assertNotIn("partials/fund_requests/monthly_preview.html", root)
        self.assertNotIn("components/kpi_strip.html", monthly)

    def test_special_projects_dashboard_uses_shared_executive_tray(self):
        source = _read("templates/pages/dashboards/special_projects.html")
        self.assertIn("components/kpi_strip.html", source)
        self.assertIn('variant="executive"', source)
        self.assertNotIn("components/kpi_card.html", source)
