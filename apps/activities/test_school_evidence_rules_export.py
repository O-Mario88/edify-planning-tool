"""The Go gateway builds School Evidence from the same rules as this
application.

Go embeds platform/backend/internal/schoolevidence/rules.json. This test
fails the moment a door, strip, state or label it carries changes without
the file being exported again (python manage.py export_school_evidence_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_school_evidence_rules import (
    EXPORT_PATH,
    rendered,
)


class SchoolEvidenceRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_school_evidence_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "School Evidence's rules changed; run "
            "`python manage.py export_school_evidence_rules` so the Go gateway "
            "builds the page the same way.",
        )
