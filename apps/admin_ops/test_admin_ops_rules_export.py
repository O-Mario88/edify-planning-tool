"""The Go gateway builds the platform-operations registers from the same rules as this application.

Go embeds platform/backend/internal/adminops/rules.json. This test fails
the moment one of the doors, labels or limits it carries changes
without the file being exported again (python manage.py
export_admin_ops_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.admin_ops.management.commands.export_admin_ops_rules import (
    EXPORT_PATH,
    rendered,
)


class AdminOpsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_admin_ops_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The platform-operations registers' rules changed; run "
            "`python manage.py export_admin_ops_rules` so the Go gateway "
            "builds the page the same way.",
        )
