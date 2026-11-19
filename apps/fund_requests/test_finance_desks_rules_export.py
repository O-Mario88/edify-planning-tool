"""The Go gateway builds the Accounts desks from the same rules as this
application.

Go embeds platform/backend/internal/financedesks/rules.json. This test fails
the moment a desk's door, a school link or an activity type's words change
without the file being exported again (python manage.py
export_finance_desks_rules).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.management.commands.export_finance_desks_rules import (
    EXPORT_PATH,
    rendered,
)


class FinanceDesksRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_desks_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Accounts desks' rules changed; run "
            "`python manage.py export_finance_desks_rules` so the Go gateway "
            "answers them the same way.",
        )

    def test_the_accountant_opens_every_desk_and_a_field_officer_none(self):
        roles = json.loads(rendered())["roles"]

        self.assertTrue(all(roles["Accountant"]["desks"].values()))
        self.assertFalse(any(roles["CCEO"]["desks"].values()))
