"""The Go gateway draws Core Schools Planning from the same rules as this
application.

Go embeds platform/backend/internal/coreschools/rules.json. This test fails
the moment the page's doors, page sizes, names or the states its figures
count change without the file being exported again (python manage.py
export_core_schools_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core_schools.management.commands.export_core_schools_rules import (
    EXPORT_PATH,
    rendered,
)


class CoreSchoolsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_core_schools_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Core Schools Planning's page rules changed; run "
            "`python manage.py export_core_schools_rules` so the Go "
            "gateway draws the page the same way.",
        )
