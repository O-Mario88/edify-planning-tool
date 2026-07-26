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
    CANONICAL_RATES,
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


class CostReferenceSurvivesAFlushTest(TransactionTestCase):
    """The case that made these rows disappear: a transactional test truncates
    every table, and a data migration does not run a second time."""

    def test_the_rate_card_exists_inside_a_transactional_test(self):
        present = set(CostSetting.objects.values_list("key", flat=True))
        missing = [key for key, _, _ in CANONICAL_RATES if key not in present]
        self.assertEqual(missing, [])
        self.assertTrue(CostCatalogue.objects.filter(is_active=True).exists())
