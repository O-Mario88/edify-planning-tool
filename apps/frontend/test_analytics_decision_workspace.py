"""Contracts for the executive analytics workspace redesign."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class AnalyticsDecisionWorkspaceContractTest(SimpleTestCase):
    def test_overview_leads_with_four_signals_and_geographic_priorities(self):
        cards = _read("templates/partials/analytics/kpi_cards.html")

        self.assertIn("items=executive_kpi_items", cards)
        self.assertIn("items=additional_kpi_items", cards)
        self.assertIn("analytics-row--geography", cards)
        geography = cards.split(
            'class="analytics-layout-row analytics-row--geography"', 1
        )[1]
        geography = geography.split("</div>", 2)[0]
        self.assertIn("regional_performance.html", geography)
        self.assertNotIn("target_by_district.html", geography)
        self.assertLess(
            cards.index("regional_performance.html"),
            cards.index("target_by_district.html"),
        )
        self.assertLess(
            cards.index("regional_performance.html"),
            cards.index("recommended_insights.html"),
        )
        self.assertIn("analytics-evidence-disclosure", cards)

    def test_district_priorities_are_complete_grouped_and_ranked(self):
        service = _read("apps/analytics/analytics_dashboard_service.py")
        template = _read("templates/partials/analytics/target_by_district.html")

        self.assertIn('select_related("region", "sub_region")', service)
        self.assertIn("target_by_district_groups", service)
        self.assertNotIn("shown_districts = list(all_districts[:8])", service)
        self.assertIn("grouped by sub-region", template)
        self.assertIn("Needs attention", template)
        self.assertIn("View all {{ group.districts|length }} districts", template)

    def test_map_keeps_original_visual_while_distribution_uses_new_layout(self):
        map_template = "\n".join(
            (
                _read("templates/partials/analytics/regional_performance.html"),
                _read("static/css/components.css"),
            )
        )
        layout = _read("static/css/pages/analytics-dashboard.css")

        self.assertIn(
            'class="sr-map-viewport relative w-full aspect-square"', map_template
        )
        self.assertNotIn("sr-map-stage", map_template)
        self.assertNotIn("sr-subregion-zoomed", map_template)
        self.assertNotIn("#sr-cam:not(.sr-zoomed) .sr-labels", map_template)
        self.assertNotIn("#sr-cam:not(.sr-zoomed) .sr-school-pins", map_template)
        self.assertNotIn("max-block-size: 350px", layout)
        self.assertIn("sr-map-layout flex flex-col xl:flex-row", map_template)
        self.assertIn("sr-map-viewport", map_template)
        self.assertIn("sr-distribution-panel", map_template)
        self.assertIn('data-mobile-table="fit"', map_template)
        self.assertNotIn('data-mobile-table="scroll"', map_template)
        self.assertIn("sr-distribution-col--name", map_template)
        self.assertIn("@media (max-width: 64rem)", layout)
        self.assertNotIn("min-inline-size: 34rem", layout)
        self.assertIn("overflow-x: clip", layout)
        self.assertIn("table-layout: fixed", layout)
        self.assertIn("padding: 1rem 0.5rem 0", layout)
        self.assertIn("@media (max-width:48rem)", map_template)
        self.assertIn("#sr-cam .sr-dl{display:none}", map_template)
        self.assertIn("#sr-cam .sr-sl{display:block}", map_template)
        cluster_template = _read(
            "templates/partials/analytics/cluster_performance.html"
        )
        self.assertIn('data-mobile-table="scroll"', cluster_template)

    def test_analytics_navigation_exposes_named_workspace_areas(self):
        navigation = _read("apps/core/navigation.py")
        partial = _read("templates/partials/_section_nav.html")

        for label in (
            "Overview",
            "School Performance",
            "Impact & Decisions",
            "Delivery & Quality",
            "Reporting",
        ):
            self.assertIn(label, navigation)
        self.assertIn("workspace.groups", partial)
        self.assertIn("edify-section-nav__cluster", partial)
        self.assertIn("edify-section-nav__view-menu", partial)
        self.assertNotIn("edify-section-nav__inner--group", partial)
        self.assertNotIn(
            'workspace.key == "analytics" and workspace.groups|length > 1',
            partial,
        )
        self.assertIn('x-show="open"', partial)
        self.assertNotIn('role="tab"', partial)
        self.assertIn(
            "Admin can inspect every role-specific Overview cockpit", navigation
        )

    def test_every_analytics_route_uses_the_enterprise_anatomy(self):
        templates = (
            "templates/pages/analytics/index.html",
            "templates/pages/analytics/pl_analytics.html",
            "templates/pages/analytics/cd_analytics.html",
            "templates/pages/analytics/impact.html",
            "templates/pages/analytics/visit_effectiveness.html",
            "templates/pages/analytics/declining_schools.html",
            "templates/pages/analytics/closure_quality.html",
            "templates/pages/analytics/closure_impact.html",
            "templates/pages/analytics/publishing_status.html",
            "templates/pages/ssa/performance.html",
            "templates/pages/decisions/index.html",
            "templates/pages/audit/decision_log.html",
            "templates/pages/core_schools/leadership.html",
            "templates/pages/reports/index.html",
            "templates/pages/closure/completed_activities.html",
            "templates/pages/projects/analytics.html",
            "templates/pages/ia/analytics_dashboard.html",
        )
        for template in templates:
            source = _read(template)
            self.assertIn("data-analytics-enterprise", source, template)
            self.assertIn("analytics_decision_frame.html", source, template)
            self.assertIn("analytics-dashboard.css", source, template)

    def test_enterprise_layer_is_scoped_accessible_and_personalized(self):
        base = _read("templates/base.html")
        css = _read("static/css/pages/analytics-dashboard.css")
        script = _read("static/js/analytics-workspace.js")
        decision_frame = _read("templates/components/analytics_decision_frame.html")

        self.assertIn("analytics-workspace.js", base)
        self.assertIn("[data-analytics-enterprise]", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("content-visibility: auto", css)
        self.assertIn("localStorage", script)
        self.assertIn("edify:analytics-interaction", script)
        self.assertIn('aria-label="Decision and data context"', decision_frame)

    def test_role_dashboards_prioritize_actions_and_disclose_evidence(self):
        pl = _read("templates/partials/analytics/pl/body.html")
        cd = _read("templates/partials/analytics/cd/body.html")
        ia = _read("templates/pages/ia/analytics_dashboard.html")
        reports = _read("templates/pages/reports/index.html")

        self.assertIn("Priority intelligence", pl)
        self.assertEqual(pl.count("data-analytics-disclosure"), 3)
        self.assertIn("Leadership priorities", cd)
        self.assertEqual(cd.count("data-analytics-disclosure"), 4)
        self.assertEqual(ia.count("data-analytics-disclosure"), 3)
        self.assertEqual(reports.count("data-analytics-disclosure"), 2)
