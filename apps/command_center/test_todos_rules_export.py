"""The Go gateway builds the To-Do page from the same rules as this application.

Go embeds platform/backend/internal/todos/rules.json, and its tests read the
next-action cases beside it. This test fails the moment a door, a builder a
role reaches, a link's gate, a vocabulary or a next action changes without
the files being exported again (python manage.py export_todos_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.command_center.management.commands.export_todos_rules import (
    CASES_PATH,
    EXPORT_PATH,
    rendered,
    rendered_cases,
)

STALE = (
    "The To-Do page's rules changed; run `python manage.py export_todos_rules` "
    "so the Go gateway builds the page the same way (or passes the role on)."
)


class TodosRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_todo_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(exported, rendered(), STALE)

    def test_the_gateways_next_action_cases_are_current(self):
        exported = (Path(settings.BASE_DIR) / CASES_PATH).read_text(encoding="utf-8")

        self.assertEqual(exported, rendered_cases(), STALE)
