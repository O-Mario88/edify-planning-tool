"""The Go gateway answers Home as this application builds it.

Go embeds platform/backend/internal/home/rules.json. This test fails the
moment a role's Quick access, title, plan, Home access, an icon or a figure's
label changes without the file being exported again (python manage.py
export_home_rules).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.command_center.management.commands.export_home_rules import (
    EXPORT_PATH,
    rendered,
)


class HomeRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_home_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Home changed; run `python manage.py export_home_rules` so the Go "
            "gateway answers it the same way.",
        )

    def test_a_planner_keeps_the_four_shortcuts_the_owner_named(self):
        rules = json.loads(rendered())

        for role in ("CCEO", "Program Lead"):
            self.assertEqual(
                [s["label"] for s in rules["roles"][role]["shortcuts"]],
                ["Dashboard", "Clusters", "My Plan", "Calendar"],
            )
