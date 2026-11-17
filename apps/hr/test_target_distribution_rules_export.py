"""The Go gateway draws Uganda Target Distribution from the same rules as
this application.

Go embeds platform/backend/internal/targetdistribution/rules.json. This test
fails the moment the page's doors, its import permission, a role's
Priorities rail or the FY bounds change without the file being exported
again (python manage.py export_target_distribution_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.hr.management.commands.export_target_distribution_rules import (
    EXPORT_PATH,
    rendered,
)


class TargetDistributionRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_target_distribution_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Uganda Target Distribution's page rules changed; run "
            "`python manage.py export_target_distribution_rules` so the Go "
            "gateway draws the page the same way.",
        )
