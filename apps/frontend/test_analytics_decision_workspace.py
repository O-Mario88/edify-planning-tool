"""Contracts for the executive analytics workspace redesign."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    from apps.frontend.template_families import read_template

    return read_template(ROOT, relative_path)


class AnalyticsDecisionWorkspaceContractTest(SimpleTestCase):
    def test_map_keeps_original_visual_while_distribution_uses_new_layout(self):
        map_template = "\n".join(
            (
                _read("templates/partials/analytics/regional_performance.html"),
                _read("static/css/components.css"),
            )
        )
        layout = _read("static/css/pages/analytics-dashboard.css")

        # The map is a square sheet bounded by the room under the headers
        # (owner, 2026-09-17: "The map should be square much as it will fill
        # the desktop page"). The STYLESHEET sizes it — that is what this
        # assertion is really for — so the viewport still carries no sizing
        # utility of its own, aspect-square included.
        self.assertIn('class="sr-map-viewport relative w-full"', map_template)
        self.assertNotIn("aspect-square", map_template)
        # The sheet is full-width since 2026-09-20 and no longer square; its
        # height is 600px where the window has the room and the room under
        # the chrome where it has less, so the whole map stays on screen. The
        # stylesheet still sizes it and the script still never measures.
        self.assertIn("inline-size: 100% !important;", layout)
        self.assertIn(
            "height: min(600px, calc(100svh - var(--sr-map-chrome))) !important;",
            layout,
        )
        self.assertIn("aspect-ratio: auto !important;", layout)
        self.assertNotIn("--map-viewport-height", layout)
        self.assertNotIn("sr-map-stage", map_template)
        self.assertNotIn("sr-subregion-zoomed", map_template)
        self.assertNotIn("#sr-cam:not(.sr-zoomed) .sr-labels", map_template)
        self.assertNotIn("#sr-cam:not(.sr-zoomed) .sr-school-pins", map_template)
        self.assertNotIn("max-block-size: 350px", layout)
        # The distribution table sits below the map at every width (owner,
        # 2026-09-14), so the layout never turns into a row on desktop.
        self.assertIn("sr-map-layout flex flex-col", map_template)
        self.assertNotIn("xl:flex-row", map_template)
        self.assertNotIn("xl:w-[286px]", map_template)
        self.assertIn("sr-map-viewport", map_template)
        self.assertIn("sr-distribution-panel", map_template)
        # Every column shows on a phone and the table scrolls in its region
        # (owner's mobile directive, 2026-09-27: "Do not hide table columns").
        self.assertIn('data-mobile-table="scroll"', map_template)
        self.assertNotIn('data-mobile-table="fit"', map_template)
        self.assertIn("sr-distribution-col--name", map_template)
        self.assertIn("@media (max-width: 64rem)", layout)
        self.assertNotIn("min-inline-size: 34rem", layout)
        self.assertIn("overflow-x: clip", layout)
        self.assertIn("table-layout: fixed", layout)
        # The distribution block starts on the key's and title band's edge
        # (owner, 2026-09-27): no side padding of its own, and flush from the
        # platform's nested-card inset its "-panel" class name would get.
        self.assertIn("padding: 1rem 0 0", layout)
        self.assertIn(
            '<div class="sr-distribution-panel w-full" data-edify-padding="flush">',
            map_template,
        )
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

    def test_the_section_nav_shows_named_workspace_areas(self):
        partial = _read("templates/partials/_section_nav.html")

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

    def test_a_bare_htmx_request_gets_a_fragment_not_a_page(self):
        """HX-Request without HX-Target asked for a fragment: the renderer
        answers with the scope, never the shell with a <head>."""

        source = _read("apps/frontend/views/analytics_render.py")
        self.assertIn(
            'if request.headers.get("HX-Request") == "true" and not target:', source
        )
        self.assertIn("return render(request, SCOPE_TEMPLATE, context)", source)

    def test_the_three_tools_render_through_the_one_shell(self):
        """Reports, the Decision Log and Closure Quality, the pages that kept
        sidebar entries when the Analytics entry was retired (owner,
        2026-10-19), share one shell: render_analytics_section draws the
        header and the decision frame around each panel."""

        import inspect

        from django.urls import resolve

        for url in ("/reports", "/decision-log", "/analytics/closure-quality"):
            with self.subTest(url=url):
                view = inspect.unwrap(resolve(url).func)
                self.assertIn(
                    "render_analytics_section(",
                    inspect.getsource(view),
                    f"{url} does not render through the shell",
                )

    def test_every_analytics_route_uses_the_enterprise_anatomy(self):
        templates = (
            "templates/pages/analytics/workspace.html",
            "templates/pages/audit/decision_log.html",
            "templates/pages/reports/index.html",
            "templates/pages/projects/analytics.html",
            "templates/pages/ia/analytics_dashboard.html",
        )
        for template in templates:
            source = _read(template)
            if template.endswith("analytics/workspace.html"):
                source += _read("templates/partials/analytics/scope.html")
                source += _read("templates/partials/analytics/panel.html")
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
        # Disclosures start closed and one is open at a time (owner,
        # 2026-09-25): no remembered state reopens them on load.
        self.assertNotIn("localStorage", script)
        self.assertIn("other.open = false", script)
        self.assertIn("edify:analytics-interaction", script)
        self.assertIn('aria-label="Decision and data context"', decision_frame)

    def test_role_dashboards_prioritize_actions_and_disclose_evidence(self):
        # The Programme Lead and Country Director cockpits left with the
        # Analytics entry (owner, 2026-10-19).
        ia = _read("templates/partials/ia/dashboard_body.html")
        reports = _read("templates/partials/analytics/panels/reports.html")

        self.assertEqual(ia.count("data-analytics-disclosure"), 3)
        # One disclosure since the period matrix moved to the target pages.
        self.assertEqual(reports.count("data-analytics-disclosure"), 1)
