"""One donut implementation, everywhere.

The platform used to draw rings by hand: a `stroke-dasharray` on a path in
whichever template needed one, each with its own radius, stroke width, cap and
centre type. They disagreed with each other, and none of them clamped, so a
value over its denominator wrapped past twelve o'clock and read as progress it
did not have.

This pins the outcome of consolidating them: the geometry lives in
`apps.core.donut`, the markup lives in one partial, and no template hand-rolls
a ring again.
"""

from __future__ import annotations

from pathlib import Path

from django.test import TestCase

from apps.core.donut import GAUGE_SIZE, build_gauge, build_rings

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "templates"
COMPONENT = TEMPLATES / "partials" / "components" / "donut_rings.html"


class NoHandRolledRingsTest(TestCase):
    def test_only_the_shared_component_draws_an_arc(self):
        offenders = [
            path.relative_to(TEMPLATES).as_posix()
            for path in TEMPLATES.rglob("*.html")
            if path != COMPONENT
            and "<circle" in path.read_text()
            and "stroke-dasharray" in path.read_text()
        ]
        self.assertEqual(
            offenders,
            [],
            "these templates draw their own ring instead of including "
            "partials/components/donut_rings.html",
        )


class GaugeGeometryTest(TestCase):
    """A gauge is the same component at list scale — and the same honesty."""

    def test_a_gauge_is_a_single_ring(self):
        gauge = build_gauge(64, label="Data quality", color="var(--edify-success)")
        self.assertEqual(len(gauge["rings"]), 1)
        self.assertEqual(gauge["size"], GAUGE_SIZE)

    def test_a_gauge_reads_its_value_as_a_percentage_by_default(self):
        gauge = build_gauge(25, label="Q", color="red")
        self.assertEqual(gauge["rings"][0].percent, 25.0)

    def test_zero_draws_no_arc(self):
        """A rounded cap at twelve o'clock is a sliver of progress that is not
        there, and zero is exactly when that lie matters."""
        gauge = build_gauge(0, label="Q", color="red")
        self.assertFalse(gauge["rings"][0].has_arc)

    def test_a_value_over_its_denominator_clamps(self):
        gauge = build_gauge(140, label="Q", color="red")
        self.assertEqual(gauge["rings"][0].percent, 100.0)

    def test_a_negative_value_never_draws_backwards(self):
        gauge = build_gauge(-10, label="Q", color="red")
        self.assertEqual(gauge["rings"][0].percent, 0.0)
        self.assertFalse(gauge["rings"][0].has_arc)

    def test_an_empty_series_draws_nothing_rather_than_a_full_circle(self):
        self.assertEqual(build_rings([])["rings"], [])
