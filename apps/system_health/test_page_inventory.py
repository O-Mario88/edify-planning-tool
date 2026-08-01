"""Contract tests for the living product-surface inventory."""

from pathlib import Path

from django.test import SimpleTestCase

from apps.core.rbac import EdifyRole
from apps.realtime.registry import JOB_REGISTRY
from apps.system_health.page_inventory import (
    TEMPLATE_ROOT,
    _template_findings,
    build_page_inventory,
)


class PageInventoryTest(SimpleTestCase):
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
            for finding in _template_findings(source):
                outstanding.append(
                    (str(template_path.relative_to(TEMPLATE_ROOT)), finding.key)
                )
        self.assertEqual(outstanding, [])
