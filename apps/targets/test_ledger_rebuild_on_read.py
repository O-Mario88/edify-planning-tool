"""Who rebuilds the achievement ledger on read, and who reads it as it stands.

`per_user_monthly_series` rebuilt every user's ledger before reading it, on
every page load. That is a write on the way to answering a read, and at roughly
six queries per in-scope person it was the largest single cost on the Country
Director and RVP surfaces.

The split is deliberate, and these tests are what keep it deliberate:

* A person reading their OWN credit -- My Targets, Team Targets, Staff
  Performance -- expects the activity they closed this morning to count, so
  those still rebuild.
* A country or regional roll-up reads the ledger as `target_ledger_sync` last
  left it. The job bounds staleness at thirty minutes, and
  `apps.realtime.health` reports it overdue past ninety, so a stale ledger
  becomes a failing health check rather than quietly wrong national numbers.

The last test states the cost of that trade in the open rather than leaving it
to be discovered.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.fy import get_operational_fy
from apps.targets.my_targets import per_user_monthly_series, pooled_monthly_series

REBUILD = "apps.targets.my_targets.TargetAchievementService.rebuild"


class RebuildOnReadTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.user = User.objects.create(
            id="ledger-read-user",
            email="ledger-read@edify.org",
            name="Ledger Read",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="ledger-read-staff", user=cls.user, title="CCEO")

    def test_the_default_still_rebuilds(self):
        """Every existing caller keeps the behaviour it had."""
        with patch(REBUILD) as rebuild:
            per_user_monthly_series([self.user], self.fy)
        rebuild.assert_called_once()

    def test_rebuild_false_reads_the_ledger_as_it_stands(self):
        with patch(REBUILD) as rebuild:
            per_user_monthly_series([self.user], self.fy, rebuild=False)
        rebuild.assert_not_called()

    def test_the_series_is_still_returned_without_a_rebuild(self):
        """Skipping the write must not skip the read."""
        series = per_user_monthly_series([self.user], self.fy, rebuild=False)
        self.assertIn(self.user.id, series)
        targets, achieved = series[self.user.id]
        self.assertIsInstance(targets, dict)
        self.assertIsInstance(achieved, dict)

    def test_pooled_series_passes_the_flag_through(self):
        with patch(REBUILD) as rebuild:
            pooled_monthly_series([self.user], self.fy, rebuild=False)
        rebuild.assert_not_called()

    def test_pooled_series_rebuilds_by_default(self):
        with patch(REBUILD) as rebuild:
            pooled_monthly_series([self.user], self.fy)
        rebuild.assert_called_once()


class LeadershipSurfacesSkipTheRebuildTest(TestCase):
    """CD and RVP roll-ups are the surfaces the trade was made for."""

    def test_priming_the_cd_scope_does_not_rebuild(self):
        from apps.analytics.cd_analytics_service import (
            _prime_target_series,
            resolve_cd_scope,
        )

        cd = resolve_cd_scope(get_operational_fy())
        with patch(REBUILD) as rebuild:
            _prime_target_series(cd)
        rebuild.assert_not_called()

    def test_the_cd_scope_is_still_populated(self):
        from apps.analytics.cd_analytics_service import (
            _prime_target_series,
            resolve_cd_scope,
        )

        cd = resolve_cd_scope(get_operational_fy())
        _prime_target_series(cd)
        self.assertTrue(cd.areas, "target areas must still be resolved")
        self.assertIsInstance(cd.per_user_series, dict)


class PersonalSurfacesKeepTheRebuildTest(TestCase):
    """A person reading their own number must not be shown a stale one."""

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.user = User.objects.create(
            id="ledger-personal-user",
            email="ledger-personal@edify.org",
            name="Ledger Personal",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="ledger-personal-staff", user=cls.user, title="PL"
        )

    def test_team_targets_still_rebuilds_before_reading(self):
        from apps.targets import team_targets

        source = team_targets.__file__.replace(".pyc", ".py")
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(
            "TargetAchievementService.rebuild(",
            text,
            "Team Targets shows a person their own credit and must not be "
            "switched to rebuild=False without a deliberate decision",
        )

    def test_the_scheduled_job_still_rebuilds(self):
        """Skipping on read only works because the job keeps doing the write."""
        from apps.realtime import jobs

        with open(jobs.__file__, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("TargetAchievementService.rebuild(u, fy)", text)


class StalenessCostTest(TestCase):
    """State the cost of the trade rather than leaving it to be discovered."""

    def test_a_roll_up_does_not_see_credit_the_job_has_not_recorded_yet(self):
        """New work is invisible to leadership roll-ups until the job runs.

        This is the accepted trade, not a defect: the alternative was ~54
        queries on every CD and RVP page load. `target_ledger_sync` runs every
        thirty minutes and is monitored for being overdue.
        """
        from apps.targets.models import TargetAchievementLedger

        user = User.objects.create(
            id="ledger-stale-user",
            email="ledger-stale@edify.org",
            name="Ledger Stale",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="ledger-stale-staff", user=user, title="CCEO")

        # Nothing has written a ledger row for this person yet.
        self.assertFalse(TargetAchievementLedger.objects.filter(user_id=user.id))

        with patch(REBUILD) as rebuild:
            series = per_user_monthly_series(
                [user], get_operational_fy(), rebuild=False
            )
        rebuild.assert_not_called()

        # The read still succeeds and reports no achievement -- which is the
        # truth about the ledger, and becomes the truth about the work as soon
        # as the job runs.
        _targets, achieved = series[user.id]
        self.assertTrue(all(sum(v) == 0 for v in achieved.values()))
