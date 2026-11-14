"""The Go gateway builds the Smart Route Planner from the same rules as this application.

Go embeds platform/backend/internal/routeplan/rules.json. This test fails
the moment one of the working-day figures, statuses or doors it carries changes
without the file being exported again (python manage.py
export_route_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.routes.management.commands.export_route_rules import (
    EXPORT_PATH,
    rendered,
)


class RouteRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_route_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Smart Route Planner' rules changed; run "
            "`python manage.py export_route_rules` so the Go gateway "
            "plans the day the same way.",
        )
