"""The Go gateway builds the Personal Time Off page from the
same rules as this application.

Go embeds platform/backend/internal/personaltimeoff/rules.json. This test fails
the moment one of the doors, words or page size it carries changes without
the file being exported again (python manage.py export_personal_time_off_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_personal_time_off_rules import (
    EXPORT_PATH,
    rendered,
)


class PersonalTimeOffRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_personal_time_off_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Personal Time Off page's rules changed; run "
            "`python manage.py export_personal_time_off_rules` so the Go gateway "
            "builds the page the same way.",
        )
