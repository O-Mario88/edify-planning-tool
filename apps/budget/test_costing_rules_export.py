"""The Go gateway prices activities from the same rules as this application.

Go embeds platform/backend/internal/costing/rules.json. This test fails the
moment one of the rates, labels, aliases, day keys or activity types it
carries changes without the file being exported again (python manage.py
export_costing_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.budget.management.commands.export_costing_rules import (
    EXPORT_PATH,
    rendered,
)


class CostingRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_costing_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The costing engine's rules changed; run `python manage.py export_costing_rules` "
            "so the Go gateway prices activities the same way.",
        )
