"""The Go gateway builds the Messages inbox from the same rules as this
application.

It embeds platform/backend/internal/messaging/rules.json. This test fails the
moment one of the tabs, record kinds, role rules or labels it carries changes
without the file being exported again (python manage.py
export_messaging_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.messaging.management.commands.export_messaging_rules import (
    EXPORT_PATH,
    rendered,
)


class MessagingRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_messaging_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Messages inbox's rules changed; run "
            "`python manage.py export_messaging_rules` so the Go gateway "
            "builds the inbox the same way.",
        )
