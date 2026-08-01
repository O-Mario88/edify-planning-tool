"""The KPI inventory must stay accurate, and the unregistered surface must shrink.

The ratchets below are deliberately set to *today's* measured numbers rather
than to zero. A gate nobody can pass gets muted; a gate one metric away from
passing gets fixed. Each migration onto ``apps.core.metrics`` should lower the
ceiling in this file, and the assertions fail if the ceiling is left stale
after the surface improves.
"""

from __future__ import annotations

import ast

from django.test import SimpleTestCase

from apps.system_health.kpi_inventory import _classify, build_inventory


# Lower these as tiles migrate; never raise them.
#
# The surface before the metric registry was 281 unregistered tiles and 21
# label families computed in more than one module. Migrating My Plan's strip
# (8 tiles) and deleting the duplicated "Planned Activities Funding" tile on PL
# Fund Approvals took it to 272. The shared SSA, Impact, Partner,
# country-health and Admin Operations migration then registered 27 tiles and
# removed the non-metric Team Plans CTA, leaving the total four below that
# earlier baseline.
MAX_UNREGISTERED_TILES = 268
MAX_DUPLICATED_LABELS = 16


class ClassificationTests(SimpleTestCase):
    """Misclassification would send someone to fix working code."""

    def test_a_headline_number_with_presentation_keys_is_a_tile(self):
        self.assertEqual(
            _classify({"label", "value", "variant", "icon", "helper"}), "kpi-tile"
        )

    def test_a_bare_label_value_pair_is_a_tile(self):
        self.assertEqual(_classify({"label", "value"}), "kpi-tile")

    def test_a_status_bucket_row_is_not_a_tile(self):
        """`weekly_status_buckets` rows repeat by design, not by mistake."""
        self.assertEqual(_classify({"label", "amount", "tone"}), "breakdown-row")

    def test_a_count_row_without_a_value_is_not_a_tile(self):
        self.assertEqual(_classify({"label", "count", "url"}), "breakdown-row")


class InventoryTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inventory = build_inventory()

    def test_the_scan_finds_the_kpi_surface(self):
        self.assertGreater(len(self.inventory.tiles()), 100)

    def test_every_site_records_where_it_was_found(self):
        for site in self.inventory.tiles():
            with self.subTest(f"{site.module}:{site.line}"):
                self.assertTrue(site.module.endswith(".py"))
                self.assertGreater(site.line, 0)

    def test_tests_and_migrations_are_not_scanned(self):
        for site in self.inventory.sites:
            with self.subTest(site.module):
                self.assertNotIn("/migrations/", site.module)
                self.assertFalse(site.module.rsplit("/", 1)[-1].startswith("test_"))

    def test_the_hand_built_tile_count_does_not_grow(self):
        """A tile built through `render_metric` leaves this scan entirely, so
        this count is "tiles still written by hand" and should only fall."""
        hand_built = [s for s in self.inventory.tiles() if not s.has_metric_key]
        self.assertLessEqual(
            len(hand_built),
            MAX_UNREGISTERED_TILES,
            "new KPI tiles must be built through apps.core.metrics.render_metric",
        )

    def test_the_ratchet_is_tightened_as_tiles_migrate(self):
        """A ceiling left far above reality stops being a gate."""
        hand_built = [s for s in self.inventory.tiles() if not s.has_metric_key]
        self.assertGreater(
            len(hand_built),
            MAX_UNREGISTERED_TILES - 15,
            "the hand-built surface has shrunk -- lower MAX_UNREGISTERED_TILES "
            "in this file to lock the improvement in",
        )

    def test_labels_built_in_several_modules_do_not_grow(self):
        duplicated = self.inventory.labels_built_in_several_modules()
        self.assertLessEqual(
            len(duplicated),
            MAX_DUPLICATED_LABELS,
            "a metric computed in two modules needs one owning service, or two "
            f"names: {sorted(duplicated)}",
        )

    def test_known_duplicate_families_are_still_detected(self):
        """Guards the detector itself, not the product.

        If a refactor makes these stop being reported, the scan has gone blind
        rather than the duplication having been fixed -- the registry, not this
        assertion, is what records a genuine consolidation.
        """
        duplicated = self.inventory.labels_built_in_several_modules()
        self.assertIn("Planned This Week", duplicated)
        self.assertGreaterEqual(len(duplicated["Planned This Week"]), 2)

    def test_the_summary_is_internally_consistent(self):
        summary = self.inventory.summary()
        tiles = self.inventory.tiles()
        self.assertEqual(summary["tiles"], len(tiles))
        self.assertEqual(summary["modules"], len({s.module for s in tiles}))
        self.assertEqual(
            summary["distinct_labels"], len({s.label for s in tiles if s.label})
        )


class ScanFidelityTests(SimpleTestCase):
    """The scan must agree with the source it claims to describe."""

    def test_a_reported_site_really_is_a_dict_at_that_line(self):
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR)
        sampled = build_inventory().tiles()[:40]
        self.assertTrue(sampled)

        for site in sampled:
            with self.subTest(f"{site.module}:{site.line}"):
                tree = ast.parse((root / site.module).read_text(encoding="utf-8"))
                lines = {
                    node.lineno for node in ast.walk(tree) if isinstance(node, ast.Dict)
                }
                self.assertIn(site.line, lines)
