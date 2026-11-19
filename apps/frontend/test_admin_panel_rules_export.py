"""The Go gateway builds the Admin Panel's pages from the same rules as this
application.

Go embeds platform/backend/internal/adminpanel/rules.json. This test fails the
moment a door or a listed rule changes without the file being exported again
(python manage.py export_admin_panel_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_admin_panel_rules import (
    EXPORT_PATH,
    rendered,
)


class AdminPanelRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_admin_panel_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Admin Panel's rules changed; run "
            "`python manage.py export_admin_panel_rules` so the Go gateway "
            "answers them the same way.",
        )
