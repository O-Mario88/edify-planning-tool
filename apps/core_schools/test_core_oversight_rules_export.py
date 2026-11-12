"""The Go gateway builds Core School Oversight from the same rules as this
application.

Go is to be the application's only backend (owner, 2026-11-11); it embeds
platform/backend/internal/coreoversight/rules.json. This test fails the
moment one of the doors, tabs, readings, statuses or Champion rules it
carries changes without the file being exported again
(python manage.py export_core_oversight_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core_schools.management.commands.export_core_oversight_rules import (
    EXPORT_PATH,
    rendered,
)


class CoreOversightRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_core_oversight_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Core School Oversight's rules changed; run "
            "`python manage.py export_core_oversight_rules` so the Go gateway "
            "builds the page the same way.",
        )
