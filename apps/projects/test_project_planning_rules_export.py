"""The Go gateway builds the Special Projects Planning from the
same rules as this application.

Go embeds platform/backend/internal/projectplanning/rules.json. This test fails
the moment one of the doors, names or statuses it carries changes without
the file being exported again (python manage.py export_project_planning_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.projects.management.commands.export_project_planning_rules import (
    EXPORT_PATH,
    rendered,
)


class ProjectPlanningRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_project_planning_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Special Projects Planning's rules changed; run "
            "`python manage.py export_project_planning_rules` so the Go gateway "
            "builds the page the same way.",
        )
