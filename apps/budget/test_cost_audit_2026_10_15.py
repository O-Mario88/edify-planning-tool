"""Every cost is the activity's own cost (owner, 2026-10-15: "I want every
cost fetched exactly the cost of the activity, no doubling the cost, no
inflating or deflating the costs, no misleading costs").

Found reading production the same day (the team's FY2027 plan, every cost
line):

  1. An in-school Training whose School Visit had been called off still read
     as the free half of a pair, so the day's visit cost was in no budget at
     all (Nissi College Akia, 10 December 2026). The owner's rule: a training
     with no companion visit carries the visit cost.
  2. Planning Oversight wrote every in-school Training's cost as 0 whatever
     it carried, so a Training priced as its own visit day (Adonai, Gulu,
     UGX 73,000) was missing from the page's planned budget and its export.
  3. A Programme Lead's three nights away were filed under the CCEO's
     accommodation rate: the rate was chosen by the role the person happened
     to be using when the day was priced, not the role they hold.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.pair_costing import (
    UNCOSTED_PAIR_TRAINING,
    is_uncosted_pair_training,
    live_companions,
)
from apps.core.rbac import EdifyRole
from apps.daily_visit_batches.pricing import (
    ACCOMMODATION_KEY,
    MANAGEMENT_ACCOMMODATION_KEY,
)
from apps.frontend import test_oversight_filters_export as export_tests
from apps.fund_requests import test_paired_visit_not_funded_twice as pair_tests

TRAINING_COST, VISIT_COST = pair_tests.TRAINING_COST, pair_tests.VISIT_COST


class APairIsAPairWhileItsVisitIsLive(pair_tests.PairedVisitIsNotFundedTwiceTest):
    """Runs the fund-request pair tests as they stand, then the visit leaves."""

    def _uncosted(self):
        return set(
            Activity.objects.filter(UNCOSTED_PAIR_TRAINING).values_list("id", flat=True)
        )

    def test_a_live_pair_s_training_is_the_free_half(self):
        self.assertTrue(is_uncosted_pair_training(self.training))
        self.assertIn(self.training.id, self._uncosted())
        self.assertEqual(live_companions([self.training]), {self.visit.id})

    def test_a_training_whose_visit_was_called_off_carries_the_day(self):
        for status in ("cancelled", "rejected", "deferred"):
            with self.subTest(status=status):
                Activity.objects.filter(pk=self.visit.pk).update(status=status)
                self.training.refresh_from_db()
                self.assertFalse(is_uncosted_pair_training(self.training))
                self.assertNotIn(self.training.id, self._uncosted())
                self.assertEqual(live_companions([self.training]), set())

    def test_a_training_whose_visit_was_deleted_carries_the_day(self):
        from django.utils import timezone

        Activity.objects.filter(pk=self.visit.pk).update(deleted_at=timezone.now())
        self.training.refresh_from_db()
        self.assertFalse(is_uncosted_pair_training(self.training))

    def test_its_cost_is_then_requested(self):
        Activity.objects.filter(pk=self.visit.pk).update(status="cancelled")
        result, items = self._submit()
        self.assertIn(
            self.training.id, set(items.values_list("activity_id", flat=True))
        )
        self.assertEqual(result["totalAmount"], TRAINING_COST)
        self.assertNotEqual(result["totalAmount"], TRAINING_COST + VISIT_COST)


class APairSettlesWhenItsVisitChanges(pair_tests.PairedVisitIsNotFundedTwiceTest):
    """The two halves of a pair never disagree about the day (owner,
    2026-10-15): pricing or calling off the visit re-prices its Training only
    when the Training disagrees with the visit's state."""

    def _settled(self):
        from unittest.mock import patch

        from apps.activities import services

        with patch.object(services, "_price_activity") as price:
            services._settle_pair_training(self.visit)
        return [call.args[0].id for call in price.call_args_list]

    def test_a_live_visit_takes_the_day_off_its_training(self):
        # The fixture's Training holds a day line beside a live visit.
        self.assertEqual(self._settled(), [self.training.id])

    def test_a_called_off_visit_leaves_the_day_on_its_training(self):
        Activity.objects.filter(pk=self.visit.pk).update(status="deferred")
        self.assertEqual(self._settled(), [])

    def test_a_called_off_visit_puts_the_day_on_a_bare_training(self):
        Activity.objects.filter(pk=self.visit.pk).update(status="deferred")
        ActivityScheduleCostLine.objects.filter(activity=self.training).delete()
        self.assertEqual(self._settled(), [self.training.id])

    def test_a_settled_pair_is_left_alone(self):
        ActivityScheduleCostLine.objects.filter(activity=self.training).delete()
        self.assertEqual(self._settled(), [])

    def test_a_partner_fee_is_not_the_day(self):
        ActivityScheduleCostLine.objects.filter(activity=self.training).update(
            line_item_type="facilitation"
        )
        self.assertEqual(self._settled(), [])

    def test_a_delivered_training_is_never_repriced(self):
        Activity.objects.filter(pk=self.training.pk).update(status="ia_verified")
        self.assertEqual(self._settled(), [])

    def test_deferring_a_visit_settles_its_training(self):
        from unittest.mock import patch

        from apps.activities import services

        with patch.object(services, "_settle_pair_training") as settle:
            services.defer(self.visit.id, {"reason": "school closed"}, self.owner)
        self.assertEqual([c.args[0].id for c in settle.call_args_list], [self.visit.id])


