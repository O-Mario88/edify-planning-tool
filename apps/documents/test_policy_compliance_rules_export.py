"""The Go gateway builds Policy Compliance from the same rules as this application.

Go embeds platform/backend/internal/policycompliance/rules.json. This test fails
the moment one of the doors, strips, labels or limits it carries changes
without the file being exported again (python manage.py
export_policy_compliance_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.documents.management.commands.export_policy_compliance_rules import (
    EXPORT_PATH,
    rendered,
)


class PolicyComplianceRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_policy_compliance_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Policy Compliance page's rules changed; run "
            "`python manage.py export_policy_compliance_rules` so the Go gateway "
            "builds the page the same way.",
        )
