"""The Go gateway builds Completion Reviews from the same rules as this application.

Go embeds platform/backend/internal/plreview/rules.json. This test fails
the moment one of the doors, roles, labels or limits it carries changes
without the file being exported again (python manage.py
export_completion_reviews_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.management.commands.export_completion_reviews_rules import (
    EXPORT_PATH,
    rendered,
)


class CompletionReviewsRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_completion_reviews_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Completion Reviews page's rules changed; run "
            "`python manage.py export_completion_reviews_rules` so the Go gateway "
            "builds the page the same way.",
        )
