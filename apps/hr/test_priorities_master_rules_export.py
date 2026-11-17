"""The Go gateway draws Uganda Priorities from the same rules as this
application.

Go embeds platform/backend/internal/prioritiesmaster/rules.json. This test
fails the moment the page's doors, who it sends on, whose target column is
their own, a role's Priorities rail or the FY bounds change without the file
being exported again (python manage.py export_priorities_master_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_priorities_master_rules import (
    EXPORT_PATH,
    rendered,
)


class PrioritiesMasterRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_priorities_master_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Uganda Priorities' page rules changed; run "
            "`python manage.py export_priorities_master_rules` so the Go "
            "gateway draws the page the same way.",
        )
