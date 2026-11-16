"""The Go gateway builds the Upload Center from the same rules as this
application.

Go embeds platform/backend/internal/uploadcenter/rules.json. This test fails
the moment one of the doors, actions, permissions or words it carries
changes without the file being exported again
(python manage.py export_upload_center_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.documents.management.commands.export_upload_center_rules import (
    EXPORT_PATH,
    rendered,
)


class UploadCenterRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_upload_center_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Upload Center's rules changed; run "
            "`python manage.py export_upload_center_rules` so the Go gateway "
            "builds the page the same way.",
        )
