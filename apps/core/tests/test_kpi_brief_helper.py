"""The line under a KPI is a second figure, or nothing (owner, 2026-10-07).

"KPI strip has a lot of explanation can you minimize the explanations so the
focus is on the actual KPI, i noticed the explanations are already somewhere
else."

Every tile carried a sentence under its figure: 438 different ones across the
platform when this was written, 344 of them prose. A tile is now its name and
its figure; the line under it stays when it is a second figure about the
first, cut to that figure. The sentence is kept whole for the hover text and
for a screen reader, so nothing a tile said is lost.
"""

from __future__ import annotations

from django.template import Context, Template
from django.test import SimpleTestCase

from apps.core.metrics.payload import HELPER_FIGURE_CHARS, brief_helper
from apps.core.templatetags.kpi_metrics import professional_kpis


class BriefHelperTest(SimpleTestCase):
    def test_a_sentence_that_explains_the_metric_is_not_drawn(self):
        for prose in (
            "deduplicated across tabs and devices",
            "No cost until a partner schedules",
            "Scheduled work only",
            "Verified and awaiting payment",
            "expected, but did not sign in",
            "Average SSA: None",
            "IA-verified, FY2026 → FY2027",
            "Across 8 planned activities",
            "",
            None,
        ):
            with self.subTest(helper=prose):
                self.assertEqual(brief_helper(prose), "")

    def test_a_second_figure_is_kept_as_it_is(self):
        for figure in (
            "of 700 schools",
            "33% of expected",
            "0 in progress",
            "4 no login",
            "1 request",
            "0 teachers · 0 leaders",
            "0 of 8 due",
            "UGX 40,000 pending",
        ):
            with self.subTest(helper=figure):
                self.assertEqual(brief_helper(figure), figure)

    def test_a_long_line_is_cut_to_its_first_figure(self):
        self.assertEqual(
            brief_helper("of 280 a year · 0 Core, 1 Client"), "of 280 a year"
        )
        self.assertEqual(
            brief_helper("of 5 planned · 0 held, in review"), "of 5 planned"
        )
        self.assertEqual(
            brief_helper(
                "1 of 302 schools the Partner should hold (102 Core, 200 beyond "
                "staff capacity) · 301 still to assign · 1 awaiting a date"
            ),
            "1 of 302 schools",
        )
        self.assertEqual(
            brief_helper("of 6 listed have a working day in the period"), "of 6 listed"
        )

    def test_what_is_drawn_is_never_longer_than_a_short_figure(self):
        for helper in (
            "4 of 560 staff visits · 556 remaining · 5 planned in all: 0 core, 5 client",
            "1 dated · 1 awaiting a date · 1 of 302 schools the Partner should hold",
            "146 open and unacknowledged",
        ):
            with self.subTest(helper=helper):
                self.assertLessEqual(len(brief_helper(helper)), HELPER_FIGURE_CHARS)
                self.assertTrue(brief_helper(helper))


class TheStripTest(SimpleTestCase):
    def render(self, items):
        template = Template(
            '{% include "components/context_metrics.html" with items=items %}'
        )
        return template.render(Context({"items": items}))

    def test_the_sentence_moves_to_the_hover_text_and_the_screen_reader(self):
        (item,) = professional_kpis(
            [
                {
                    "label": "Total Active Time",
                    "value": "1h 50m",
                    "helper": "deduplicated across tabs and devices",
                }
            ]
        )

        self.assertEqual(item["helper"], "")
        self.assertEqual(item["helper_note"], "deduplicated across tabs and devices")

        html = self.render(
            [
                {
                    "label": "Total Active Time",
                    "value": "1h 50m",
                    "helper": "deduplicated across tabs and devices",
                }
            ]
        )
        self.assertNotIn('class="context-metrics__helper"', html)
        self.assertIn(
            '<span class="sr-only" data-kpi-note>deduplicated across tabs and devices</span>',
            html,
        )
        self.assertIn('title="deduplicated across tabs and devices"', html)

    def test_a_figure_stays_under_the_figure(self):
        html = self.render(
            [{"label": "SSA Coverage", "value": "0%", "helper": "0 of 697 schools"}]
        )

        self.assertIn(">0 of 697 schools</span>", html)
        self.assertNotIn("data-kpi-note", html)

    def test_a_cut_line_keeps_its_whole_sentence_on_hover(self):
        whole = "of 280 a year · 0 Core, 1 Client"
        html = self.render([{"label": "Your Visits", "value": "1", "helper": whole}])

        self.assertIn(">of 280 a year</span>", html)
        self.assertIn(f'title="{whole}"', html)
        self.assertIn(f"data-kpi-note>{whole}</span>", html)

    def test_a_tile_with_no_line_is_unchanged(self):
        (item,) = professional_kpis([{"label": "Schools", "value": "697"}])

        self.assertNotIn("helper_note", item)
