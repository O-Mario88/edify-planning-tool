"""The Go gateway builds the Training Summary from the same rules as this
application.

Go embeds platform/backend/internal/trainingsummary/rules.json. This test
fails the moment one of the gates, statuses, activity types or words it
carries changes without the file being exported again
(python manage.py export_training_summary_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.planning.management.commands.export_training_summary_rules import (
    EXPORT_PATH,
    rendered,
)


class TrainingSummaryRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_training_summary_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Training Summary's rules changed; run "
            "`python manage.py export_training_summary_rules` so the Go gateway "
            "builds the page the same way.",
        )
