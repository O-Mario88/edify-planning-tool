"""Concentric-ring donut geometry.

The arithmetic is here rather than in a template, so it is testable — and the
things worth pinning are the honesty guarantees, not the pixel values: an empty
dataset must not draw a full circle, a zero series must not draw a rounded cap
that reads as progress, and a ring must never reach into the space the headline
occupies.
"""

from __future__ import annotations

import math

from django.test import SimpleTestCase

from apps.core.donut import MIN_CLEAR_CENTRE, build_rings


def _series(*values):
    return [
        {"key": f"s{i}", "label": f"S{i}", "value": v, "color": "#000"}
        for i, v in enumerate(values)
    ]


class DonutGeometryTest(SimpleTestCase):
    def test_rings_are_concentric_and_ordered_outermost_first(self):
        donut = build_rings(_series(10, 8, 6), share_of=10)
        radii = [r.radius for r in donut["rings"]]
        self.assertEqual(radii, sorted(radii, reverse=True))
        self.assertEqual(len(set(radii)), 3)

    def test_the_arc_is_the_series_share_of_the_denominator(self):
        donut = build_rings(_series(50), share_of=200)
        ring = donut["rings"][0]
        self.assertEqual(ring.percent, 25.0)
        arc = float(ring.dash.split()[0])
        self.assertAlmostEqual(arc, ring.circumference * 0.25, places=1)

    def test_the_denominator_defaults_to_the_largest_series(self):
        donut = build_rings(_series(40, 10))
        self.assertEqual(donut["rings"][0].percent, 100.0)
        self.assertEqual(donut["rings"][1].percent, 25.0)

    def test_the_circumference_matches_the_radius(self):
        ring = build_rings(_series(1))["rings"][0]
        self.assertAlmostEqual(ring.circumference, 2 * math.pi * ring.radius, places=1)

    def test_value_labels_stack_with_their_own_rings(self):
        donut = build_rings(_series(10, 10, 10))
        ys = [r.label_y for r in donut["rings"]]
        # Outermost ring's label sits highest, each inner one below it.
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(len(set(ys)), 3)


class DonutHonestyTest(SimpleTestCase):
    def test_no_data_draws_no_arcs(self):
        """A zeroed dataset must not render as a completed circle."""
        donut = build_rings(_series(0, 0), share_of=0)
        self.assertTrue(donut["rings"])
        for ring in donut["rings"]:
            self.assertEqual(ring.percent, 0.0)
            self.assertFalse(ring.has_arc)

    def test_an_empty_series_list_renders_nothing(self):
        self.assertEqual(build_rings([])["rings"], [])

    def test_a_zero_series_among_real_ones_draws_no_cap(self):
        donut = build_rings(_series(10, 0), share_of=10)
        self.assertTrue(donut["rings"][0].has_arc)
        self.assertFalse(donut["rings"][1].has_arc)

    def test_a_share_over_the_denominator_is_clamped(self):
        """Otherwise the arc wraps past twelve o'clock and reads as less."""
        ring = build_rings(_series(150), share_of=100)["rings"][0]
        self.assertEqual(ring.percent, 100.0)
        self.assertLessEqual(float(ring.dash.split()[0]), ring.circumference)

    def test_negative_values_never_draw_backwards(self):
        ring = build_rings(_series(-5), share_of=100)["rings"][0]
        self.assertEqual(ring.percent, 0.0)
        self.assertFalse(ring.has_arc)


class DonutCentreClearanceTest(SimpleTestCase):
    def test_rings_never_reach_into_the_headline(self):
        donut = build_rings(_series(*([10] * 12)))
        centre = donut["centre"]
        for ring in donut["rings"]:
            inner_edge = ring.radius - donut["stroke"] / 2
            self.assertGreater(inner_edge, centre * MIN_CLEAR_CENTRE)

    def test_more_series_than_fit_are_dropped_not_crushed(self):
        """The legend still carries every series; the rings do not."""
        donut = build_rings(_series(*([10] * 40)))
        self.assertLess(len(donut["rings"]), 40)
        self.assertTrue(donut["rings"])
