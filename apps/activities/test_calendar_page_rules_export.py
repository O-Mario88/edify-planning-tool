"""The Go gateway builds the Calendar from the same rules as this application.

Go embeds platform/backend/internal/calendarpage/rules.json. This test fails
the moment one of the doors, vocabularies, holidays or settings it carries
changes without the file being exported again (python manage.py
export_calendar_page_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_calendar_page_rules import (
    EXPORT_PATH,
    rendered,
)


class CalendarPageRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_calendar_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Calendar's rules changed; run "
            "`python manage.py export_calendar_page_rules` so the Go gateway "
            "builds the page the same way.",
        )
