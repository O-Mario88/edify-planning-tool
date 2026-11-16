"""The Go gateway builds My Professional Development from the same rules as this
application.

Go embeds platform/backend/internal/mypd/rules.json. This test
fails the moment one of the doors, words or thresholds it carries changes
without the file being exported again
(python manage.py export_my_pd_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.professional_development.management.commands.export_my_pd_rules import (
    EXPORT_PATH,
    rendered,
)


class MyPDRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_my_pd_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "My Professional Development's rules changed; run "
            "`python manage.py export_my_pd_rules` so the Go "
            "gateway builds the page the same way.",
        )
