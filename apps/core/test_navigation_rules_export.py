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
