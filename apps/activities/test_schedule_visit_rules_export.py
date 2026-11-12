"""The Go gateway schedules a school visit from the same rules as this
application.

Go embeds platform/backend/internal/activities/rules.json. This test fails
the moment one of the doors, words or constants it carries changes without
the file being exported again (python manage.py export_schedule_visit_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_schedule_visit_rules import (
    EXPORT_PATH,
    rendered,
)


class ScheduleVisitRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_visit_save_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The school-visit save's rules changed; run "
            "`python manage.py export_schedule_visit_rules` so the Go gateway "
            "saves the same way.",
        )
