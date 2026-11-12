"""The Go gateway builds the Planning page from the same rules as this
application.

Go embeds platform/backend/internal/planningpage/rules.json. This test
fails the moment one of the statuses, activity types or words it carries
changes without the file being exported again
(python manage.py export_planning_page_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_planning_page_rules import (
    EXPORT_PATH,
    rendered,
)


class PlanningPageRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_planning_page_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Planning page's rules changed; run "
            "`python manage.py export_planning_page_rules` so the Go gateway "
            "builds the page the same way.",
        )
