"""The Go gateway builds the partner's Assigned Schools and Activities from the same rules as this application.

Go embeds platform/backend/internal/partnerassigned/rules.json. This test fails
the moment one of the doors, labels or limits it carries changes
without the file being exported again (python manage.py
export_partner_assigned_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.partners.management.commands.export_partner_assigned_rules import (
    EXPORT_PATH,
    rendered,
)


class PartnerAssignedRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_partner_assigned_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The partner's Assigned Schools and Activities rules changed; run "
            "`python manage.py export_partner_assigned_rules` so the Go gateway "
            "builds the page the same way.",
        )
