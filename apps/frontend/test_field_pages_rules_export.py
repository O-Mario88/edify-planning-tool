"""The Go gateway builds the School Map and the empty Search page from the
same rules as this application.

Go embeds platform/backend/internal/fieldpages/rules.json. This test fails the
moment a door changes without the file being exported again (python manage.py
export_field_pages_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_field_pages_rules import (
    EXPORT_PATH,
    rendered,
)


class FieldPagesRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_field_pages_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The field pages' rules changed; run "
            "`python manage.py export_field_pages_rules` so the Go gateway "
            "answers them the same way.",
        )
