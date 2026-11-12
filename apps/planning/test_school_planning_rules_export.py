"""The Go gateway builds the school planning badges from the same rules as
this application.

Go embeds platform/backend/internal/schoolplanning/rules.json. This test
fails the moment one of the statuses, activity types or words it carries
changes without the file being exported again
(python manage.py export_school_planning_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_school_planning_rules import (
    EXPORT_PATH,
    rendered,
)


class SchoolPlanningRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_school_planning_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The school planning rules changed; run "
            "`python manage.py export_school_planning_rules` so the Go gateway "
            "builds the badges the same way.",
        )
