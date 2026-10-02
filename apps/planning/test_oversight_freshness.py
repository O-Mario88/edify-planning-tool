"""Country Planning Oversight follows the plan as it is written (owner audit,
2026-10-01): a snapshot older than the last change to the records it reads is
rebuilt on the next read, at most once per settle time — rather than staying
on the page until the cache lets go of it."""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from apps.planning.country_oversight import freshness
from apps.planning.country_oversight import service as svc
from apps.planning.test_country_planning_oversight import FY, World


@override_settings(DASHBOARD_CACHE_SECONDS=300)
class FreshnessTest(World):
    def setUp(self):
        cache.clear()
        svc._HELD.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(svc._HELD.clear)

    def country(self):
        return svc.snapshot_for(self.cd_user, svc.Filters(fy=FY)).tree.country

    def test_a_new_plan_reaches_the_page_without_waiting_for_the_cache(self):
        school = self.school("client", self.cceo)
        with patch.object(freshness, "SETTLE_SECONDS", 0):
            self.assertEqual(self.country().p_visits, 0)
            self.activity(school, "training_follow_up_visit", owner=self.cceo)
            country = self.country()
            self.assertEqual((country.p_visits, country.any_visit), (1, 1))
            # The school list a drawer opens reads the same fresh facts.
            dataset = svc.dataset_for(self.cd_user, svc.Filters(fy=FY).window)
            self.assertEqual(dataset.facts[school.id].staff[2], 1)

    def test_a_hand_over_and_a_roster_change_are_noticed_too(self):
        school = self.school("client", self.cceo, cluster=self.cluster)
        with patch.object(freshness, "SETTLE_SECONDS", 0):
            self.assertEqual(self.country().pa_work, 0)
            self.handover(
                school,
                self.partner,
                status="pending_scheduling",
                assigning_staff_id=self.cceo.id,
            )
            self.assertEqual(self.country().pa_work, 1)
            self.session("cluster_meeting", [school])
            self.assertEqual(self.country().meeting_covered, 1)

    def test_nothing_is_rebuilt_while_nothing_changes(self):
        self.school("client", self.cceo)
        with patch.object(freshness, "SETTLE_SECONDS", 0):
            self.assertEqual(self.country().schools, 1)
            with patch.object(
                svc, "build_dataset", side_effect=AssertionError("rebuilt")
            ):
                self.assertEqual(self.country().schools, 1)
                self.assertEqual(self.country().schools, 1)

    def test_a_morning_of_saves_does_not_rebuild_on_every_one(self):
        school = self.school("client", self.cceo)
        self.assertEqual(self.country().p_visits, 0)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        # The snapshot is seconds old: it stands until the settle time.
        with patch.object(svc, "build_dataset", side_effect=AssertionError("rebuilt")):
            self.assertEqual(self.country().p_visits, 0)

    def test_without_a_cache_the_figures_are_always_live(self):
        school = self.school("client", self.cceo)
        with override_settings(DASHBOARD_CACHE_SECONDS=0):
            self.assertEqual(self.country().p_visits, 0)
            self.activity(school, "training_follow_up_visit", owner=self.cceo)
            self.assertEqual(self.country().p_visits, 1)
            self.assertFalse(freshness.overtaken(None))
