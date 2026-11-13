"""The Go gateway builds Project Monitoring from the same rules as this
application.

Go embeds platform/backend/internal/projectmonitoring/rules.json. This test
fails the moment one of the doors, words or thresholds it carries changes
without the file being exported again
(python manage.py export_project_monitoring_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.projects.management.commands.export_project_monitoring_rules import (
    EXPORT_PATH,
    rendered,
)


class ProjectMonitoringRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_project_monitoring_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Project Monitoring's rules changed; run "
            "`python manage.py export_project_monitoring_rules` so the Go "
            "gateway builds the page the same way.",
        )
