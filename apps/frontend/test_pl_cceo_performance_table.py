"""Regression contracts for the Program Lead CCEO performance table."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)
TEMPLATE = ROOT / "templates/partials/dashboards/pl/cceo_performance.html"
STYLES = ROOT / "static/css/pages.css"


class ProgramLeadCCEOPerformanceTableTest(SimpleTestCase):
    def setUp(self):
        self.template = TEMPLATE.read_text(encoding="utf-8")
        self.styles = STYLES.read_text(encoding="utf-8")

    def test_table_uses_seven_readable_decision_columns(self):
        for heading in (
            "CCEO and region",
            "Schools",
            "Delivery",
            "Exceptions",
            "Route quality",
            "Risk",
            "Action",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f">{heading}</th>", self.template)

        self.assertEqual(self.template.count('scope="col"'), 7)
        self.assertIn('scope="row"', self.template)
        self.assertIn('colspan="7"', self.template)
        for abbreviation in (">Sch<", ">Pln<", ">SF<", ">Bklg<"):
            with self.subTest(abbreviation=abbreviation):
                self.assertNotIn(abbreviation, self.template)

    def test_table_explains_the_order_and_keeps_related_data_together(self):
        self.assertIn("<caption", self.template)
        self.assertIn("ordered by highest operational risk", self.template)
        self.assertIn("{{ c.name }}", self.template)
        self.assertIn("{{ c.region }}", self.template)
        self.assertIn("{{ c.verified }}", self.template)
        self.assertIn("of {{ c.planned }}", self.template)
        self.assertIn("{{ c.verified_pct }}% verified", self.template)
        self.assertIn("SF pending", self.template)
        self.assertIn("backlog", self.template)

    def test_row_action_is_a_named_native_button(self):
        self.assertIn('<button type="button"', self.template)
        self.assertIn(
            'aria-label="View performance details for {{ c.name }}"', self.template
        )
        self.assertIn('hx-target="#drawer-container"', self.template)
        self.assertNotIn('tabindex="0"', self.template)

        row_opening = self.template.split("{% for c in cceo_performance.rows %}", 1)[
            1
        ].split(">", 1)[0]
        self.assertNotIn("hx-get", row_opening)
        self.assertNotIn("style=", self.template)

    def test_layout_is_semantic_scrollable_and_touch_safe(self):
        self.assertIn('data-mobile-table="scroll"', self.template)
        self.assertIn(".pl-cceo-performance-scroll {", self.styles)
        self.assertIn("overflow-x: auto", self.styles)
        self.assertIn("scrollbar-gutter: stable", self.styles)
        self.assertIn("overscroll-behavior-inline: contain", self.styles)
        self.assertIn("min-inline-size: 58rem", self.styles)
        self.assertIn("min-block-size: 2.75rem", self.styles)
        self.assertIn(".pl-cceo-performance-table__action:focus-visible", self.styles)

    def test_statuses_use_governed_semantic_tokens(self):
        for token in (
            "--edify-success-light",
            "--edify-success-text",
            "--edify-warning-light",
            "--edify-warning-text",
            "--edify-danger-light",
            "--edify-danger-text",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.styles)

        for visible_label in (
            "{{ c.route_quality }}",
            "{{ c.risk }}",
            "SF pending",
            "backlog",
        ):
            with self.subTest(visible_label=visible_label):
                self.assertIn(visible_label, self.template)
