"""The Go gateway builds the HR registers from the same rules as this application.

Go embeds platform/backend/internal/hrregister/rules.json. This test fails the
moment one of the doors, strips, buttons or labels it carries changes without
the file being exported again (python manage.py export_hr_register_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_hr_register_rules import (
    EXPORT_PATH,
    rendered,
)


class HRRegisterRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_hr_register_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The HR registers' rules changed; run "
            "`python manage.py export_hr_register_rules` so the Go gateway "
            "builds the page the same way.",
        )
