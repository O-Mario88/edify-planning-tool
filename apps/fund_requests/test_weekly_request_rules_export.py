"""The Go gateway builds the Weekly Advance Request page from the
same rules as this application.

Go embeds platform/backend/internal/weeklyrequest/rules.json. This test fails
the moment one of the doors, statuses or stage labels it carries changes without
the file being exported again (python manage.py export_weekly_request_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.fund_requests.management.commands.export_weekly_request_rules import (
    EXPORT_PATH,
    rendered,
)


class WeeklyRequestRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_weekly_request_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Weekly Advance Request page's rules changed; run "
            "`python manage.py export_weekly_request_rules` so the Go gateway "
            "builds the page the same way.",
        )
