"""Semantic metric tones must not recreate visual KPI tiles."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _strip_rules(context: str) -> str:
    """The strip's own rules: the context-metrics contract without the phone
    grid block. A phone lays every fact out in a grid of compact rows (owner's
    mobile directive, 2026-09-27: no KPI carousel on a phone); from a tablet
    up the strip stays one continuous, scrolling row."""
    start = context.index("/* Phones: every KPI on screen")
    end = context.index("/* end of the phone KPI grid */")
    return context[:start] + context[end:]


class ContextMetricToneContractTest(SimpleTestCase):
    def test_metric_tones_do_not_create_per_fact_visual_variants(self):
        template = (ROOT / "templates/components/context_metrics.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("item.variant }}", template)
        self.assertIn('data-tone="{{ item.tone }}"', template)
        self.assertNotIn("kpi_icon.html", template)

    def test_context_contract_contains_no_gradient_or_tile_grid(self):
        css = (ROOT / "static/css/components.css").read_text(encoding="utf-8")
        context = css[css.index("CONTEXT METRICS") :]

        self.assertNotIn("linear-gradient", context)
        self.assertNotIn("grid-template-columns", _strip_rules(context))
        self.assertIn("box-shadow", context)
        self.assertIn("scroll-snap-type: x ", context)
