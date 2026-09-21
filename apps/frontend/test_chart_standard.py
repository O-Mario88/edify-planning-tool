from django.test import SimpleTestCase
from django.template.loader import render_to_string
from apps.frontend.templatetags.chart_tags import (
    comparison_chart,
    summary_chart,
    team_chart,
)


class ChartPayloadTests(SimpleTestCase):
    def test_comparison_preserves_missing_measurements_and_zero(self):
        result = comparison_chart(
            [
                {"name": "A", "actual": 0, "target": 5},
                {"name": "B", "actual": None, "target": 3},
            ],
            "name",
            "actual",
            "target",
            "Visits",
            "Scheduled",
            "Target",
        )
        self.assertEqual(result["chart_payload"]["series"][0]["data"], [0, None])
        self.assertEqual(result["chart_payload"]["series"][1]["data"], [5, 3])

    def test_summary_does_not_invent_missing_data(self):
        result = summary_chart(
            {"planned": 0}, "planned,completed", "Planned,Completed", "Delivery"
        )
        self.assertEqual(result["chart_payload"]["series"][0]["data"], [0, None])

    def test_chart_payload_escapes_school_names(self):
        context = comparison_chart(
            [{"name": "</script><script>alert(1)</script>", "a": 1, "b": 2}],
            "name",
            "a",
            "b",
            "Visits",
            "Planned",
            "Done",
        )
        html = render_to_string("components/bar_chart.html", context)
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn(r"</script>", html)

    def test_team_chart_reads_each_person_as_a_series_in_row_order(self):
        """The lead first, then the officers: the series order is the colour
        order, so a person wears the same hue on every chart of the page."""
        rows = [
            {"name": "Mary A. (you)", "planned": 4, "done": 2},
            {"name": "Deo M.", "planned": 13, "done": None},
            {"name": "Ruth N.", "planned": 0, "done": 0},
        ]
        result = team_chart(
            rows, "name", "planned, done", "Planned, Completed", "Progress", "By person"
        )
        payload = result["chart_payload"]
        self.assertEqual(
            [s["name"] for s in payload["series"]],
            ["Mary A. (you)", "Deo M.", "Ruth N."],
        )
        self.assertEqual(payload["series"][0]["data"], [4, 2])
        self.assertEqual(payload["series"][1]["data"], [13, None])
        self.assertEqual(payload["series"][2]["data"], [0, 0])
        self.assertEqual(payload["xaxis"]["categories"], ["Planned", "Completed"])
        self.assertEqual(result["subtitle"], "By person")

    def test_team_chart_with_nobody_renders_an_empty_series_list(self):
        payload = team_chart([], "name", "planned", "Planned", "Progress")[
            "chart_payload"
        ]
        self.assertEqual(payload["series"], [])

    def test_the_card_carries_title_and_subtitle_outside_the_plot(self):
        html = render_to_string(
            "components/bar_chart.html",
            team_chart(
                [{"name": "Deo M.", "planned": 1}],
                "name",
                "planned",
                "Planned",
                "Progress",
                "Whole team, this year",
            ),
        )
        self.assertIn('class="edify-data-chart__title">Progress<', html)
        self.assertIn('class="edify-data-chart__subtitle">Whole team, this year<', html)
        self.assertIn("EdifyChartSystem.renderDetached(", html)
