"""The Go gateway builds the Fund Disbursement Dashboard from the same rules
as this application.

Go embeds platform/backend/internal/disbursements/rules.json. This test
fails the moment one of the doors, statuses or words it carries changes
without the file being exported again
(python manage.py export_disbursements_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.management.commands.export_disbursements_rules import (
    EXPORT_PATH,
    rendered,
)


class DisbursementsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_disbursements_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Disbursements page's rules changed; run "
            "`python manage.py export_disbursements_rules` so the Go "
            "gateway builds the page the same way.",
        )
