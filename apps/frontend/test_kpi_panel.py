"""Contract for the system-wide compact performance strip."""

from django.test import SimpleTestCase

from .test_design_system_quality import _read


class ContextMetricsAnatomyTest(SimpleTestCase):
    def test_component_has_one_shared_semantic_list(self):
        markup = _read("templates/components/context_metrics.html")

        self.assertIn('class="context-metrics', markup)
        self.assertIn('class="context-metrics__sentence" role="list"', markup)
        self.assertIn('role="listitem"', markup)
        self.assertIn('data-component="context-metric"', markup)
        self.assertNotIn("kpi-strip__", markup)
        self.assertNotIn('data-component="kpi-card"', markup)
        self.assertNotIn("kpi_icon.html", markup)

    def test_values_and_labels_form_one_readable_fact(self):
        markup = _read("templates/components/context_metrics.html")

        self.assertIn("context-metrics__value", markup)
        self.assertIn("context-metrics__label", markup)
        self.assertIn("{% firstof item.label item.canonical_label %}", markup)
        self.assertIn("item.accessible_description", markup)

    def test_links_and_drawers_remain_available_without_card_chrome(self):
        markup = _read("templates/components/context_metrics.html")

        self.assertIn("item.hx_get", markup)
        self.assertIn('hx-target="#drawer-container"', markup)
        self.assertIn("item.drilldown_url", markup)
        self.assertIn("item.link", markup)
        self.assertIn('class="context-metrics__link"', markup)

    def test_css_uses_one_continuous_surface_without_tile_grids(self):
        css = _read("static/css/components.css")
        contract = css[css.index("CONTEXT METRICS") :]

        self.assertIn("display: flex;", contract)
        self.assertIn("scroll-snap-type: x mandatory;", contract)
        self.assertIn("font-variant-numeric: tabular-nums;", contract)
        for forbidden in (
            "background-image:",
            "border-inline-start:",
            "border-block-start:",
            "grid-template-columns:",
        ):
            self.assertNotIn(forbidden, contract)

    def test_mobile_summary_scrolls_with_two_visible_metrics(self):
        css = _read("static/css/components.css")
        contract = css[css.index("CONTEXT METRICS") :]

        self.assertIn("@container performance (max-width: 599px)", contract)
        self.assertIn("flex-direction: column;", contract)
        self.assertIn("overflow-x: auto", contract)
        self.assertIn("scroll-snap", contract)

    def test_legacy_entry_point_can_only_forward_to_the_new_pattern(self):
        legacy = _read("templates/components/kpi_strip.html")

        self.assertIn("components/context_metrics.html", legacy)
        self.assertNotIn("kpi-strip__", legacy)
        self.assertNotIn('data-component="kpi-card"', legacy)


class CoordinatorMetricPlacementTest(SimpleTestCase):
    def test_delivery_home_has_shared_summary_strip(self):
        page = _read("templates/pages/dashboards/special_projects.html")

        self.assertIn("{% kpi_strip %}", page)
        self.assertNotIn("Delivery pulse", page)
        self.assertIn("active_project_count", page)
        self.assertIn("activities_in_plan", page)

    def test_coordinator_metrics_live_with_their_decisions(self):
        operations = _read(
            "templates/partials/dashboards/special_projects/operations.html"
        )

        self.assertIn("evidence_pending", operations)
        self.assertIn("activities_in_plan", operations)
        self.assertIn("active_project_count", operations)
        self.assertIn("Projects to watch", operations)
