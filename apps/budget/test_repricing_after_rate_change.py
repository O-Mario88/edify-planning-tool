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

from types import SimpleNamespace
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.test_activity_editing import EditingFixture
from apps.activities.test_profile_activities import PASSWORD
from apps.budget import repricing
from apps.budget import services as budget_services
from apps.budget.costing_service import active_catalogue
from apps.budget.models import CostSetting
from apps.core.exceptions import BadRequest


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


class TheSweepWorksThroughABacklog(RepricingFixture):
    """Production, 2026-10-05: the scheduler went from 58% to 90% of its
    512 MB the hour the sweep first ran, and DigitalOcean reported the app
    Degraded. Each run read every plan in the backlog to re-price the few
    dozen it had time for, and asked the writer again about every plan it had
    already been refused on."""

    def setUp(self):
        super().setUp()
        repricing.forget_refusals()
        self.addCleanup(repricing.forget_refusals)
        self.later = self._visit(self.fresh_two, days=9)

    def _refusing(self, *refused):
        def writer(activity):
            if activity.id in refused:
                raise BadRequest("This date's visits have already left draft status.")

        return patch("apps.activities.services.reprice_activity", side_effect=writer)

    def test_a_plan_past_the_deadline_is_not_read(self):
        with self.assertNumQueries(0):
            result = repricing.reprice_stale_plans([self.visit.id], deadline=0.0)

        self.assertEqual(result["left"], [self.visit.id])

    def test_the_backlog_is_read_as_far_as_the_run_gets(self):
        clock = SimpleNamespace(now=0.0, monotonic=lambda: clock.now)

        def writer(_activity):
            clock.now = 100.0

        with (
            patch.object(repricing, "time", clock),
            patch.object(repricing, "_READ_AT_A_TIME", 1),
            patch(
                "apps.activities.services.reprice_activity", side_effect=writer
            ) as asked,
            CaptureQueriesContext(connection) as queries,
        ):
            result = repricing.reprice_stale_plans(
                [self.visit.id, self.later.id], deadline=50.0
            )

        self.assertEqual(asked.call_count, 1)
        self.assertEqual(result["repriced"], [self.visit.id])
        self.assertEqual(result["left"], [self.later.id])
        self.assertFalse([q for q in queries if self.later.id in q["sql"]])

    def test_the_sweep_does_not_ask_a_refused_plan_again(self):
        with self._refusing(self.visit.id) as asked:
            first = repricing.reprice_stale_plans([self.visit.id], skip_refused=True)
            again = repricing.reprice_stale_plans([self.visit.id], skip_refused=True)

        self.assertEqual(first["kept"], [self.visit.id])
        self.assertEqual(again["kept"], [self.visit.id])
        self.assertEqual(asked.call_count, 1)

    def test_a_refused_plan_does_not_hold_up_the_one_behind_it(self):
        both = [self.visit.id, self.later.id]
        with self._refusing(self.visit.id) as asked:
            repricing.reprice_stale_plans(both, skip_refused=True)
            asked.reset_mock()
            again = repricing.reprice_stale_plans(both, skip_refused=True)

        self.assertEqual(
            [call.args[0].id for call in asked.call_args_list], [self.later.id]
        )
        self.assertEqual(again["kept"], [self.visit.id])
        self.assertEqual(again["repriced"], [self.later.id])

    def test_a_refused_plan_is_asked_again_later(self):
        with self._refusing(self.visit.id) as asked:
            repricing.reprice_stale_plans([self.visit.id], skip_refused=True)
            repricing._refused[self.visit.id] -= repricing.REFUSED_FOR_SECONDS + 1
            repricing.reprice_stale_plans([self.visit.id], skip_refused=True)

        self.assertEqual(asked.call_count, 2)

    def test_a_saved_rate_and_the_command_ask_every_plan(self):
        """What the Country Director is told was kept is the writer's answer
        to this save, not something remembered from an earlier run."""
        with self._refusing(self.visit.id) as asked:
            repricing.reprice_stale_plans([self.visit.id], skip_refused=True)
            repricing.reprice_stale_plans([self.visit.id])

        self.assertEqual(asked.call_count, 2)


class TheScheduledSweep(SimpleTestCase):
    def test_it_skips_refused_plans_and_says_what_it_did(self):
        from apps.realtime import jobs

        result = {"repriced": ["a", "b"], "kept": ["c"], "left": ["d", "e", "f"]}
        with (
            patch(
                "apps.budget.repricing.reprice_stale_plans", return_value=result
            ) as sweep,
            self.assertLogs("edify.jobs", level="INFO") as logs,
        ):
            done = jobs._do_cost_reprice_sweep()

        self.assertEqual(done, 2)
        self.assertTrue(sweep.call_args.kwargs["skip_refused"])
        self.assertIn("'repriced': 2, 'kept': 1, 'left': 3", logs.output[0])


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
