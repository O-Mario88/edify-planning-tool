"""Contract tests for the living product-surface inventory."""

import json
from collections import Counter

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import get_resolver

from apps.core.rbac import EdifyRole
from apps.realtime.registry import JOB_REGISTRY
from apps.system_health.page_inventory import (
    TEMPLATE_ROOT,
    _iter_patterns,
    _template_findings,
    build_page_inventory,
    inventory_as_markdown,
)


class PageInventoryTest(SimpleTestCase):
    def test_checked_in_manifests_match_the_live_platform(self):
        """Generated evidence must describe this exact source revision."""
        inventory = build_page_inventory()
        docs = Path(settings.BASE_DIR) / "docs"
        checked_in_json = json.loads(
            (docs / "platform-page-inventory.json").read_text(encoding="utf-8")
        )
        checked_in_markdown = (docs / "platform-page-inventory.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            checked_in_json,
            inventory,
            "platform-page-inventory.json is stale; run build_page_inventory",
        )
        self.assertEqual(
            checked_in_markdown,
            inventory_as_markdown(inventory),
            "platform-page-inventory.md is stale; run build_page_inventory",
        )

    def test_route_manifest_is_complete(self):
        """Every resolver entry must appear exactly once in the route manifest.

        Comparing counters rather than sets also detects a generator that
        silently collapses duplicate route/name registrations.
        """
        manifest = build_page_inventory()
        expected = Counter(
            (route, pattern.name or "")
            for pattern, route in _iter_patterns(get_resolver().url_patterns)
        )
        actual = Counter(
            (item["route"], item["route_name"]) for item in manifest["routes"]
        )
        self.assertEqual(actual, expected)
        self.assertEqual(manifest["summary"]["all_routes"], sum(actual.values()))

    def test_inventory_discovers_the_platform_and_required_metadata(self):
        inventory = build_page_inventory()
        self.assertGreaterEqual(inventory["summary"]["routed_surfaces"], 90)
        self.assertGreaterEqual(inventory["summary"]["all_routes"], 200)
        self.assertGreaterEqual(inventory["summary"]["permission_keys"], 38)
        self.assertGreaterEqual(inventory["summary"]["component_templates"], 100)

        # Counting the registries the inventory itself reads from would compare
        # a value to itself. Assert the inventory reproduces them faithfully and
        # that each entry is usable — those can actually fail.
        platform = inventory["platform"]
        self.assertEqual(set(platform["roles"]), {role.value for role in EdifyRole})
        self.assertEqual(
            {job["name"] for job in platform["scheduled_jobs"]},
            {job.name for job in JOB_REGISTRY},
        )
        for job in platform["scheduled_jobs"]:
            self.assertTrue(job.get("cron"), f"{job['name']} has no schedule")
            self.assertTrue(job.get("description"), f"{job['name']} has no description")
            self.assertTrue(
                job.get("idempotency_note") or not job.get("idempotent"),
                f"{job['name']} claims idempotency without saying why",
            )

        dashboard = next(
            page for page in inventory["pages"] if page["route"] == "/dashboard"
        )
        self.assertEqual(dashboard["page_title"], "Dashboard")
        self.assertIn("ADMIN", dashboard["role_access"])
        self.assertTrue(dashboard["templates"])
        self.assertIn("state_coverage", dashboard)
        self.assertIsNone(dashboard["manual_quality_score"])

    def test_every_permission_gated_surface_has_a_role_mapping(self):
        inventory = build_page_inventory()
        missing = [
            page["route"]
            for page in inventory["pages"]
            if page["permission_key"] and not page["role_access"]
        ]
        self.assertEqual(missing, [])

    def test_template_audit_distinguishes_state_bindings_and_ids_from_style_debt(self):
        findings = _template_findings(
            '<button hx-target="#add-school" :style="`left:${x}px`">Open</button>'
        )
        self.assertEqual(findings, [])

        findings = _template_findings(
            '<div class="bg-white text-[#123456]" style="margin: 2px"></div>'
        )
        self.assertEqual(
            {finding.key for finding in findings},
            {"legacy-white-surface", "raw-hex", "inline-style"},
        )

    def test_routed_frontend_has_no_automated_design_system_findings(self):
        inventory = build_page_inventory()
        outstanding = [
            (page["route"], finding["key"])
            for page in inventory["pages"]
            for finding in page["findings"]
        ]
        self.assertEqual(outstanding, [])

    def test_every_template_has_no_automated_design_system_findings(self):
        outstanding = []
        for template_path in Path(TEMPLATE_ROOT).rglob("*.html"):
            source = template_path.read_text(encoding="utf-8")
            name = str(template_path.relative_to(TEMPLATE_ROOT))
            # Pass the name, as the inventory does: some rules are scoped to
            # where they apply (the shell legitimately renders the one
            # persistent search once per breakpoint).
            for finding in _template_findings(source, name):
                outstanding.append((name, finding.key))
        self.assertEqual(outstanding, [])
