"""Semantic metric tones must not recreate visual KPI tiles."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class ContextMetricToneContractTest(SimpleTestCase):
    def test_metric_tones_do_not_create_per_fact_visual_variants(self):
        template = (
            ROOT / "templates/components/context_metrics.html"
        ).read_text(encoding="utf-8")

        self.assertNotIn("item.variant }}", template)
        self.assertIn('data-tone="{{ item.tone }}"', template)
        self.assertNotIn("kpi_icon.html", template)

    def test_context_contract_contains_no_gradient_or_tile_grid(self):
        css = (ROOT / "static/css/components.css").read_text(encoding="utf-8")
        context = css[css.index("CONTEXT METRICS") :]

        self.assertNotIn("linear-gradient", context)
        self.assertNotIn("grid-template-columns", context)
        self.assertIn("box-shadow", context)
        self.assertIn("scroll-snap-type: x mandatory", context)
