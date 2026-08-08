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
                    missing.append(f'{section["group_label"]}: {item["label"]}')

        self.assertEqual(missing, [])

    def test_sidebar_icons_are_decorative_because_links_keep_text_labels(self):
        template = (ROOT / "templates/components/sidebar.html").read_text()

        self.assertIn(
            'class="app-sidebar__item-icon" aria-hidden="true"',
            template,
        )
        self.assertIn("{{ item.label }}", template)
