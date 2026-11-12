"""The Go gateway builds the Closed Schools page from the same rules as this
application.

Go embeds platform/backend/internal/closedschools/rules.json. This test fails
the moment one of the doors, words or sizes it carries changes without the
file being exported again (python manage.py export_closed_schools_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.schools.management.commands.export_closed_schools_rules import (
    EXPORT_PATH,
    rendered,
)


class ClosedSchoolsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_closed_schools_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Closed Schools page's rules changed; run "
            "`python manage.py export_closed_schools_rules` so the Go gateway "
            "builds the page the same way.",
        )
