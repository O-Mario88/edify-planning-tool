"""The Go gateway sweeps delegated actions by the same rules as this application.

Go embeds platform/backend/internal/actionsweep/rules.json. This test fails the
moment one of the issue families, states, statuses, types or score bands it
carries changes without the file being exported again
(python manage.py export_action_sweep_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_action_sweep_rules import (
    EXPORT_PATH,
    rendered,
)


class ActionSweepRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_action_sweep_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The delegated-action sweep's rules changed; run "
            "`python manage.py export_action_sweep_rules` so the Go gateway "
            "sweeps actions the same way.",
        )
