"""A cost the Country Director adds is linked to one activity and priced on
every schedule of it (owner, 2026-09-06: "the cd can add more cost using add
new cost but the cost needs to be linked to an activity").
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import User
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget import services as budget_services
from apps.budget.costing_service import (
    active_catalogue,
    activity_cost_coverage,
    preview,
)
from apps.budget.models import CostSetting
from apps.core.exceptions import BadRequest


class LinkedCostTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = User.objects.create(
            id="cd_link",
            email="cd.link@edify.org",
            name="CD Link",
            roles=["CountryDirector"],
        )
        cls.cd.active_role = "CountryDirector"
        cls.visit = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT"
        )
        cls.other = (
            ActivityCatalogueItem.objects.exclude(pk=cls.visit.pk)
            .order_by("display_name")
            .first()
        )

    def _add(self, label="Diagnostic kit", cost=25_000, item=None):
        return budget_services.add_linked_cost(
            {
                "catalogueItemId": (item or self.visit).id,
                "label": label,
                "unitCost": cost,
                "approvedMinimum": cost,
                "reason": "Every visit of this kind consumes one.",
            },
            self.cd,
        )

    def test_the_cost_is_keyed_to_its_activity_and_lands_on_the_active_card(self):
        result = self._add()
        self.assertEqual(result["key"], "activity:standard_school_visit:diagnostic_kit")
        row = CostSetting.objects.get(key=result["key"], catalogue=active_catalogue())
        self.assertEqual(row.catalogue_item_id, self.visit.id)
        self.assertEqual(row.unit, "per activity")
        self.assertEqual(row.unit_cost, 25_000)

    def test_the_activity_prices_the_cost_and_other_activities_do_not(self):
        self._add()
        base = {
            "activityType": "school_visit",
            "deliveryType": "staff",
            "districtType": "primary",
        }
        with_link = preview({**base, "catalogueItemId": self.visit.id})
        without = preview({**base, "catalogueItemId": self.other.id})
        keys = [line["key"] for line in with_link["lines"]]
        self.assertIn("activity:standard_school_visit:diagnostic_kit", keys)
        self.assertEqual(with_link["amount"], without["amount"] + 25_000)
        self.assertNotIn(
            "activity:standard_school_visit:diagnostic_kit",
            [line["key"] for line in without["lines"]],
        )

    def test_the_cost_shows_in_the_activity_coverage_and_the_rate_list(self):
        self._add()
        coverage = {
            row["stable_code"]: row
            for row in activity_cost_coverage([self.visit, self.other])
        }
        self.assertIn("Diagnostic kit", coverage["STANDARD_SCHOOL_VISIT"]["components"])
        self.assertNotIn(
            "Diagnostic kit", coverage[self.other.stable_code]["components"]
        )
        listed = budget_services.list_cost_settings(None, {})["settings"]
        linked = [s for s in listed if s["key"].startswith("activity:")]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0]["catalogueItemName"], self.visit.display_name)

    def test_a_cost_needs_an_activity_and_a_name(self):
        with self.assertRaises(BadRequest):
            budget_services.add_linked_cost(
                {"label": "Orphan", "unitCost": 1, "reason": "no activity"}, self.cd
            )
        with self.assertRaises(BadRequest):
            self._add(label="   ")

    def test_editing_the_cost_keeps_its_link_across_versions(self):
        result = self._add()
        budget_services.upsert_cost_setting(
            {"key": result["key"], "unitCost": 30_000, "reason": "Kits cost more."},
            self.cd,
        )
        row = CostSetting.objects.get(key=result["key"], catalogue=active_catalogue())
        self.assertEqual(row.unit_cost, 30_000)
        self.assertEqual(row.catalogue_item_id, self.visit.id)
        self.assertEqual(row.version, 2)
