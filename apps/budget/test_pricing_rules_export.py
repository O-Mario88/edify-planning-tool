"""The Go gateway prices stored activities from the same rules as this application.

Go embeds platform/backend/internal/pricing/rules.json. This test fails the
moment one of the roles, profiles, names or limits it
carries changes without the file being exported again (python manage.py
export_pricing_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.budget.management.commands.export_pricing_rules import (
    EXPORT_PATH,
    rendered,
)


class PricingRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_pricing_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The pricing rules changed; run `python manage.py export_pricing_rules` "
            "so the Go gateway prices the same way.",
        )
