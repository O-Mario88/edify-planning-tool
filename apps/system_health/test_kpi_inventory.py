"""The KPI inventory must stay accurate and the completed migration stay closed.

Both ratchets are zero. A new hand-built payload or duplicated source family is
therefore a regression, not an allowance to be raised.
"""

from __future__ import annotations

import ast
import json

from django.conf import settings
from django.test import SimpleTestCase

from apps.system_health.kpi_inventory import _classify, build_inventory


# Never raise these: every real metric now goes through apps.core.metrics.
MAX_UNREGISTERED_TILES = 0
MAX_DUPLICATED_LABELS = 0


class ClassificationTests(SimpleTestCase):
    """Misclassification would send someone to fix working code."""

    def test_a_headline_number_with_presentation_keys_is_a_tile(self):
        self.assertEqual(
            _classify({"label", "value", "variant", "icon", "helper"}), "kpi-tile"
        )

    def test_a_bare_label_value_pair_is_a_breakdown_or_option(self):
        self.assertEqual(_classify({"label", "value"}), "breakdown-row")

    def test_an_ssa_band_row_is_not_a_tile(self):
        self.assertEqual(
            _classify({"label", "value", "band", "bar_pct", "score", "tone"}),
            "breakdown-row",
        )

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
        self.assertEqual(
            self.inventory.tiles(),
            [],
            "all KPI payloads must go through a registry-backed renderer",
        )
        self.assertGreater(len(self.inventory.registered_metrics), 400)

    def test_checked_in_manifest_matches_the_live_source(self):
        from pathlib import Path

        path = Path(settings.BASE_DIR) / "docs/platform-kpi-inventory.json"
        checked_in = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            checked_in,
            json.loads(json.dumps(self.inventory.as_dict())),
            "platform-kpi-inventory.json is stale; run build_kpi_inventory",
        )

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
        self.assertEqual(
            len(hand_built),
            MAX_UNREGISTERED_TILES,
            "new KPI tiles must be built through apps.core.metrics.render_metric",
        )

    def test_the_ratchet_is_tightened_as_tiles_migrate(self):
        """A ceiling left far above reality stops being a gate."""
        hand_built = [s for s in self.inventory.tiles() if not s.has_metric_key]
        self.assertEqual(
            len(hand_built),
            0,
            "the completed migration must not retain a hand-built allowance",
        )

    def test_labels_built_in_several_modules_do_not_grow(self):
        duplicated = self.inventory.labels_built_in_several_modules()
        self.assertLessEqual(
            len(duplicated),
            MAX_DUPLICATED_LABELS,
            "a metric computed in two modules needs one owning service, or two "
            f"names: {sorted(duplicated)}",
        )

    def test_previously_duplicated_families_are_reconciled(self):
        duplicated = self.inventory.labels_built_in_several_modules()
        self.assertEqual(duplicated, {})
        keys = {metric["kpi_id"] for metric in self.inventory.registered_metrics}
        self.assertIn("command_center_dashboard_service_planned_this_week", keys)
        self.assertIn("projects_my_plan_service_planned_this_week", keys)

    def test_the_summary_is_internally_consistent(self):
        summary = self.inventory.summary()
        tiles = self.inventory.tiles()
        self.assertEqual(summary["tiles"], len(tiles))
        self.assertEqual(summary["modules"], len({s.module for s in tiles}))
        self.assertEqual(
            summary["distinct_labels"], len({s.label for s in tiles if s.label})
        )
        self.assertEqual(summary["professional_headline_limit"], 6)
        self.assertEqual(summary["professional_compact_limit"], 2)
        self.assertIsNone(summary["professional_category_limit"])
        self.assertEqual(summary["supporting_metric_disclosures"], 0)

    def test_registered_payload_groups_are_audited_before_rendering(self):
        self.assertGreater(len(self.inventory.payload_groups), 30)
        self.assertGreater(
            sum(group.source_item_count for group in self.inventory.payload_groups),
            200,
        )
        for group in self.inventory.payload_groups:
            with self.subTest(group=group.audit_id):
                self.assertTrue(group.audit_id.startswith("KPI-PAYLOAD-"))
                self.assertTrue(group.module.endswith(".py"))
                self.assertGreater(group.line, 0)
                self.assertLessEqual(group.professional_headline_count, 6)
                self.assertLessEqual(len(group.professional_metric_keys), 6)
                self.assertLessEqual(
                    set(group.professional_metric_keys),
                    set(group.registered_metric_keys),
                )

    def test_every_rendered_summary_declares_its_information_hierarchy(self):
        self.assertGreater(len(self.inventory.template_sites), 40)
        unclassified = [
            site
            for site in self.inventory.template_sites
            if site.presentation not in {"executive", "supporting"}
        ]
        self.assertEqual(
            unclassified,
            [],
            "Every KPI include must choose executive or supporting; "
            "an implicit tile grid has no auditable page-level decision.",
        )

    def test_registered_metric_decisions_carry_the_required_audit_fields(self):
        required = {
            "audit_id",
            "kpi_id",
            "page",
            "roles",
            "metric_name",
            "value_type",
            "period",
            "scope",
            "data_state",
            "user_question",
            "user_decision",
            "user_action",
            "metric_class",
            "recommendation",
            "replacement_pattern",
            "implementation_status",
            "source_location",
        }
        self.assertGreater(len(self.inventory.registered_metrics), 75)
        for metric in self.inventory.registered_metrics:
            with self.subTest(metric=metric["kpi_id"]):
                self.assertFalse(required - metric.keys())
                self.assertTrue(metric["user_question"])
                self.assertTrue(metric["implementation_status"])
                self.assertTrue(metric["roles"])

    def test_reconciled_metrics_name_roles_and_exact_source_locations(self):
        reconciled = [
            metric
            for metric in self.inventory.registered_metrics
            if metric["kpi_id"].startswith(
                (
                    "accounts_hr_dashboard_service_",
                    "analytics_",
                    "projects_",
                    "targets_team_targets_",
                )
            )
        ]
        self.assertGreater(len(reconciled), 100)
        for metric in reconciled:
            with self.subTest(metric=metric["kpi_id"]):
                self.assertTrue(metric["roles"])
                self.assertRegex(metric["source_location"], r"^apps/.+\.py:\d+$")

    def test_assigned_work_pages_do_not_regress_to_kpi_grids(self):
        from pathlib import Path

        templates = Path(settings.BASE_DIR) / "templates/pages/partner"
        for name in (
            "assigned_list.html",
            "assignments.html",
            "assignment_detail.html",
        ):
            source = (templates / name).read_text(encoding="utf-8")
            self.assertNotIn("components/kpi_strip.html", source, name)
            self.assertNotIn("edify-kpi-strip", source, name)

    def test_shared_component_has_one_visual_renderer(self):
        from pathlib import Path

        root = Path(settings.BASE_DIR)
        component = (root / "templates/components/kpi_strip.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('variant == "context"', component)
        self.assertNotIn("kpi-context-summary", component)
        self.assertNotIn('data-component="context-metric"', component)
        self.assertIn("kpi-strip--executive", component)
        self.assertIn('data-component="kpi-card"', component)

    def test_executive_renderer_removes_surplus_values_from_the_html(self):
        from django.template.loader import render_to_string

        items = [
            {"label": f"Metric {number}", "value": number} for number in range(1, 8)
        ]
        html = render_to_string(
            "components/kpi_strip.html",
            {"items": items, "variant": "executive", "title": "Decision metrics"},
        )

        self.assertEqual(html.count('data-component="kpi-card"'), 6)
        self.assertIn("Metric 5", html)
        self.assertIn("Metric 6", html)
        self.assertNotIn("Metric 7", html)
        self.assertNotIn("kpi-supporting-metrics", html)

    def test_every_remaining_kpi_card_uses_the_shared_tray_visual(self):
        from pathlib import Path

        root = Path(settings.BASE_DIR)
        component = (root / "templates/components/kpi_strip.html").read_text()
        styles = (root / "static/css/components.css").read_text()

        self.assertIn("kpi-strip--executive", component)
        self.assertIn(".kpi-strip.kpi-strip--executive {", styles)
        self.assertIn("overflow: clip;", styles)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr));", styles)

    def test_compact_or_mobile_tray_has_at_most_two_items(self):
        from django.template.loader import render_to_string

        items = [
            {"label": f"Metric {number}", "value": number} for number in range(1, 5)
        ]
        html = render_to_string(
            "components/kpi_strip.html",
            {"items": items, "variant": "executive", "density": "compact"},
        )
        self.assertEqual(html.count('data-component="kpi-card"'), 2)

    def test_obsolete_context_variant_cannot_bypass_the_tile_renderer(self):
        from django.template.loader import render_to_string

        items = [{"label": "Planned", "value": 4}, {"label": "Verified", "value": 2}]
        html = render_to_string(
            "components/kpi_strip.html",
            {"items": items, "variant": "context", "title": "Plan progress"},
        )

        self.assertEqual(html.count('data-component="kpi-card"'), 2)
        self.assertNotIn('data-component="context-metric"', html)
        self.assertIn("kpi-strip--executive", html)


class ScanFidelityTests(SimpleTestCase):
    """The scan must agree with the source it claims to describe."""

    def test_a_reported_site_really_is_a_dict_at_that_line(self):
        from pathlib import Path

        from django.conf import settings

        root = Path(settings.BASE_DIR)
        sampled = build_inventory().tiles()[:40]
        self.assertEqual(sampled, [])

        for site in sampled:
            with self.subTest(f"{site.module}:{site.line}"):
                tree = ast.parse((root / site.module).read_text(encoding="utf-8"))
                lines = {
                    node.lineno for node in ast.walk(tree) if isinstance(node, ast.Dict)
                }
                self.assertIn(site.line, lines)
