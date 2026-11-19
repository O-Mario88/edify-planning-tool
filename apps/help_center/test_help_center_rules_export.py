"""The Go gateway builds the Knowledge Center from the same rules as this
application.

Go embeds platform/backend/internal/helpcenter/rules.json. This test fails
the moment who opens it, a role guide's address, a synonym or a readable
state changes without the file being exported again
(python manage.py export_help_center_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.help_center.management.commands.export_help_center_rules import (
    EXPORT_PATH,
    rendered,
)


class HelpCenterRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_help_center_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Knowledge Center's rules changed; run "
            "`python manage.py export_help_center_rules` so the Go gateway "
            "builds it the same way.",
        )
