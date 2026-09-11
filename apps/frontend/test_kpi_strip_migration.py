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
    from apps.frontend.template_families import read_template

    return read_template(ROOT, relative_path)


class KpiStripMigrationTests(SimpleTestCase):
    """Keep contextual summaries unified without reviving KPI card grids."""

    def test_data_driven_role_dashboards_use_the_shared_component(self):
        for template in (
            "templates/partials/analytics/cd/body.html",
            "templates/partials/analytics/pl/body.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/dashboards/pl/body.html",
            "templates/partials/dashboards/hr/operations.html",
            "templates/partials/debriefs/dashboard_body.html",
            "templates/partials/hr/pd_dashboard/body.html",
            "templates/partials/professional_development/body.html",
        ):
            source = _read(template)
            self.assertIn("components/context_metrics.html", source, template)

    def test_previously_bespoke_kpi_surfaces_use_the_shared_component(self):
        for template in (
            "templates/partials/finance/fund_workspace.html",
            "templates/pages/hr/my_performance.html",
            # ia/analytics_dashboard.html is not in this list because it uses
            # the real shared component rather than the legacy adapter — the
            # 2026-07-31 consistency mandate migrated its bespoke `ia-metric`
            # tiles onto components/context_metrics.html. See
            # test_ia_dashboard_design.test_summary_metrics_use_the_one_approved_kpi_component.
            "templates/pages/notifications/index.html",
            "templates/partials/analytics/panels/reports.html",
            "templates/pages/staff/detail.html",
            "templates/pages/staff/index.html",
            "templates/pages/todos/index.html",
            "templates/partials/analytics/visit_effectiveness_workspace.html",
            "templates/partials/finance/country_budget/root.html",
            "templates/partials/fund_requests/kpis.html",
            "templates/partials/targets/my_body.html",
        ):
            source = _read(template)
            self.assertIn("components/context_metrics.html", source, template)
            self.assertNotIn("edify-kpi-strip", source, template)

    def test_period_and_timeline_controls_are_not_misclassified_as_kpis(self):
        fund_allocation = _read("templates/pages/finance/fund_allocation.html")
        targets = _read("templates/partials/targets/my_body.html")
        self.assertIn("budget-period-rail", fund_allocation)
        # The period cards became the progress table (2026-09-05); the table
        # is a disclosure, not a KPI strip.
        self.assertIn('<details class="edify-disclosure" open>', targets)
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
                template != ROOT / "templates/components/context_metrics.html"
                and 'data-component="kpi-card"' in source
            ):
                violations.append(
                    f"{template.relative_to(ROOT)}: direct KPI-card markup"
                )
        self.assertEqual(violations, [])

    def test_shared_component_has_one_continuous_strip_visual_path(self):
        source = _read("templates/components/context_metrics.html")
        styles = _read("static/css/components.css")
        context = styles[styles.index("CONTEXT METRICS") :]
        self.assertIn('data-component="context-metric"', source)
        self.assertIn('class="context-metrics__sentence" role="list"', source)
        self.assertNotIn('data-component="kpi-card"', source)
        self.assertNotIn("kpi-strip__", source)
        self.assertIn("{% firstof item.label item.canonical_label %}", source)
        self.assertIn("scroll-snap-type: x mandatory;", context)
        self.assertIn("box-shadow:", context)
        self.assertNotIn("background-image:", context)
        self.assertNotIn("grid-template-columns:", context)

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
            self.assertIn("components/context_metrics.html", source, template)
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
                source.count("components/context_metrics.html"),
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
                source.count("components/context_metrics.html"),
                1,
                f"{template} must not duplicate KPI DOM for mobile and desktop",
            )

    def test_fund_requests_have_one_headline_kpi_tray(self):
        root = _read("templates/partials/fund_requests/root.html")
        self.assertIn("partials/fund_requests/kpis.html", root)
        self.assertNotIn("partials/fund_requests/monthly_preview.html", root)
        self.assertFalse(
            (ROOT / "templates/partials/fund_requests/monthly_preview.html").exists()
        )

    def test_special_projects_dashboard_distributes_metrics_into_work(self):
        source = _read("templates/pages/dashboards/special_projects.html")
        operations = _read(
            "templates/partials/dashboards/special_projects/operations.html"
        )
        self.assertIn("{% kpi_strip %}", source)
        self.assertIn("active_project_count", source)
        self.assertIn("activities_in_plan", source)
        self.assertIn("evidence_pending", operations)
        self.assertNotIn("components/kpi_card.html", source)
