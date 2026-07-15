"""weighted_period_pct — the single canonical weighted-% formula (targets_analytics
audit punch-list item: My Targets / Team Targets per-member / Team Targets
team-wide rollup must all reduce to ONE formula, not three copies that can
silently drift apart).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.test import SimpleTestCase

from apps.targets.my_targets import weighted_period_pct


@dataclass
class _Area:
    key: str
    weight: int


class WeightedPeriodPctTest(SimpleTestCase):
    def setUp(self):
        # Mirrors the real TargetArea weights (visits 30, meetings 20,
        # trainings 20, ssa 20, mscs 10 — sums to 100).
        self.areas = [
            _Area("school_visits", 30),
            _Area("cluster_meetings", 20),
            _Area("cluster_trainings", 20),
            _Area("ssa_completed", 20),
            _Area("mscs", 10),
        ]

    def _series(self, **month1):
        """Build a 12-month {area_key: [12 ints]} series with values only in
        month index 0 (month_of_fy=1)."""
        out = {a.key: [0] * 12 for a in self.areas}
        for k, v in month1.items():
            out[k][0] = v
        return out

    def test_weighted_average_matches_hand_calculation(self):
        targets = self._series(school_visits=10, cluster_meetings=5, ssa_completed=4)
        achieved = self._series(school_visits=5, cluster_meetings=5, ssa_completed=2)
        # visits: 5/10=50% * w30 = 1500; meetings: 5/5=100% * w20 = 2000;
        # ssa: 2/4=50% * w20 = 1000; trainings/mscs have no target → excluded.
        # wsum = 30+20+20 = 70; psum = 4500 → 4500/70 = 64.28... → 64
        pct, ach, tgt = weighted_period_pct(self.areas, targets, achieved, [1])
        self.assertEqual(pct, 64)
        self.assertEqual(ach, 12)
        self.assertEqual(tgt, 19)

    def test_areas_with_no_target_are_excluded_not_zeroed(self):
        targets = self._series(school_visits=10)
        achieved = self._series(school_visits=10)
        # Only school_visits has a target and it's 100% — the untargeted
        # areas must not drag the weighted average down.
        pct, ach, tgt = weighted_period_pct(self.areas, targets, achieved, [1])
        self.assertEqual(pct, 100)

    def test_no_targets_assigned_returns_zero_by_default(self):
        targets = self._series()
        achieved = self._series()
        pct, ach, tgt = weighted_period_pct(self.areas, targets, achieved, [1])
        self.assertEqual((pct, ach, tgt), (0, 0, 0))

    def test_no_targets_assigned_returns_none_when_requested(self):
        targets = self._series()
        achieved = self._series()
        pct, ach, tgt = weighted_period_pct(
            self.areas, targets, achieved, [1], none_if_unassigned=True
        )
        self.assertIsNone(pct)

    def test_my_targets_and_team_targets_share_the_same_function_object(self):
        """Regression guard: Team Targets (per-member wpct + team-wide
        team_wpct) must call this exact function rather than re-deriving the
        formula — that reimplementation is what let the three call sites
        drift into disagreeing 'team target %' numbers in the audit finding.
        """
        import apps.targets.my_targets as my_targets_mod
        import apps.targets.team_targets as team_targets_mod

        self.assertIs(
            team_targets_mod.weighted_period_pct, my_targets_mod.weighted_period_pct
        )
