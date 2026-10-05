"""Plans already made follow the Cost Catalogue (owner, 2026-10-05).

"I still see the old cost being fetched like even when the cost is changed or
deleted, it still fetches."

Saving a rate published a new version of the catalogue and left every plan
already scheduled on the old rate, so the weekly request went on fetching the
old cost. What is pinned here: a saved rate re-prices the open plans priced
with it and nothing else, work already carried out keeps the cost it was
priced at, and the person who saved the rate is told what it did.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.test_activity_editing import EditingFixture
from apps.activities.test_profile_activities import PASSWORD
from apps.budget import repricing
from apps.budget import services as budget_services
from apps.budget.costing_service import active_catalogue
from apps.budget.models import CostSetting


class RepricingFixture(EditingFixture):
    def setUp(self):
        super().setUp()
        self.director = User.objects.create_user(
            email="reprice-cd@edify.org",
            name="Reprice Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password=PASSWORD,
            is_active=True,
        )
        self.visit = self._visit(self.fresh)

    def _lines(self, activity):
        return list(
            ActivityScheduleCostLine.objects.filter(activity=activity).order_by("id")
        )

    def _a_rate_the_visit_uses(self) -> CostSetting:
        keys = [line.cost_setting_key.split("#")[0] for line in self._lines(self.visit)]
        self.assertTrue(keys, "the fixture's visit has cost lines")
        return CostSetting.objects.get(catalogue=active_catalogue(), key=keys[0])

    def _save_rate(self, setting, unit_cost):
        with self.captureOnCommitCallbacks(execute=True):
            return budget_services.upsert_cost_setting(
                {
                    "key": setting.key,
                    "label": setting.label,
                    "unitCost": unit_cost,
                    "reason": "Fuel went up",
                },
                self.director,
            )


class ASavedRateReachesThePlansAlreadyMade(RepricingFixture):
    def test_an_open_plan_priced_with_it_is_re_priced(self):
        rate = self._a_rate_the_visit_uses()
        before = self.visit.est_cost_cents
        old_catalogue = active_catalogue().id

        saved = self._save_rate(rate, rate.unit_cost + 6000)

        self.assertIn(self.visit.id, saved["repricing"]["repriced"])
        self.visit.refresh_from_db()
        self.assertGreater(self.visit.est_cost_cents, before)
        new_catalogue = active_catalogue().id
        self.assertNotEqual(new_catalogue, old_catalogue)
        self.assertEqual(
            {line.catalogue_id for line in self._lines(self.visit)}, {new_catalogue}
        )
        # Nothing is left behind the catalogue.
        self.assertEqual(repricing.stale_plan_ids(), [])

    def test_a_rate_the_plan_does_not_use_leaves_it_alone(self):
        used = {line.cost_setting_key.split("#")[0] for line in self._lines(self.visit)}
        other = (
            CostSetting.objects.filter(catalogue=active_catalogue())
            .exclude(key__in=used)
            .filter(key__in=budget_services.CANONICAL_RATE_KEYS)
            .first()
        )
        self.assertIsNotNone(other)
        before = self.visit.est_cost_cents
        priced_with = {line.catalogue_id for line in self._lines(self.visit)}

        saved = self._save_rate(other, other.unit_cost + 500)

        self.assertNotIn(self.visit.id, saved["repricing"]["repriced"])
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.est_cost_cents, before)
        self.assertEqual(
            {line.catalogue_id for line in self._lines(self.visit)}, priced_with
        )

    def test_work_already_carried_out_keeps_the_cost_it_was_priced_at(self):
        rate = self._a_rate_the_visit_uses()
        Activity.objects.filter(id=self.visit.id).update(status="completed")
        before = [
            (line.cost_setting_key, line.amount) for line in self._lines(self.visit)
        ]

        saved = self._save_rate(rate, rate.unit_cost + 6000)

        self.assertNotIn(self.visit.id, saved["repricing"]["repriced"])
        self.assertEqual(
            [(line.cost_setting_key, line.amount) for line in self._lines(self.visit)],
            before,
        )

    def test_a_plan_money_has_moved_on_is_not_looked_at(self):
        rate = self._a_rate_the_visit_uses()
        Activity.objects.filter(id=self.visit.id).update(payment_status="paid")

        self._save_rate(rate, rate.unit_cost + 6000)

        self.assertNotIn(self.visit.id, repricing.stale_plan_ids())

    def test_the_sweep_finds_a_plan_a_save_did_not_reach(self):
        """The scheduled job and the command re-price what is left."""
        rate = self._a_rate_the_visit_uses()
        from unittest.mock import patch

        nothing = {"repriced": [], "kept": [], "left": []}
        with patch(
            "apps.budget.repricing.reprice_after_catalogue_change",
            return_value=nothing,
        ):
            self._save_rate(rate, rate.unit_cost + 6000)
        self.assertIn(self.visit.id, repricing.stale_plan_ids())

        with self.captureOnCommitCallbacks(execute=True):
            result = repricing.reprice_stale_plans()

        self.assertIn(self.visit.id, result["repriced"])
        self.assertEqual(repricing.stale_plan_ids(), [])

    def test_a_deadline_already_passed_leaves_the_plan_for_the_next_run(self):
        result = repricing.reprice_stale_plans([self.visit.id], deadline=0.0)

        self.assertEqual(result["left"], [self.visit.id])
        self.assertEqual(result["repriced"], [])


class WhatTheDirectorIsTold(SimpleTestCase):
    def test_each_outcome_is_said(self):
        self.assertEqual(
            repricing.summary({"repriced": [], "kept": [], "left": []}),
            "No planned activity was priced with it.",
        )
        told = repricing.summary({"repriced": ["a", "b"], "kept": ["c"], "left": ["d"]})
        self.assertIn("2 planned activities re-priced at the new cost", told)
        self.assertIn("1 more will be re-priced in the next few minutes", told)
        self.assertIn("1 kept at the cost already approved", told)

    def test_the_sweep_is_a_registered_job(self):
        from apps.realtime.registry import JOB_REGISTRY

        self.assertIn("cost_reprice_sweep", {spec.name for spec in JOB_REGISTRY})
