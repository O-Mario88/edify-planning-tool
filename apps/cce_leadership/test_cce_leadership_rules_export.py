"""The Go gateway builds the CCE leadership registers from the same rules as this application.

Go embeds platform/backend/internal/ccelead/rules.json. This test fails the
moment one of the doors, strips or labels it carries changes without
the file being exported again (python manage.py export_cce_leadership_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.cce_leadership.management.commands.export_cce_leadership_rules import (
    EXPORT_PATH,
    rendered,
)


class CceLeadershipRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_cce_leadership_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The CCE leadership registers' rules changed; run "
            "`python manage.py export_cce_leadership_rules` so the Go gateway "
            "builds the page the same way.",
        )
