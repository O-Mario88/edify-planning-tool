"""The Go gateway prices a day from the same rules as this application.

Go embeds platform/backend/internal/costing/daypool/rules.json and checks
itself against vectors.json. This test fails the moment one of the rates a
day fetches, the roles behind them, or the answers of the functions that
apply them changes without the files being exported again
(python manage.py export_daypool_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.budget.management.commands.export_daypool_rules import (
    RULES_PATH,
    VECTORS_PATH,
    rendered_rules,
    rendered_vectors,
)


class DayPoolRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_day_costing_rules_is_current(self):
        for path, current in (
            (RULES_PATH, rendered_rules()),
            (VECTORS_PATH, rendered_vectors()),
        ):
            with self.subTest(path=str(path)):
                exported = (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")
                self.assertEqual(
                    exported,
                    current,
                    "A day's costing rules changed; run "
                    "`python manage.py export_daypool_rules` so the Go gateway "
                    "prices the same way.",
                )
