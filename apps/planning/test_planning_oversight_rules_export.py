"""The Go gateway opens Planning Oversight and Country Oversight by the same
doors as this application.

Go is to be the application's only backend (owner, 2026-11-11); it embeds
platform/backend/internal/planningoversight/rules.json. This test fails the
moment a page gate or the feed's page list changes without the file being
exported again (python manage.py export_planning_oversight_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_planning_oversight_rules import (
    EXPORT_PATH,
    rendered,
)


class PlanningOversightRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_planning_oversight_doors_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Planning Oversight's doors changed; run "
            "`python manage.py export_planning_oversight_rules` so the Go "
            "gateway opens the pages the same way.",
        )
