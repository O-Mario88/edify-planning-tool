"""The official target areas are reference data the platform cannot run without.

An empty `target_area` table does not raise anywhere it is read — it resolves
no keys, writes no rows and reports success. That is how an HR approval came to
say it had populated My Targets while writing nothing at all: a
TransactionTestCase had flushed the table, and rows put there by a data
migration never come back.
"""

from __future__ import annotations

from django.test import TestCase, TransactionTestCase

from apps.targets.models import TargetArea
from apps.targets.reference import OFFICIAL_TARGET_AREAS, ensure_target_areas


class ReferenceDataTest(TestCase):
    def test_the_official_areas_are_present_after_migration(self):
        keys = set(TargetArea.objects.values_list("key", flat=True))
        self.assertTrue(
            {a[0] for a in OFFICIAL_TARGET_AREAS}.issubset(keys),
            f"missing official target areas: {keys}",
        )

    def test_active_weights_total_one_hundred(self):
        """Overall Progress is a weighted average; weights that do not total
        100 make it a number with no defined meaning."""
        total = sum(
            TargetArea.objects.filter(
                active=True, key__in=[a[0] for a in OFFICIAL_TARGET_AREAS]
            ).values_list("weight", flat=True)
        )
        self.assertEqual(total, 100)

    def test_the_migration_and_the_reference_list_agree(self):
        """Two copies of the same list, deliberately — a migration must stay
        frozen in time — so they have to be pinned to each other."""
        import importlib

        migration = importlib.import_module(
            "apps.targets.migrations.0003_seed_target_areas"
        )
        self.assertEqual(
            [tuple(row) for row in migration.AREAS], list(OFFICIAL_TARGET_AREAS)
        )

    def test_ensure_is_idempotent(self):
        before = TargetArea.objects.count()
        self.assertEqual(ensure_target_areas(), 0)
        self.assertEqual(TargetArea.objects.count(), before)

    def test_ensure_does_not_overwrite_an_administrator_edit(self):
        area = TargetArea.objects.get(key="school_visits")
        area.weight = 35
        area.save(update_fields=["weight"])
        ensure_target_areas()
        area.refresh_from_db()
        self.assertEqual(area.weight, 35)


class ReferenceDataSurvivesAFlushTest(TransactionTestCase):
    """A TransactionTestCase truncates every table on teardown.

    This is the case that broke: with the rows only ever created by a data
    migration, the table stayed empty afterwards — permanently, for a reused
    test database. `post_migrate` fires after `flush` too, which is what
    restores them.
    """

    def test_the_areas_exist_inside_a_transactional_test(self):
        self.assertTrue(TargetArea.objects.filter(active=True).exists())
