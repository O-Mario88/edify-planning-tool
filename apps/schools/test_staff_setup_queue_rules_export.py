"""The Go gateway builds the Staff Setup Queue from the same rules as this application.

Go embeds platform/backend/internal/staffsetup/rules.json. This test fails
the moment one of the doors, statuses or limits it carries changes
without the file being exported again (python manage.py
export_staff_setup_queue_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.schools.management.commands.export_staff_setup_queue_rules import (
    EXPORT_PATH,
    rendered,
)


class StaffSetupQueueRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_staff_setup_queue_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Staff Setup Queue's rules changed; run "
            "`python manage.py export_staff_setup_queue_rules` so the Go gateway "
            "builds the page the same way.",
        )
