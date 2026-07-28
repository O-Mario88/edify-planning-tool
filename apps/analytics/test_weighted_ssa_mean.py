"""The n-weighted SSA mean, computed once and on the server.

The regional map template computed this in JavaScript for boundaries spanning
several districts, duplicating arithmetic `_group` already performs. Section 40
permits no authoritative business analytic in JavaScript; two implementations
of a weighted mean is one more than can be kept honest.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.analytics.subregion_analytics import (
    combine_district_rows,
    weighted_ssa_mean,
)


class WeightedMeanTests(SimpleTestCase):
    def test_a_large_sample_outweighs_a_small_one(self):
        """The whole point: 3 assessments must not move a region like 200."""
        rows = [
            {"ssa_avg": 2.0, "ssa_n": 3},
            {"ssa_avg": 8.0, "ssa_n": 200},
        ]
        result = weighted_ssa_mean(rows)
        self.assertAlmostEqual(result, 7.91, places=2)
        # A plain mean of means would have said 5.0.
        self.assertNotAlmostEqual(result, 5.0, places=1)

    def test_nothing_assessed_is_absent_not_zero(self):
        for rows in (
            [],
            [{"ssa_avg": None, "ssa_n": 0}],
            [{"ssa_avg": 7.0, "ssa_n": 0}],
        ):
            with self.subTest(rows=rows):
                self.assertIsNone(weighted_ssa_mean(rows))

    def test_a_district_with_no_assessment_does_not_drag_the_mean_down(self):
        rows = [
            {"ssa_avg": 8.0, "ssa_n": 10},
            {"ssa_avg": None, "ssa_n": 0},
        ]
        self.assertEqual(weighted_ssa_mean(rows), 8.0)

    def test_a_single_district_returns_its_own_mean(self):
        self.assertEqual(weighted_ssa_mean([{"ssa_avg": 6.35, "ssa_n": 12}]), 6.35)


class CombineDistrictRowsTests(SimpleTestCase):
    def _row(self, **overrides):
        row = {
            "key": "district-a",
            "schools": 10,
            "clusters": 2,
            "core_schools": 1,
            "ssa_done": 8,
            "ssa_total": 10,
            "ssa_n": 8,
            "ssa_avg": 7.0,
            "ssa_avg_cluster": 6.0,
            "ssa_avg_core": 8.0,
            "trained": 4,
            "visited": 6,
            "teachers_trained": 40,
            "leaders_trained": 5,
        }
        row.update(overrides)
        return row

    def test_counts_add(self):
        combined = combine_district_rows([self._row(), self._row(key="district-b")])
        self.assertEqual(combined["schools"], 20)
        self.assertEqual(combined["ssa_n"], 16)
        self.assertEqual(combined["teachers_trained"], 80)

    def test_the_average_is_reweighted_not_re_averaged(self):
        combined = combine_district_rows(
            [
                self._row(ssa_avg=2.0, ssa_n=3),
                self._row(key="b", ssa_avg=8.0, ssa_n=200),
            ]
        )
        self.assertAlmostEqual(combined["ssa_avg"], 7.91, places=2)

    def test_cohort_averages_are_kept_for_a_single_district(self):
        combined = combine_district_rows([self._row()])
        self.assertEqual(combined["ssa_avg_cluster"], 6.0)
        self.assertEqual(combined["ssa_avg_core"], 8.0)

    def test_cohort_averages_are_dropped_rather_than_invented(self):
        """They ship no independent sample size, so combining them would mean
        inventing a weighting."""
        combined = combine_district_rows([self._row(), self._row(key="b")])
        self.assertIsNone(combined["ssa_avg_cluster"])
        self.assertIsNone(combined["ssa_avg_core"])

    def test_an_empty_boundary_is_absent_not_zero(self):
        combined = combine_district_rows([])
        self.assertIsNone(combined["ssa_avg"])
        self.assertEqual(combined["schools"], 0)

    def test_the_matched_keys_travel_with_the_result(self):
        combined = combine_district_rows([self._row(), self._row(key="district-b")])
        self.assertEqual(combined["matched_keys"], ["district-a", "district-b"])


class ServerAndClientAgreeTests(SimpleTestCase):
    """The server helper must reproduce what the template used to compute.

    Pinned because the JavaScript is being retired in favour of this: if the
    two ever disagreed, the map would have been telling a different story from
    every other surface reading the same districts.
    """

    def test_it_matches_the_javascript_formula_on_a_worked_example(self):
        rows = [
            {"ssa_avg": 6.4, "ssa_n": 25},
            {"ssa_avg": 7.1, "ssa_n": 40},
            {"ssa_avg": 5.9, "ssa_n": 15},
        ]
        # (6.4*25 + 7.1*40 + 5.9*15) / 80 = 532.5 / 80 = 6.65625 -> 6.66
        self.assertEqual(weighted_ssa_mean(rows), 6.66)
