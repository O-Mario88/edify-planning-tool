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
            # ia/analytics_dashboard.html graduated off the legacy strip: the
            # 2026-07-30 redesign gave it its own designed metric system,
            # held to account by test_ia_dashboard_design.py (which forbids
            # the legacy marker on that page).
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
            self.assertIn("legacy-kpi-strip", _read(template), template)

    def test_specialised_workspaces_are_covered_by_the_same_adapter(self):
        adapter = _read("static/css/consistency.css")

        for selector in (
            ".admin-kpi-strip",
            ".partner-kpi-grid",
            ".tt-kpi-strip",
            ".sp-kpis",
            ".sp-kpi-grid",
            ".spp-kpi-grid",
            ".spa-kpi-grid",
        ):
            self.assertIn(selector, adapter)

        # The adapter renders themed cards (white/dark/blue-glass via design
        # tokens) and wraps 2-per-row on phones — never a navy panel or a
        # sideways-scrolling carousel.
        self.assertIn("background: var(--edify-surface) !important", adapter)
        self.assertIn("border: 1px solid var(--edify-border) !important", adapter)
        self.assertIn("repeat(2, minmax(0, 1fr))", adapter)
        self.assertNotIn("scroll-snap-type: inline mandatory", adapter)
        for navy_hex in ("#052d50", "#0a4169", "#07385f"):
            self.assertNotIn(navy_hex, adapter)
