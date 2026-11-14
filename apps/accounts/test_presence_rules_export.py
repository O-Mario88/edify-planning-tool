"""The Go gateway stamps a person's presence by the same rules as this
application.

Go embeds platform/backend/internal/presence/rules.json. This test fails the
moment one of the untracked paths, read methods, action verbs, thresholds,
lengths or the time zone it carries changes without the file being exported
again (python manage.py export_presence_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.accounts.management.commands.export_presence_rules import (
    EXPORT_PATH,
    rendered,
)


class PresenceRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_presence_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The presence stamp's rules changed; run "
            "`python manage.py export_presence_rules`.",
        )
