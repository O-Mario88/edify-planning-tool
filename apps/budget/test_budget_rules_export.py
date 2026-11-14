"""The Go gateway builds Budget from the same rules as this application.

Go embeds platform/backend/internal/budgetpage/rules.json. This test fails the
moment one of the roles, profiles, names or limits it
carries changes without the file being exported again (python manage.py
export_budget_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.budget.management.commands.export_budget_rules import (
    EXPORT_PATH,
    rendered,
)


class BudgetRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_budget_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Budget page's rules changed; run `python manage.py export_budget_rules` "
            "so the Go gateway builds the page the same way.",
        )
