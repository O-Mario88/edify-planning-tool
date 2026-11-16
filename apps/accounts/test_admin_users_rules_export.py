"""The Go gateway builds the User Management page from the
same rules as this application.

Go embeds platform/backend/internal/adminusers/rules.json. This test fails
the moment one of the doors, words or page size it carries changes without
the file being exported again (python manage.py export_admin_users_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.accounts.management.commands.export_admin_users_rules import (
    EXPORT_PATH,
    rendered,
)


class AdminUsersRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_admin_users_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The User Management page's rules changed; run "
            "`python manage.py export_admin_users_rules` so the Go gateway "
            "builds the page the same way.",
        )
