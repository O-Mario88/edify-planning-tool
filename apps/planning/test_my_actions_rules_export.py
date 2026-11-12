"""The Go gateway builds My Actions from the same rules as this application.

Go embeds platform/backend/internal/myactions/rules.json. This test fails the
moment one of the doors, tabs, labels or limits it carries changes without
the file being exported again (python manage.py export_my_actions_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_my_actions_rules import (
    EXPORT_PATH,
    rendered,
)


class MyActionsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_my_actions_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The My Actions page's rules changed; run "
            "`python manage.py export_my_actions_rules` so the Go gateway "
            "builds the page the same way.",
        )
