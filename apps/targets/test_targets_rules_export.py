"""The Go gateway computes targets from the same rules as this application.

Go embeds platform/backend/internal/targets/rules.json. This test fails the
moment one of the area mappings, fallbacks, stages or bands it carries
changes without the file being exported again (python manage.py
export_targets_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.targets.management.commands.export_targets_rules import (
    EXPORT_PATH,
    rendered,
)


class TargetsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_target_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The target engine's rules changed; run "
            "`python manage.py export_targets_rules` so the Go gateway "
            "computes targets the same way.",
        )
