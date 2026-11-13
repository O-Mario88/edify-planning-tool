"""The Go gateway builds the Team Performance page from the same rules as this
application.

Go embeds platform/backend/internal/teamperformance/rules.json. This test
fails the moment one of the doors, statuses, measures or labels it carries
changes without the file being exported again (python manage.py
export_team_performance_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_team_performance_rules import (
    EXPORT_PATH,
    rendered,
)


class TeamPerformanceRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_team_performance_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Team Performance page's rules changed; run "
            "`python manage.py export_team_performance_rules` so the Go gateway "
            "builds the page the same way.",
        )
