"""The Go gateway builds the notification centre from the same rules as this
application.

Go embeds platform/backend/internal/notificationcenter/rules.json. This test
fails the moment the door, a status, a priority or the page size it carries
changes without the file being exported again (python manage.py
export_notification_center_rules).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from apps.notifications.management.commands.export_notification_center_rules import (
    EXPORT_PATH,
    rendered,
    rules,
)


class NotificationCenterRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_notification_centre_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The notification centre's rules changed; run "
            "`python manage.py export_notification_center_rules` so the Go "
            "gateway builds the page the same way.",
        )

    def test_the_email_rule_is_the_mailers_own(self):
        from apps.core.email import MailerService

        exported = rules()
        env = {
            exported["email_provider_env"]: exported["email_provider"],
            exported["email_key_env"]: "set",
        }
        with mock.patch.dict(os.environ, env):
            self.assertTrue(MailerService().is_configured)
        with mock.patch.dict(os.environ, {**env, exported["email_key_env"]: ""}):
            self.assertFalse(MailerService().is_configured)
        with mock.patch.dict(
            os.environ, {**env, exported["email_provider_env"]: "console"}
        ):
            self.assertFalse(MailerService().is_configured)
