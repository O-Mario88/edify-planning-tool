"""The Go gateway builds the Visit Requests page from the same rules as this
application.

Go embeds platform/backend/internal/visitrequests/rules.json. This test fails
the moment one of the doors it carries changes without the file being
exported again (python manage.py export_visit_requests_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_visit_requests_rules import (
    EXPORT_PATH,
    rendered,
)


class VisitRequestsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_visit_requests_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Visit Requests page's rules changed; run "
            "`python manage.py export_visit_requests_rules` so the Go gateway "
            "builds the page the same way.",
        )
