"""The Go gateway builds the Today page from the same rules as this
application.

Go embeds platform/backend/internal/todaypage/rules.json. This test fails the
moment who opens Today, its limits, its snooze choices or a decision adapter
changes without the file being exported again
(python manage.py export_today_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.command_center.management.commands.export_today_rules import (
    EXPORT_PATH,
    rendered,
)


class TodayRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_today_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Today page's rules changed; run "
            "`python manage.py export_today_rules` so the Go gateway "
            "builds it the same way.",
        )
