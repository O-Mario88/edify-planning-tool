"""Contracts for the executive analytics workspace redesign."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    from apps.frontend.template_families import read_template

    return read_template(ROOT, relative_path)


class AnalyticsDecisionWorkspaceContractTest(SimpleTestCase):
    def test_overview_leads_with_four_signals_and_geographic_priorities(self):
        """The four signals moved out of the overview and above the tablist on
        2026-09-05: they describe the scope the filters ask for, so they are
        the same on every Analytics tab rather than one section's opening row.
        They still lead the workspace; the panel opens on its decision cards."""
        pulse = _read("templates/partials/analytics/executive_pulse.html")
        cards = _read("templates/partials/analytics/kpi_cards.html")

        self.assertIn("items=executive_kpi_items", pulse)
        self.assertIn("items=additional_kpi_items", pulse)
        scope = _read("templates/partials/analytics/scope.html")
        self.assertLess(scope.index("tiles_template"), scope.index("tab_rail.html"))
        # The country map moved to the Map view of the home dashboards
        # (owner, 2026-09-05): the overview opens on its decision cards.
        self.assertNotIn("regional_performance.html", cards)
        self.assertNotIn("analytics-row--geography", cards)
        self.assertLess(
            cards.index("target_by_district.html"),
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
        # Each filter says how many districts it holds, and a filter that
        # finds nothing says so — in a scope of two critical districts all
        # three filters showed the same rows and read as a broken control
        # (owner, 2026-09-05).
        self.assertIn("target_by_district_summary", service)
        for count in ("districts", "attention", "critical"):
            self.assertIn(
                "{{ target_by_district_summary.%s|default:0 }}</b>" % count, template
            )
        self.assertIn('class="analytics-priority-empty"', template)
        self.assertIn("No critical district in this scope", template)

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
        # A phone map carries SUB-REGION names only (owner, 2026-09-05). All
        # 136 district names at once on a 375px canvas overlap into noise, and
        # the sub-region is the level the table beside the map is grouped by.
        # District identity stays one tap away in zoom, tooltip and focus.
        self.assertIn("#sr-cam .sr-dl{display:none}", map_template)
        # At the plain type step, too. The names were enlarged on 2026-09-07 so
        # a reader could tell them from the district labels they share the map
        # with; a phone has no district labels and a third of the canvas, where
        # the same multiplier only crowds the names into each other.
        self.assertIn(
            "#sr-cam .sr-sl{display:block;letter-spacing:0;stroke-width:.2em;",
            map_template,
        )
        self.assertIn(
            "font-size:var(--edify-svg-text-micro,var(--edify-text-micro-size))",
            map_template[map_template.index("@media (max-width:48rem){") :],
        )
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

    def test_a_bare_htmx_request_gets_a_fragment_not_a_page(self):
        """HX-Request without HX-Target asked for a fragment: the renderer
        answers with the scope, never the shell with a <head>."""

        source = _read("apps/frontend/views/analytics_render.py")
        self.assertIn(
            'if request.headers.get("HX-Request") == "true" and not target:', source
        )
        self.assertIn("return render(request, SCOPE_TEMPLATE, context)", source)

    def test_every_analytics_tab_renders_through_the_one_workspace(self):
        """Every tab of the Analytics rail is the same page.

        Six of the fifteen tabs were separate pages with their own header and
        a different, grouped rail, so the chrome changed as a reader crossed
        them (owner, 2026-09-05: "rebuild and fix ... to make it enterprise
        grade"). A tab's view now hands its panel to render_analytics_section,
        which is the only way the header, filter row, tiles and tablist stay
        fixed around it.
        """

        import inspect

        from django.urls import resolve

        from apps.core.navigation import ANALYTICS_SECTIONS

        for section in ANALYTICS_SECTIONS:
            with self.subTest(section=section["key"]):
                view = inspect.unwrap(resolve(section["url"]).func)
                self.assertIn(
                    "render_analytics_section(",
                    inspect.getsource(view),
                    f"{section['url']} does not render through the workspace",
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

    def test_impact_contribution_results_are_complete_scrollable_tables(self):
        template = _read("templates/partials/analytics/impact_workspace.html")
        css = _read("static/css/pages/analytics-dashboard.css")

        self.assertIn("data-impact-driver-table", template)
        self.assertIn("data-impact-group-table", template)
        self.assertIn("data-impact-lagging-table", template)
        self.assertEqual(template.count('data-mobile-table="scroll"'), 3)
        self.assertEqual(template.count('class="impact-table-scroll"'), 3)
        self.assertEqual(template.count("data-table-scroll-region"), 3)
        self.assertIn('<caption class="sr-only">', template)
        self.assertIn('<th scope="col">Adjusted p</th>', template)
        self.assertIn('<th scope="col">Median SSA Δ</th>', template)
        self.assertIn('<th scope="col">Paired schools</th>', template)
        self.assertIn("driver.schools_unexposed", template)
        self.assertNotIn(
            "{{ row.district }} · {{ row.intervention }} — median Δ",
            template,
        )
        self.assertNotIn(
            'class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3"',
            template,
        )
        self.assertIn(".impact-table-scroll", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("min-inline-size: 126rem", css)
        self.assertIn("min-inline-size: 42rem", css)
        self.assertIn(":focus-visible", css)

    def test_role_dashboards_prioritize_actions_and_disclose_evidence(self):
        pl = _read("templates/partials/analytics/pl/body.html")
        cd = _read("templates/partials/analytics/cd/body.html")
        # Both bodies became shared partials when these sections also became
        # tabs of the one Analytics page (2026-09-05).
        ia = _read("templates/partials/ia/dashboard_body.html")
        reports = _read("templates/partials/analytics/panels/reports.html")

        self.assertIn("Priority intelligence", pl)
        self.assertEqual(pl.count("data-analytics-disclosure"), 3)
        self.assertIn("Leadership priorities", cd)
        self.assertEqual(cd.count("data-analytics-disclosure"), 4)
        self.assertEqual(ia.count("data-analytics-disclosure"), 3)
        # One disclosure since the period matrix moved to the target pages.
        self.assertEqual(reports.count("data-analytics-disclosure"), 1)