class PlanningOversightShowsTheTrainingsOwnCost(export_tests.FilterExportFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # No companion visit: it is its own journey and carries the visit day.
        cls.solo = Activity.objects.create(
            activity_type="in_school_training",
            school=cls.school,
            fy=cls.fy,
            quarter="Q1",
            planned_date=cls.visit.planned_date,
            planned_month=cls.visit.planned_month,
            status="scheduled",
            responsible_staff_id=cls.james.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=cls.solo,
            cost_setting_key="primary_transport_per_day",
            line_item_type="transport",
            label="Transport Primary District",
            unit_cost=73_000,
            quantity=1,
            amount=73_000,
        )

    def test_the_export_and_the_page_total_carry_it(self):
        from apps.planning import oversight_service as svc

        # The export is My Plan's tables (owner, 2026-10-26): the training is
        # on Trainings, and its Cost is what My Plan writes for it. The page's
        # total carries the training's own day.
        rows = [
            row
            for row in self.export_records(fy=self.fy)
            if row["Sheet"] == "Trainings" and row["Mode of Delivery"]
        ]
        self.assertTrue(rows)
        items = [
            item
            for item in svc.build_items(self.pl_user, fy=self.fy)
            if item.activity_id == self.solo.id
        ]
        self.assertEqual([item.planned_cost for item in items], [73_000])


class TheNightFollowsTheRoleHeld(SimpleTestCase):
    def _key(self, roles, active):
        from types import SimpleNamespace

        from apps.daily_visit_batches import districts

        user = SimpleNamespace(roles=roles, active_role=active)
        return districts.accommodation_key_for_user(user)

    def test_a_programme_lead_using_another_role_sleeps_at_the_lead_rate(self):
        lead = EdifyRole.COUNTRY_PROGRAM_LEAD.value
        cceo = EdifyRole.CCEO.value
        self.assertEqual(self._key([lead, cceo], cceo), MANAGEMENT_ACCOMMODATION_KEY)
        self.assertEqual(self._key([lead], lead), MANAGEMENT_ACCOMMODATION_KEY)

    def test_a_cceo_acting_as_lead_sleeps_at_the_cceo_rate(self):
        # Acting for a month is following up, never a change of post (owner,
        # 2026-10-07).
        lead = EdifyRole.COUNTRY_PROGRAM_LEAD.value
        cceo = EdifyRole.CCEO.value
        self.assertEqual(self._key([cceo], lead), ACCOMMODATION_KEY)
        self.assertEqual(self._key([cceo], cceo), ACCOMMODATION_KEY)

    def test_an_account_with_no_roles_listed_reads_its_active_role(self):
        self.assertEqual(
            self._key([], EdifyRole.COUNTRY_DIRECTOR.value),
            MANAGEMENT_ACCOMMODATION_KEY,
        )
        self.assertEqual(self._key([], None), ACCOMMODATION_KEY)


class AnOnlineCatalogueTrainingPreviewsFree(TestCase):
    """The Work Plan drawer previews what the save writes (owner, 2026-10-15:
    "no misleading costs"). An online catalogue training is saved free
    (apps.activities.online_training); its preview priced meals, a room, a
    facilitator and the officer's day."""

    def test_the_work_plan_preview_of_an_online_training_is_nothing(self):
        from apps.accounts.models import StaffProfile, User
        from apps.activity_catalogue.models import ActivityCatalogueItem

        cceo = User.objects.create_user(
            email="online-preview@edify.org",
            name="Online Preview",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
        )
        StaffProfile.objects.create(user=cceo, title="CCEO")
        item = ActivityCatalogueItem.objects.get(
            stable_code="EARLY_CHILDHOOD_EDUCATION_PROJECT"
        )
        self.client.force_login(cceo)

        response = self.client.post(
            "/work-plan/add/preview",
            {
                "catalogue_item_id": item.id,
                "scheduled_date": "2026-11-10",
                "expected_participants": "25",
            },
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(response.context["online_free"])
        self.assertContains(response, "UGX 0")
        self.assertNotContains(response, "Venue")
