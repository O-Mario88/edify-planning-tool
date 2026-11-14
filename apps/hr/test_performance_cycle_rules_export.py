"""The Go gateway builds the Performance Cycle Console from the same rules as this application.

Go embeds platform/backend/internal/perfcycle/rules.json. This test fails
the moment one of the doors, roles, labels or limits it carries changes
without the file being exported again (python manage.py
export_performance_cycle_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_performance_cycle_rules import (
    EXPORT_PATH,
    rendered,
)


class PerformanceCycleRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_performance_cycle_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Performance Cycle Console's rules changed; run "
            "`python manage.py export_performance_cycle_rules` so the Go gateway "
            "builds the page the same way.",
        )
