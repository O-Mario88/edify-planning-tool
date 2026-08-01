"""The cost rate card is reference data the platform cannot cost work without.

Every costing path resolves a rate by key and treats a missing key as "no
cost", not as an error — so an empty `cost_setting` table produces plans,
requests and budgets that silently come to nothing. The rows arrived through
data migrations, which a flushed database never replays.
"""

from __future__ import annotations

from django.test import TestCase, TransactionTestCase

from apps.budget.models import CostCatalogue, CostSetting
from apps.budget.reference import (
    CANONICAL_RATE_KEYS,
    CANONICAL_RATES,
    RETIRED_COST_SETTING_KEYS,
    ensure_active_catalogue,
    ensure_cost_reference,
)


class CostReferenceTest(TestCase):
    def test_every_canonical_rate_exists(self):
        present = set(CostSetting.objects.values_list("key", flat=True))
        missing = [key for key, _, _ in CANONICAL_RATES if key not in present]
        self.assertEqual(missing, [], f"missing canonical rates: {missing}")

    def test_there_is_exactly_one_active_catalogue(self):
        """A snapshot stamps catalogue id and version; two active catalogues
        make that stamp ambiguous, and none makes it impossible."""
        self.assertEqual(CostCatalogue.objects.filter(is_active=True).count(), 1)

    def test_every_canonical_rate_is_attached_to_a_catalogue(self):
        orphans = list(
            CostSetting.objects.filter(
                key__in=[k for k, _, _ in CANONICAL_RATES], catalogue__isnull=True
            ).values_list("key", flat=True)
        )
        self.assertEqual(orphans, [])

    def test_ensure_is_idempotent(self):
        before = CostSetting.objects.count()
        self.assertEqual(ensure_cost_reference(), 0)
        self.assertEqual(CostSetting.objects.count(), before)

    def test_ensure_does_not_reset_a_rate_the_country_director_changed(self):
        rate = CostSetting.objects.get(key="primary_lunch_per_day")
        rate.unit_cost = 19000
        rate.save(update_fields=["unit_cost"])
        ensure_cost_reference()
        rate.refresh_from_db()
        self.assertEqual(rate.unit_cost, 19000)

    def test_ensure_active_catalogue_returns_the_existing_one(self):
        existing = CostCatalogue.objects.filter(is_active=True).first()
        self.assertEqual(ensure_active_catalogue().id, existing.id)

    def test_canonical_registry_has_no_duplicate_or_retired_keys(self):
        keys = [key for key, _label, _cost in CANONICAL_RATES]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(CANONICAL_RATE_KEYS.isdisjoint(RETIRED_COST_SETTING_KEYS))

    def test_cost_settings_api_surface_contains_only_canonical_items(self):
        from apps.budget.services import list_cost_settings

        result = list_cost_settings(principal=None, query={})
        visible_keys = {item["key"] for item in result["settings"]}

        self.assertEqual(visible_keys, CANONICAL_RATE_KEYS)
        self.assertTrue(visible_keys.isdisjoint(RETIRED_COST_SETTING_KEYS))

    def test_cost_catalogue_projects_coverage_for_all_governed_activities(self):
        from apps.activity_catalogue.services import effective_items
        from apps.budget.costing_service import activity_cost_coverage

        items = list(
            effective_items()
            .prefetch_related("intervention_mappings")
            .order_by("display_name")
        )
        coverage = activity_cost_coverage(items)

        self.assertEqual(len(coverage), 28)
        self.assertEqual(
            {row["stable_code"] for row in coverage},
            {item.stable_code for item in items},
        )
        self.assertTrue(all(row["components"] for row in coverage))

    def test_visit_costing_prefers_one_canonical_source_per_allowance(self):
        from apps.budget.costing import cost_for_activity

        result = cost_for_activity(
            {
                "activityType": "school_visit",
                "districtType": "primary",
                "deliveryType": "staff",
            },
            {
                "primary_transport_per_day": 56000,
                "primary_lunch_per_day": 30000,
                "staff_visit_transport_primary": 999999,
                "lunch": 999999,
            },
        )

        self.assertEqual(
            [line.key for line in result.lines],
            ["primary_transport_per_day", "primary_lunch_per_day"],
        )
        self.assertEqual(result.amount, 86000)


class CostReferenceSurvivesAFlushTest(TransactionTestCase):
    """The case that made these rows disappear: a transactional test truncates
    every table, and a data migration does not run a second time."""

    def test_the_rate_card_exists_inside_a_transactional_test(self):
        present = set(CostSetting.objects.values_list("key", flat=True))
        missing = [key for key, _, _ in CANONICAL_RATES if key not in present]
        self.assertEqual(missing, [])
        self.assertTrue(CostCatalogue.objects.filter(is_active=True).exists())
