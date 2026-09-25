"""Map SSA figures do not depend on the order the database adds them in.

PostgreSQL's AVG adds floats in whatever order its plan visits the rows, so
the regional map's sub-county, district and sub-region means read 5.42 on one
load and 5.43 on the next at a rounding edge (2026-09-24 A+ audit: four of
2,560 sub-counties moved between two runs of the same code on the same data).
`map_score` rounds to six places before two, as `_ssa_score` does at one.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.analytics.pl_analytics_service import map_score, score_order

SCORES = [6.6, 8.4, 8.1, 7.8]


def _mean(values):
    total = 0.0
    for value in values:
        total += value
    return total / len(values)


class MapScoreTest(SimpleTestCase):
    def test_the_two_summation_orders_really_disagree(self):
        # The case that makes this test worth having: added forwards the mean
        # is 7.7250000000000005, backwards 7.725, and plain two-place rounding
        # gives 7.73 and 7.72.
        forwards, backwards = _mean(SCORES), _mean(list(reversed(SCORES)))
        self.assertNotEqual(round(forwards, 2), round(backwards, 2))

    def test_map_score_is_the_same_whichever_order_is_added(self):
        forwards, backwards = _mean(SCORES), _mean(list(reversed(SCORES)))
        self.assertEqual(map_score(forwards), map_score(backwards))
        self.assertEqual(map_score(forwards), 7.72)

    def test_map_score_keeps_the_absent_mean_absent(self):
        self.assertIsNone(map_score(None))

    def test_ranking_ignores_summation_noise(self):
        forwards, backwards = _mean(SCORES), _mean(list(reversed(SCORES)))
        self.assertEqual(score_order(forwards), score_order(backwards))

    def test_decimal_means_are_accepted(self):
        from decimal import Decimal

        self.assertEqual(map_score(Decimal("5.4250000001")), 5.42)
