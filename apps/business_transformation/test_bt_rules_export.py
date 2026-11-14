"""The Go gateway builds the Business Transformation pages from the same rules as this application.

Go embeds platform/backend/internal/btportfolio/rules.json. This test fails
the moment one of the doors, roles, labels or limits it carries changes
without the file being exported again (python manage.py
export_bt_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.business_transformation.management.commands.export_bt_rules import (
    EXPORT_PATH,
    rendered,
)


class BTRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_bt_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Business Transformation pages' rules changed; run "
            "`python manage.py export_bt_rules` so the Go gateway "
            "builds the page the same way.",
        )
