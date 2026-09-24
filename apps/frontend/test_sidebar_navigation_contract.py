from pathlib import Path
from unittest import TestCase

from apps.core.navigation import (
    ICONS,
    SIDEBAR_ITEMS,
    _sidebar_sections_in_display_order,
)


ROOT = Path(__file__).resolve().parents[2]


class SidebarNavigationContractTests(TestCase):
    def test_operational_groups_are_first_in_requested_order(self):
        labels = [
            section["group_label"] for section in _sidebar_sections_in_display_order()
        ]

        self.assertEqual(
            labels[:3],
            ["SCHOOLS & FIELD", "MY WORK", "FINANCE & BUDGET"],
        )
        self.assertEqual(
            set(labels), {section["group_label"] for section in SIDEBAR_ITEMS}
        )

    def test_every_registered_sidebar_destination_has_an_icon(self):
        missing = []
        for section in SIDEBAR_ITEMS:
            for item in section["items"]:
                icon_key = item.get("icon_key", item["page_key"])
                if not ICONS.get(icon_key):
                    missing.append(f"{section['group_label']}: {item['label']}")

        self.assertEqual(missing, [])

    def test_sidebar_icons_are_decorative_because_links_keep_text_labels(self):
        template = (ROOT / "templates/components/sidebar.html").read_text()

        self.assertIn(
            'class="app-sidebar__item-icon" aria-hidden="true"',
            template,
        )
        self.assertIn("{{ item.label }}", template)


class OversightSidebarTests(TestCase):
    def test_oversight_pages_share_one_group_without_duplicate_partner_entry(self):
        from types import SimpleNamespace
        from apps.core.navigation import build_sidebar_for_user, PL, IA, CD, RPL, ADMIN

        for role in (PL, IA, CD, RPL, ADMIN):
            groups = build_sidebar_for_user(
                SimpleNamespace(is_authenticated=True, active_role=role),
                "/partner-oversight/",
            )
            oversight = next(g for g in groups if g["label"] == "OVERSIGHT")
            self.assertTrue(oversight["active"])
            self.assertIn(
                "partner_oversight", [i["page_key"] for i in oversight["items"]]
            )
            links = [i for g in groups for i in g["items"]]
            self.assertEqual(sum(i["url"] == "/partner-oversight/" for i in links), 1)
            self.assertFalse(any(i["url"] == "/partners" for i in links))
            self.assertTrue(
                all(
                    g["label"] == "OVERSIGHT"
                    for g in groups
                    if any(i["page_key"].endswith("_oversight") for i in g["items"])
                )
            )

    def test_cceo_oversees_partners_and_their_project_schools(self):
        """Partner Oversight, and Project Monitoring for the schools they
        added to projects (owner, 2026-09-24: "Users want to see the schools
        they have assigned to the project"). No team or country lens."""
        from types import SimpleNamespace
        from apps.core.navigation import build_sidebar_for_user, PAGE_PERMISSIONS, CCEO

        groups = build_sidebar_for_user(
            SimpleNamespace(is_authenticated=True, active_role=CCEO),
            "/partner-oversight/",
        )
        oversight = next(g for g in groups if g["label"] == "OVERSIGHT")
        self.assertEqual(
            [i["page_key"] for i in oversight["items"]],
            ["partner_oversight", "project_monitoring"],
        )
        self.assertEqual(
            {
                key
                for key, roles in PAGE_PERMISSIONS.items()
                if key.endswith("_oversight") and CCEO in roles
            },
            {"partner_oversight"},
        )
