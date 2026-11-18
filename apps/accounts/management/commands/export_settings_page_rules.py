"""Write the Settings page's rules for the Go gateway.

Go reads the Settings page (/settings, apps.frontend.views.extended_views.
settings_view, pages/settings/index.html and apps.accounts.mfa_service.
enrolment_state) from what this command writes to
platform/backend/internal/settingspage/rules.json: who may open the page,
the environment setting that sets how long an idle session lasts and its
default, the SMS provider and settings that make text messages available, and the words
the page uses for a channel it cannot offer. A change to any of them must
be exported again; apps/accounts/test_settings_page_rules_export.py fails
until it is.

Who must use two-step verification (MFA_REQUIRED_FOR_ALL, MFA_REQUIRED_ROLES)
is not restated: Go's sign-in reads the same switches (EDIFY_MFA_REQUIRED_*).

    python manage.py export_settings_page_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/settingspage/rules.json")

#: The page's permission (require_page_permission on the view).
PAGE_PERMISSION = "settings"

#: config/settings/base.py: SESSION_COOKIE_AGE reads this, in seconds.
SESSION_IDLE_ENV = "SESSION_IDLE_TIMEOUT_SECONDS"
SESSION_IDLE_DEFAULT_SECONDS = 30 * 60

#: apps.core.sms.SmsService.is_configured: text messages can be sent when
#: this provider is chosen and both its settings are present.
SMS_PROVIDER = "africastalking"
SMS_PROVIDER_ENV = "SMS_PROVIDER"
SMS_REQUIRED_ENVS = ("SMS_API_KEY", "SMS_USERNAME")


def roles() -> dict:
    """Whether each role opens the page, by the page's own gate."""
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole

    return {
        role.value: {
            "page": RolePermissionService.can_view_page(
                _role_user(role.value), PAGE_PERMISSION
            )
        }
        for role in EdifyRole
    }


def rules() -> dict:
    from apps.accounts import mfa_service

    return {
        "roles": roles(),
        "session_idle_env": SESSION_IDLE_ENV,
        "session_idle_default_seconds": SESSION_IDLE_DEFAULT_SECONDS,
        "sms_provider": SMS_PROVIDER,
        "sms_provider_env": SMS_PROVIDER_ENV,
        "sms_required_envs": list(SMS_REQUIRED_ENVS),
        "channels": {
            "email": mfa_service.EMAIL_CHANNEL,
            "sms": mfa_service.SMS_CHANNEL,
            "app": mfa_service.APP_CHANNEL,
        },
        # enrolment_state's mfa_sms_blocked_reason, word for word.
        "sms_needs_phone": "Add a phone number to your profile to receive codes by text.",
        "sms_not_configured": "Text messaging is not configured on this deployment. "
        "Your administrator can enable it.",
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Settings page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
