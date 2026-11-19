"""The Go gateway builds the finance overviews from the same rules as this
application.

Go embeds platform/backend/internal/financedesks/overviews.json. This test
fails the moment a door, a status list or a status's words change without the
file being exported again (python manage.py export_finance_overviews_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.budget.management.commands.export_finance_overviews_rules import (
    EXPORT_PATH,
    rendered,
)


class FinanceOverviewsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_overviews_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The finance overviews' rules changed; run "
            "`python manage.py export_finance_overviews_rules` so the Go gateway "
            "answers them the same way.",
        )
