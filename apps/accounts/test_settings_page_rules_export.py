"""The Go gateway reads the Settings page from the same rules as this
application.

Go embeds platform/backend/internal/settingspage/rules.json. This test fails
the moment the door, the session length setting, the SMS provider or the
page's words for an unavailable channel change without the file being
exported again (python manage.py export_settings_page_rules).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase

from apps.accounts.management.commands.export_settings_page_rules import (
    EXPORT_PATH,
    SESSION_IDLE_DEFAULT_SECONDS,
    rendered,
    rules,
)
from apps.accounts.models import User


class SettingsPageRulesExportTest(TestCase):
    def test_the_gateways_copy_of_the_settings_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")
        self.assertEqual(
            exported,
            rendered(),
            "The Settings page's rules changed; run "
            "`python manage.py export_settings_page_rules` so the Go gateway "
            "reads the page the same way.",
        )

    def test_the_default_session_is_the_settings_own(self):
        # SESSION_COOKIE_AGE when SESSION_IDLE_TIMEOUT_SECONDS is unset.
        self.assertEqual(SESSION_IDLE_DEFAULT_SECONDS, 30 * 60)

    def test_the_unavailable_channel_words_are_enrolment_states_own(self):
        from apps.accounts.mfa_service import enrolment_state

        exported = rules()
        user = User.objects.create(email="ann@settings.test", name="Ann", phone="")
        environ = {k: v for k, v in os.environ.items() if k != "SMS_PROVIDER"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(
                enrolment_state(user)["mfa_sms_blocked_reason"],
                exported["sms_needs_phone"],
            )
            user.phone = "+256700000001"
            self.assertEqual(
                enrolment_state(user)["mfa_sms_blocked_reason"],
                exported["sms_not_configured"],
            )
