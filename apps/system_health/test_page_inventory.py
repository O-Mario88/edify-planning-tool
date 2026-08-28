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
    APPROVED_PAGE_TYPES,
    TEMPLATE_ROOT,
    _iter_patterns,
    _template_findings,
    build_page_inventory,
    component_catalogue_as_markdown,
    inventory_as_markdown,
)


def _describe_drift(was, now, path="") -> str:
    """The first handful of differing paths through two nested structures.

    A truncated `assertEqual` on a multi-megabyte manifest tells a reader
    nothing except that something changed. This walks both sides and names the
    keys, so a CI failure a developer cannot reproduce still says where to
    look.
    """
    if type(was) is not type(now):
        return f"{path or 'root'}: {type(was).__name__} -> {type(now).__name__}"
    if isinstance(was, dict):
        out = []
        for key in sorted(set(was) | set(now), key=str):
            if key not in was:
                out.append(f"{path}.{key} added")
            elif key not in now:
                out.append(f"{path}.{key} removed")
            elif was[key] != now[key]:
                out.append(_describe_drift(was[key], now[key], f"{path}.{key}"))
            if len(out) >= 5:
                break
        return "; ".join(p for p in out if p)
    if isinstance(was, list):
        if len(was) != len(now):
            return f"{path}: {len(was)} entries -> {len(now)}"
        out = []
        for index, (a, b) in enumerate(zip(was, now)):
            if a != b:
                out.append(_describe_drift(a, b, f"{path}[{index}]"))
            if len(out) >= 5:
                break
        return "; ".join(p for p in out if p)
    return f"{path}: {was!r} -> {now!r}"


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
        checked_in_components = (docs / "platform-component-catalogue.md").read_text(
            encoding="utf-8"
        )
        # Name what drifted rather than leaving a 2.9-million-character diff
        # that unittest truncates to two unreadable fragments. Same reason as
        # the card inventory: this manifest went stale on CI while matching on
        # a developer machine, and the message could not say which key moved.
        if checked_in_json != inventory:
            self.fail(
                "platform-page-inventory.json is stale; run "
                f"build_page_inventory. {_describe_drift(checked_in_json, inventory)}"
            )
        self.assertEqual(
            checked_in_markdown,
            inventory_as_markdown(inventory),
            "platform-page-inventory.md is stale; run build_page_inventory",
        )
        self.assertEqual(
            checked_in_components,
            component_catalogue_as_markdown(inventory),
            "platform-component-catalogue.md is stale; run build_page_inventory",
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

        mfi_portal = next(
            page for page in inventory["pages"] if page["route"] == "/mfi-portal"
        )
        self.assertNotIn("ADMIN", mfi_portal["role_access"])
        self.assertEqual(set(mfi_portal["role_access"]), {"MFI_ADMIN", "MFI_OFFICER"})

    def test_every_permission_gated_surface_has_a_role_mapping(self):
        inventory = build_page_inventory()
        missing = [
            page["route"]
            for page in inventory["pages"]
            if page["permission_key"] and not page["role_access"]
        ]
        self.assertEqual(missing, [])

    def test_every_surface_has_the_complete_ui_audit_contract(self):
        inventory = build_page_inventory()
        required = {
            "page_id",
            "module",
            "page_type",
            "shared_layout",
            "header_variant",
            "kpi_count",
            "card_count",
            "tabs",
            "table_pattern",
            "filters",
            "search",
            "typography_exceptions",
            "per_page_css",
            "mobile_status",
            "tablet_status",
            "accessibility_status",
            "theme_status",
            "remediation",
            "fix_status",
            "evidence",
        }
        failures = []
        page_ids = []
        for page in inventory["pages"]:
            page_ids.append(page["page_id"])
            missing = sorted(required - page.keys())
            if missing:
                failures.append((page["route"], missing))
            self.assertIn(page["page_type"], APPROVED_PAGE_TYPES, page["route"])
        self.assertEqual(failures, [])
        self.assertEqual(
            len(page_ids),
            len(set(page_ids)),
            "page audit IDs must be stable and unique",
        )

    def test_every_visual_surface_has_responsive_theme_and_accessibility_contracts(
        self,
    ):
        inventory = build_page_inventory()
        visual = [
            page
            for page in inventory["pages"]
            if page["surface_kind"] != "action" and page["templates"]
        ]
        self.assertTrue(visual)
        for page in visual:
            self.assertEqual(
                page["mobile_status"], "pass-automated-contract", page["route"]
            )
            self.assertEqual(
                page["tablet_status"], "pass-automated-contract", page["route"]
            )
            self.assertEqual(
                page["theme_status"], "pass-automated-contract", page["route"]
            )
            self.assertEqual(
                page["accessibility_status"], "pass-automated-contract", page["route"]
            )

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
