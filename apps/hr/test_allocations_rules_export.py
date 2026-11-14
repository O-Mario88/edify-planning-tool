"""The Go gateway reads approved priority contracts by the same rules as this application.

Go embeds platform/backend/internal/allocations/rules.json. This test fails
the moment one of the measurement types, counting bases, statuses or school
families it carries changes without the file being exported again (python
manage.py export_allocations_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_allocations_rules import (
    EXPORT_PATH,
    rendered,
)


class AllocationsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_allocations_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The allocations engine's rules changed; run "
            "`python manage.py export_allocations_rules` so the Go gateway "
            "reads contracts the same way.",
        )
