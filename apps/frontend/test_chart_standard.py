from django.test import SimpleTestCase
from django.template.loader import render_to_string
from apps.frontend.templatetags.chart_tags import comparison_chart, summary_chart


class ChartPayloadTests(SimpleTestCase):
    def test_comparison_preserves_missing_measurements_and_zero(self):
        result = comparison_chart([
            {"name": "A", "actual": 0, "target": 5},
            {"name": "B", "actual": None, "target": 3},
        ], "name", "actual", "target", "Visits", "Scheduled", "Target")
        self.assertEqual(result["chart_payload"]["series"][0]["data"], [0, None])
        self.assertEqual(result["chart_payload"]["series"][1]["data"], [5, 3])

    def test_summary_does_not_invent_missing_data(self):
        result = summary_chart({"planned": 0}, "planned,completed", "Planned,Completed", "Delivery")
        self.assertEqual(result["chart_payload"]["series"][0]["data"], [0, None])

    def test_chart_payload_escapes_school_names(self):
        context = comparison_chart([{"name": "</script><script>alert(1)</script>", "a": 1, "b": 2}], "name", "a", "b", "Visits", "Planned", "Done")
        html = render_to_string("components/bar_chart.html", context)
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn(r"\u003C/script\u003E", html)
