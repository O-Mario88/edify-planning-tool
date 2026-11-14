"""The Go gateway builds the Measurement Framework from the same rules as this application.

Go embeds platform/backend/internal/iaframework/rules.json. This test fails
the moment one of the doors, roles, labels or limits it carries changes
without the file being exported again (python manage.py
export_ia_framework_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_ia_framework_rules import (
    EXPORT_PATH,
    rendered,
)


class IAFrameworkRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_ia_framework_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Measurement Framework's rules changed; run "
            "`python manage.py export_ia_framework_rules` so the Go gateway "
            "builds the page the same way.",
        )
