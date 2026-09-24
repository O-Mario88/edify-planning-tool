"""The catalogue page costs the same however many items it lists (PERF-04).

Each card's "N scheduled uses" was `item.activities.count`, evaluated twice
per card: 130 COUNT queries on every load of the settings page (2026-09-24
live-performance audit). It is one correlated count on the listing query now.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.activity_catalogue.authoring import create_catalogue_item


def _item(name):
    return create_catalogue_item(
        {
            "name": name,
            "kind": "school",
            "activityType": "school_visit",
            "deliveryMethod": "school_visit",
            "costingProfile": "ONETEST",
            "reason": "Query budget fixture.",
        },
        actor_id="cd_1",
    )


class CataloguePageQueryBudgetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = get_user_model().objects.create_user(
            email="catalogue-cd@edify.test",
            password="password123",
            name="Catalogue CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        StaffProfile.objects.create(id="catalogue-cd-staff", user=cls.cd)

    def setUp(self):
        self.client.force_login(self.cd)

    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/settings/activity-catalogue/")
        self.assertEqual(response.status_code, 200)
        return len(ctx), response

    def test_more_items_cost_no_more_queries(self):
        _item("Budget Visit One")
        self.client.get("/settings/activity-catalogue/")  # warm per-process caches
        few, _ = self._queries()
        for n in range(6):
            _item(f"Budget Visit Extra {n}")
        many, _ = self._queries()
        self.assertEqual(many, few)

    def test_the_card_shows_the_live_use_count(self):
        item = _item("Counted Visit")
        Activity.objects.create(activity_type="school_visit", catalogue_item=item)
        Activity.objects.create(activity_type="school_visit", catalogue_item=item)
        removed = Activity.objects.create(
            activity_type="school_visit", catalogue_item=item
        )
        removed.soft_delete()
        _count, response = self._queries()
        self.assertContains(response, "2 scheduled uses")
