"""The Go gateway builds Fund Approvals from the same rules as this
application.

Go embeds platform/backend/internal/fundapprovals/rules.json. This test
fails the moment one of the doors, statuses, hints or words it carries
changes without the file being exported again
(python manage.py export_fund_approvals_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.management.commands.export_fund_approvals_rules import (
    EXPORT_PATH,
    rendered,
)


class FundApprovalsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_fund_approvals_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Fund Approvals page's rules changed; run "
            "`python manage.py export_fund_approvals_rules` so the Go "
            "gateway builds the page the same way.",
        )
