"""Security — data-protection/security dashboard posture."""

from __future__ import annotations

from django.conf import settings

from apps.accounts.models import User
from apps.core.crypto import load_field_encryption_key

# Model fields actually stored through apps.core.crypto.encrypt_field.
# Empty today. The crypto module names its intended subjects — NetSuite ids,
# MFA secrets, reset tokens, partner payment metadata — and of those, the
# tokens are already stored as SHA-256 hashes (better than encryption for a
# value that only ever needs comparing) and MFA is not implemented. What
# remains genuinely unprotected at rest is the NetSuite identifiers and the
# partner payment metadata.
ENCRYPTED_FIELDS: tuple[str, ...] = ()


def summary() -> dict:
    """Security posture. Every value here must describe what is true, not what
    was intended — a posture report that overstates a control is worse than no
    report, because it is read as assurance.

    Two flags were renamed for exactly that reason. `fieldEncryptionKeyConfigured`
    used to be `fieldEncryptionConfigured`, which reads as "restricted fields
    are encrypted at rest". They are not: apps.core.crypto provides
    encrypt_field/decrypt_field and no model calls them. What is true is that
    the key is present and valid, which is the precondition, not the control.
    Likewise `mfaImplemented` is stated outright, because `mfaEnabledUsers`
    being zero looks like adoption rather than absence.
    """
    users = User.objects.filter(deleted_at__isnull=True)
    try:
        load_field_encryption_key(getattr(settings, "FIELD_ENCRYPTION_KEY", ""))
        key_configured = True
    except RuntimeError:
        key_configured = False
    return {
        "authzMode": getattr(settings, "AUTHZ_MODE", "shadow"),
        "userCount": users.count(),
        "activeUsers": users.filter(status="active").count(),
        "suspendedUsers": users.filter(status="suspended").count(),
        "mfaEnabledUsers": users.filter(mfa_enabled=True).count(),
        "mfaImplemented": False,
        "fieldEncryptionKeyConfigured": key_configured,
        "encryptedFieldCount": len(ENCRYPTED_FIELDS),
        "emailConfigured": getattr(settings, "EMAIL_PROVIDER", "console") == "resend",
        "isProduction": settings.IS_PRODUCTION,
    }
