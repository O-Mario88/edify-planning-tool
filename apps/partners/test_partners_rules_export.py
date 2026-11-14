"""The Go gateway builds Partner Activities from the same rules as this application.

Go embeds platform/backend/internal/partnerworkspace/rules.json. This test
fails the moment one of the doors, labels or statuses it carries changes
without the file being exported again (python manage.py
export_partners_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.partners.management.commands.export_partners_rules import (
    EXPORT_PATH,
    rendered,
)


class PartnersRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_partners_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Partner Activities rules changed; run "
            "`python manage.py export_partners_rules` so the Go gateway "
            "builds the page the same way.",
        )
