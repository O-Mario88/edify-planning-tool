"""The Go gateway builds the IA review pages from the same rules as this application.

Go embeds platform/backend/internal/iapages/rules.json. This test fails the
moment one of the doors, strips or labels it carries changes without
the file being exported again (python manage.py export_ia_pages_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_ia_pages_rules import (
    EXPORT_PATH,
    rendered,
)


class IAPagesRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_ia_pages_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The IA review pages' rules changed; run "
            "`python manage.py export_ia_pages_rules` so the Go gateway "
            "builds the page the same way.",
        )
