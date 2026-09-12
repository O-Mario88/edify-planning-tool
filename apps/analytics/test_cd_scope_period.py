"""A selected month narrows the CD's target-progress period.

`_weighted_achievement` only knew quarters, so the headline "Country Target
Progress" stayed FY-cumulative while every other tile obeyed the month
selector. `CDScope.target_period` is what every achievement call now passes.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase

from apps.analytics.cd_analytics_service import CDAnalyticsService, CDScope


class TargetPeriodTest(TestCase):
    def test_a_month_becomes_the_matching_fy_month(self):
        # The FY starts in October: November is FY month 2, September is 12.
        self.assertEqual(CDScope(fy="2026", month=11).target_period, [2])
        self.assertEqual(CDScope(fy="2026", month=9).target_period, [12])
        self.assertEqual(CDScope(fy="2026", month=10).target_period, [1])

    def test_without_a_month_the_quarter_or_whole_year_stands(self):
        self.assertEqual(CDScope(fy="2026", quarter="Q2").target_period, "Q2")
        self.assertIsNone(CDScope(fy="2026").target_period)

    def test_the_achievement_math_measures_only_the_selected_month(self):
        captured = {}

        def fake_team_weighted_pct(user_ids, series, months, areas_for):
            captured["months"] = months
            return (50, 1, 2)

        with (
            mock.patch(
                "apps.targets.my_targets.team_weighted_pct", fake_team_weighted_pct
            ),
            mock.patch.object(
                CDAnalyticsService, "_staff_user_ids", return_value=set()
            ),
        ):
            CDAnalyticsService._weighted_achievement(
                "2026", [2], ["u1"], [], areas=["visits"], per_user_series={}
            )
        self.assertEqual(captured["months"], [2])
