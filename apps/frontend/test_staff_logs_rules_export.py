"""The Go gateway builds the staff logs from the same rules as this
application.

Go embeds platform/backend/internal/stafflogs/rules.json. This test fails the
moment one of the doors, types or statuses it carries changes without the file
being exported again (python manage.py export_staff_logs_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_staff_logs_rules import (
    EXPORT_PATH,
    rendered,
)


class StaffLogsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_staff_logs_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The staff logs' rules changed; run "
            "`python manage.py export_staff_logs_rules` so the Go gateway "
            "builds the pages the same way.",
        )
