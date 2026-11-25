"""The Go gateway draws Team Targets from the same rules as this application.

Go embeds platform/backend/internal/teamtargets/rules.json. This test fails the
moment one of the activity types, statuses, recommendations, events or labels
it carries changes without the file being exported again (python manage.py
export_team_targets_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.targets.management.commands.export_team_targets_rules import (
    EXPORT_PATH,
    rendered,
)


class TeamTargetsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_team_targets_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Team Targets' page rules changed; run "
            "`python manage.py export_team_targets_rules` so the Go gateway "
            "draws Team Targets the same way.",
        )
