"""Go's Platform Health opens to the same roles as System Health.

Go embeds platform/backend/internal/platformhealth/rules.json. This test fails
the moment the roles that may open System Health change without the file
being exported again (python manage.py export_platform_health_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.system_health.management.commands.export_platform_health_rules import (
    EXPORT_PATH,
    rendered,
)


class PlatformHealthRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_platform_health_door_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "System Health's roles changed; run `python manage.py export_platform_health_rules` "
            "so Go's Platform Health opens to the same people.",
        )
