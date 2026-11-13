"""The Go gateway builds the Staff Activity Log from the same rules as this
application.

Go embeds platform/backend/internal/staffactivity/rules.json. This test fails
the moment one of the doors, roles, meaningful actions, thresholds or labels
it carries changes without the file being exported again
(python manage.py export_staff_activity_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.staff_activity.management.commands.export_staff_activity_rules import (
    EXPORT_PATH,
    rendered,
)


class StaffActivityRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_staff_activity_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Staff Activity Log's rules changed; run "
            "`python manage.py export_staff_activity_rules`.",
        )
