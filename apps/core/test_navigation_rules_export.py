"""The Go gateway answers every role's navigation as this application builds
it.

Go embeds platform/backend/internal/navigation/rules.json. This test fails
the moment a menu, a bar, a label, an icon or a page the app draws changes
without the file being exported again (python manage.py
export_navigation_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.management.commands.export_navigation_rules import (
    EXPORT_PATH,
    rendered,
)


class NavigationRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_every_roles_navigation_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "A role's navigation changed; run "
            "`python manage.py export_navigation_rules` so the Go gateway "
            "answers it the same way.",
        )

    def test_a_partner_team_member_is_offered_less_than_the_partner_admin(self):
        import json

        from apps.partners.member_scope import MEMBER_WITHHELD_PAGES

        rules = json.loads(rendered())
        for role, menu in rules["team_members"].items():
            keys = {i["page_key"] for s in menu["sections"] for i in s["items"]}
            whole = {
                i["page_key"]
                for s in rules["roles"][role]["sections"]
                for i in s["items"]
            }
            self.assertFalse(keys & MEMBER_WITHHELD_PAGES, role)
            self.assertLess(keys, whole, role)

    def test_acting_capacities_withhold_the_substantive_leaders_pages(self):
        import json

        from apps.acting.policy import ACTING_ROLES

        rules = json.loads(rendered())
        self.assertEqual(set(rules["acting"].keys()), set(ACTING_ROLES.keys()))
        for key, entry in ACTING_ROLES.items():
            menu = rules["acting"][key]
            keys = {i["page_key"] for s in menu["sections"] for i in s["items"]}
            bottom_keys = {i["page_key"] for i in menu["bottom"]}
            all_keys = keys | bottom_keys
            whole = {
                i["page_key"]
                for s in rules["roles"][entry.acting_role_value]["sections"]
                for i in s["items"]
            }
            self.assertFalse(all_keys & entry.withheld_pages, key)
            self.assertLess(keys, whole, key)

    def test_school_links_follow_directory_permissions(self):
        from apps.core.management.commands.export_navigation_rules import (
            rules,
            _role_user,
        )
        from apps.core.permissions import RolePermissionService

        for role, menu in rules()["roles"].items():
            items = menu["bottom"] + [
                i for section in menu["sections"] for i in section["items"]
            ]
            if any(i["url"] == "/schools" for i in items):
                self.assertTrue(
                    RolePermissionService.can_view_page(
                        _role_user(role), "school_directory"
                    ),
                    role,
                )
