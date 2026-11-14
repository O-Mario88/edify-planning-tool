"""The Go gateway builds My Performance from the same rules as this application.

Go embeds platform/backend/internal/myperformance/rules.json. This test fails
the moment one of the doors, strips, buttons or words it carries changes
without the file being exported again (python manage.py
export_my_performance_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_my_performance_rules import (
    EXPORT_PATH,
    rendered,
)


class MyPerformanceRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_my_performance_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "My Performance's rules changed; run `python manage.py export_my_performance_rules` "
            "so the Go gateway builds the page the same way.",
        )
