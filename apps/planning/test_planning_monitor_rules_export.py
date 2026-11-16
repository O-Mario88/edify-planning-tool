"""The Go gateway builds the Planning Monitor from the same rules as this
application.

Go embeds platform/backend/internal/planningmonitor/rules.json. This test
fails the moment one of the types, states, kinds, targets, gaps or ledger
lines it carries changes without the file being exported again
(python manage.py export_planning_monitor_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_planning_monitor_rules import (
    EXPORT_PATH,
    rendered,
)


class PlanningMonitorRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_planning_monitor_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Planning Monitor's rules changed; run "
            "`python manage.py export_planning_monitor_rules` so the Go gateway "
            "builds the monitor the same way.",
        )
