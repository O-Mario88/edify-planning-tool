from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.frontend.management.commands.export_programme_rollout_rules import (
    EXPORT_PATH,
    rendered,
)


class ProgrammeRolloutRulesExportTest(SimpleTestCase):
    """The Go gateway draws Programme Rollout from the exported rules; this
    fails when the page's rules change and the file was not exported again."""

    def test_the_exported_rules_are_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")
        self.assertEqual(
            exported,
            rendered(),
            "Run `python manage.py export_programme_rollout_rules`.",
        )
