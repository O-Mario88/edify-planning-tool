"""Security — data-protection/security dashboard posture."""
from __future__ import annotations

from django.conf import settings

from apps.accounts.models import User


def summary() -> dict:
    users = User.objects.filter(deleted_at__isnull=True)
    return {
        "authzMode": getattr(settings, "AUTHZ_MODE", "shadow"),
        "userCount": users.count(),
        "activeUsers": users.filter(status="active").count(),
        "suspendedUsers": users.filter(status="suspended").count(),
        "mfaEnabledUsers": users.filter(mfa_enabled=True).count(),
        "fieldEncryptionConfigured": bool(getattr(settings, "FIELD_ENCRYPTION_KEY", "")),
        "emailConfigured": getattr(settings, "EMAIL_PROVIDER", "console") == "resend",
        "isProduction": settings.IS_PRODUCTION,
    }
