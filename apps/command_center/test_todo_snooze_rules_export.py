"""The Go gateway snoozes a To-Do by the same rules as this application.

Go embeds platform/backend/internal/todosnooze/rules.json. This test fails the
moment the Today page's gate, the snooze choices, the refusal's words or the
stored lengths change without the file being exported again
(python manage.py export_todo_snooze_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.command_center.management.commands.export_todo_snooze_rules import (
    EXPORT_PATH,
    rendered,
)


class TodoSnoozeRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_snooze_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The To-Do snooze's rules changed; run "
            "`python manage.py export_todo_snooze_rules` so the Go gateway "
            "snoozes the same way.",
        )
