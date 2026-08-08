from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


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

    def test_bespoke_kpi_surfaces_opt_into_the_strip_adapter(self):
        for template in (
            "templates/pages/accounts/dashboard.html",
            "templates/pages/dashboards/special_projects.html",
            "templates/pages/finance/fund_allocation.html",
            "templates/pages/hr/my_performance.html",
            # ia/analytics_dashboard.html is not in this list because it uses
            # the real shared component rather than the legacy adapter — the
            # 2026-07-31 consistency mandate migrated its bespoke `ia-metric`
            # tiles onto components/kpi_strip.html. See
            # test_ia_dashboard_design.test_summary_metrics_use_the_one_approved_kpi_component.
            "templates/pages/notifications/index.html",
            "templates/pages/reports/index.html",
            "templates/pages/schools/upload_preview.html",
            "templates/pages/staff/detail.html",
            "templates/pages/staff/index.html",
            "templates/pages/todos/index.html",
            "templates/partials/analytics/visit_effectiveness_workspace.html",
            "templates/partials/finance/country_budget/root.html",
            "templates/partials/fund_requests/monthly_preview.html",
            "templates/partials/targets/my_body.html",
        ):
            self.assertIn("edify-kpi-strip", _read(template), template)

    def test_specialised_workspaces_use_the_shared_component_not_an_adapter(self):
        migrated = (
            "templates/pages/dashboards/main.html",
            "templates/pages/hr/module_workspace.html",
            "templates/pages/partners/index.html",
            "templates/partials/analytics/impact_workspace.html",
            "templates/partials/dashboards/admin/_platform_operations.html",
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
