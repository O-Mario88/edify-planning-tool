"""The Go gateway builds the Decision Log from the same rules as this
application.

Go embeds platform/backend/internal/decisionlog/rules.json. This test fails
the moment one of the doors, groups, labels or sizes it carries changes
without the file being exported again (python manage.py
export_decision_log_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.audit.management.commands.export_decision_log_rules import (
    EXPORT_PATH,
    rendered,
)


class DecisionLogRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_decision_log_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Decision Log's rules changed; run "
            "`python manage.py export_decision_log_rules` so the Go gateway "
            "builds the page the same way.",
        )
