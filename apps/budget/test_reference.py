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

    def test_default_catalogue_resolution_stays_in_the_operational_fy(self):
        from django.conf import settings

        from apps.budget.costing_service import active_catalogue
        from apps.core.fy import get_operational_fy

        operational = active_catalogue()
        self.assertIsNotNone(operational)
        CostCatalogue.objects.create(
            country=getattr(settings, "COUNTRY", "Uganda"),
            fy=str(int(get_operational_fy()) + 1),
            version=99,
            is_active=True,
            label="Future catalogue that must not price current work",
        )

        self.assertEqual(active_catalogue().id, operational.id)

    def test_costing_ignores_a_rate_not_shown_in_the_active_catalogue(self):
        from apps.budget.costing_service import preview

        key = "group_training_participant_meal_cost_per_head"
        rate = CostSetting.objects.get(key=key)
        rate.catalogue = None
        rate.save(update_fields=["catalogue", "updated_at"])

        result = preview(
            {
                "activityType": "cluster_training",
                "expectedParticipants": 10,
            }
        )

        meal_line = next(line for line in result["lines"] if line["key"] == key)
        self.assertTrue(meal_line["missing"])
        self.assertIn(key, result["missingItems"])
        self.assertFalse(result["canSchedule"])

    def test_cost_settings_api_ignores_orphaned_rows(self):
        from apps.budget.services import list_cost_settings

        key = "group_training_venue_cost"
        rate = CostSetting.objects.get(key=key)
        rate.catalogue = None
        rate.save(update_fields=["catalogue", "updated_at"])

        visible_keys = {
            item["key"]
            for item in list_cost_settings(principal=None, query={})["settings"]
        }
        self.assertNotIn(key, visible_keys)

    def test_a_hidden_legacy_rate_cannot_replace_a_missing_cd_page_rate(self):
        from apps.budget.costing_service import active_catalogue, preview

        canonical_key = "primary_transport_per_day"
        legacy_key = "staff_visit_transport_primary"
        canonical = CostSetting.objects.get(key=canonical_key)
        canonical.catalogue = None
        canonical.save(update_fields=["catalogue", "updated_at"])
        CostSetting.objects.update_or_create(
            key=legacy_key,
            defaults={
                "label": "Hidden legacy transport",
                "unit_cost": 999_999,
                "catalogue": active_catalogue(),
            },
        )

        result = preview(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
            }
        )

        self.assertIn(canonical_key, result["missingItems"])
        self.assertNotIn(legacy_key, {line["key"] for line in result["lines"]})
        self.assertFalse(result["canSchedule"])

    def test_missing_activity_specific_rate_is_not_replaced_by_visit_costs(self):
        from apps.budget.costing_service import preview

        key = "core_school_training"
        rate = CostSetting.objects.get(key=key)
        rate.catalogue = None
        rate.save(update_fields=["catalogue", "updated_at"])

        result = preview({"activityType": "core_training"})

        self.assertEqual(result["missingItems"], [key])
        self.assertEqual([line["key"] for line in result["lines"]], [key])
        self.assertFalse(result["canSchedule"])

    def test_cost_catalogue_projects_coverage_for_all_governed_activities(self):
        from apps.activity_catalogue.services import effective_items
        from apps.budget.costing_service import activity_cost_coverage

        items = list(
            effective_items()
            .prefetch_related("intervention_mappings")
            .order_by("display_name")
        )
        coverage = activity_cost_coverage(items)

        # 28 governed curriculum titles + 12 standard field support items.
        # Standard support draws from the same CD rate card as everything
        # else — a school visit that nothing in the catalogue can price is
        # exactly the state that made ordinary support unschedulable.
        self.assertEqual(len(coverage), 40)
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
