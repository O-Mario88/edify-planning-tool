"""Contract tests for the living product-surface inventory."""

from django.test import SimpleTestCase

from apps.core.rbac import EdifyRole
from apps.realtime.registry import JOB_REGISTRY
from apps.system_health.page_inventory import build_page_inventory


class PageInventoryTest(SimpleTestCase):
    def test_inventory_discovers_the_platform_and_required_metadata(self):
        inventory = build_page_inventory()
        self.assertGreaterEqual(inventory["summary"]["routed_surfaces"], 90)
        self.assertGreaterEqual(inventory["summary"]["all_routes"], 200)
        # Derived from the registries rather than hardcoded, so adding a role
        # or a scheduled job doesn't fail an unrelated inventory assertion.
        self.assertEqual(inventory["summary"]["roles"], len(EdifyRole.values()))
        self.assertEqual(
            inventory["summary"]["scheduled_jobs"], len(JOB_REGISTRY)
        )
        self.assertGreaterEqual(inventory["summary"]["permission_keys"], 38)
        self.assertGreaterEqual(inventory["summary"]["component_templates"], 100)

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
