"""The Go gateway builds the School Directory from the same rules as this
application.

Go owns the School Directory (owner brief, 2026-11-11); it embeds
platform/backend/internal/schooldirectory/rules.json. This test fails the
moment one of the vocabularies or page gates it carries changes without the
file being exported again (python manage.py export_school_directory_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.schools.management.commands.export_school_directory_rules import (
    EXPORT_PATH,
    rendered,
)


class SchoolDirectoryRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_directory_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The School Directory's rules changed; run "
            "`python manage.py export_school_directory_rules` so the Go gateway "
            "builds the directory the same way.",
        )
