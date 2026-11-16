"""The Go gateway builds the Batch Payments Center from the
same rules as this application.

Go embeds platform/backend/internal/batchpayments/rules.json. This test fails
the moment one of the doors, names or statuses it carries changes without
the file being exported again (python manage.py export_batch_payments_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.management.commands.export_batch_payments_rules import (
    EXPORT_PATH,
    rendered,
)


class BatchPaymentsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_batch_payments_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Batch Payments Center's rules changed; run "
            "`python manage.py export_batch_payments_rules` so the Go gateway "
            "builds the page the same way.",
        )
