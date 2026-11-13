"""The Go gateway builds the Work Plan page from the same rules as this
application.

Go reads the Work Plan for the app (M4: "Read: My Plan, Work Plan,
calendar"); it embeds platform/backend/internal/workplan/rules.json. This
test fails the moment one of the doors, statuses, labels or holidays it
carries changes without the file being exported again
(python manage.py export_work_plan_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_work_plan_rules import (
    EXPORT_PATH,
    rendered,
)


class WorkPlanRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_work_plan_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Work Plan page's rules changed; run "
            "`python manage.py export_work_plan_rules` so the Go gateway "
            "builds the page the same way.",
        )
