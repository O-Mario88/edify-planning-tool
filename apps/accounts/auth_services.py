"""
Auth + token-lifecycle services — ports of auth.service.ts and
auth-tokens.service.ts.

  • login        — per-account brute-force lockout, status gate, bcrypt compare,
                   generic errors (no enumeration), issues access + refresh pair.
  • refresh      — validates + revokes the consumed refresh token, issues a new pair.
  • logout       — revokes a refresh token.
  • forgot/reset — single-use hashed reset token, email via the MailerService.
  • validateInvite / setPassword — invitation lifecycle.

Token storage rule: the DB holds ONLY the SHA-256 hash. The raw token is
returned to the caller exactly once.
"""

from __future__ import annotations


from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.email import mailer
from apps.core.exceptions import BadRequest, Forbidden, Unauthorized
from apps.core.rbac import permissions_for_role
from apps.core.security import (
    expiry_from_now,
    generate_token,
    hash_token,
    validate_password,
)

from .jwt import issue_token_pair
from .models import RefreshToken, User, UserInvitation


# Lockout knobs previously lived here as _max_failed()/_lock_minutes() with
# fallback defaults (5, 15) that silently disagreed with the OTHER login
# path's fallbacks (10, 15) -- exactly the inconsistency Issue 3 fixed.
# Removed: all lockout policy now lives in
# apps.accounts.lockout_service.AuthenticationLockoutService, the one
# canonical place, read via django.contrib.auth.authenticate() below.


def _reset_ttl_minutes() -> int:
    return getattr(settings, "PASSWORD_RESET_TOKEN_TTL_MINUTES", 45)


def _invite_ttl_days() -> int:
    return getattr(settings, "INVITE_TOKEN_TTL_DAYS", 7)


# ── Login ────────────────────────────────────────────────────────────────────
def login(email: str, password: str, requested_active_role: str | None = None) -> dict:
    """Authenticate + issue a token pair. ONE authentication call
    (django.contrib.auth.authenticate(), via AUTHENTICATION_BACKENDS =
    LockoutEnforcingModelBackend) — the exact same call the web session
    login path makes, so lockout/lifecycle/password logic lives in exactly
    one place instead of being reimplemented per login surface. Generic
    errors throughout to avoid user enumeration."""
    from django.contrib.auth import authenticate

    from apps.accounts.lockout_service import AuthenticationLockoutService

    email = (email or "").lower().strip()
    existing = User.objects.filter(email=email, deleted_at__isnull=True).first()

    # Locked? Reject before checking the password (don't reset the clock).
    # authenticate() re-checks this itself; this pre-check exists only to
    # give a more specific error message (locked vs. wrong credentials) —
    # it is not itself the security gate.
    if existing:
        state = AuthenticationLockoutService.check_lockout(existing)
        if state.locked:
            raise Forbidden(
                "Account is temporarily locked due to repeated failed sign-ins. "
                "Try again later."
            )

    user = authenticate(email=email, password=password)
    if user is None:
        # Generic error either way to avoid user enumeration.
        raise Unauthorized("Invalid credentials")

    user = User.objects.select_related("staff_profile").get(id=user.id)

    active_role = (
        requested_active_role
        if requested_active_role and requested_active_role in (user.roles or [])
        else user.active_role
    )

    tokens = issue_token_pair(user.id, active_role)
    staff_profile_id = _staff_profile_id(user)
    return {
        **tokens,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "roles": list(user.roles or []),
            "activeRole": active_role,
            "permissions": permissions_for_role(active_role),
            "staffProfileId": staff_profile_id,
        },
    }


def _staff_profile_id(user) -> str | None:
    """Safely read the (optional) staff profile id. The reverse OneToOne
    accessor raises RelatedObjectDoesNotExist when there's no related row, so
    guard it explicitly."""
    try:
        sp = user.staff_profile
        return sp.id if sp else None
    except Exception:  # noqa: BLE001
        return None


# ── Refresh + logout ─────────────────────────────────────────────────────────
def refresh(refresh_token: str) -> dict:
    """Validate a refresh token, revoke it (single-use), and issue a fresh pair."""
    token_hash = hash_token(refresh_token or "")
    record = (
        RefreshToken.objects.select_related("user")
        .filter(
            token_hash=token_hash,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if not record or not record.user or record.user.status != "active":
        raise Unauthorized("Invalid or expired refresh token.")
    # Revoke the consumed token.
    record.revoked_at = timezone.now()
    record.save(update_fields=["revoked_at"])
    return issue_token_pair(record.user_id, record.user.active_role)


def logout(refresh_token: str | None) -> dict:
    """Revoke a refresh token (logout). The access JWT expires on its own (15m)."""
    if not refresh_token:
        return {"ok": True}
    token_hash = hash_token(refresh_token)
    RefreshToken.objects.filter(token_hash=token_hash, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    return {"ok": True}


# ── Forgot / reset password ──────────────────────────────────────────────────
def forgot_password(email: str) -> dict:
    """If the email exists, generate a single-use reset token + email it. Always
    returns the same generic response (no user enumeration)."""
    user = User.objects.filter(
        email=(email or "").lower().strip(), deleted_at__isnull=True
    ).first()
    if not user:
        return {"ok": True}  # generic — don't reveal existence

    raw_token = generate_token()
    user.password_reset_token_hash = hash_token(raw_token)
    user.password_reset_expires = expiry_from_now(_reset_ttl_minutes())
    user.save(update_fields=["password_reset_token_hash", "password_reset_expires"])

    # Email delivery (console in dev, Resend in prod). We surface the dev token
    # so the flow is testable without an email provider.
    result = mailer.send_password_reset(to=user.email, name=user.name, token=raw_token)
    dev_reset_token = raw_token if not settings.IS_PRODUCTION else None
    response = {"ok": True}
    if dev_reset_token:
        response["devResetToken"] = dev_reset_token
    if result.get("devPreview"):
        response["devPreview"] = result["devPreview"]
    return response


def reset_password(token: str, new_password: str, confirm: str) -> dict:
    """Consume a reset token + set a new password. Single-use; validates policy."""
    if new_password != confirm:
        raise BadRequest("Passwords do not match.")
    violations = validate_password(new_password)
    if violations:
        raise BadRequest(" ".join(violations))

    user = _find_user_by_reset_token(token)
    if not user:
        raise BadRequest("This reset link is invalid or has expired.")

    user.set_password(new_password)
    user.password_reset_token_hash = None
    user.password_reset_expires = None
    user.password_set_at = timezone.now()
    with transaction.atomic():
        user.save(
            update_fields=[
                "password",
                "password_reset_token_hash",
                "password_reset_expires",
                "password_set_at",
            ]
        )
        # Revoke all refresh tokens — forces a fresh login everywhere.
        RefreshToken.objects.filter(user_id=user.id, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    return {"ok": True}


def _find_user_by_reset_token(token: str) -> User | None:
    token_hash = hash_token(token or "")
    user = User.objects.filter(
        password_reset_token_hash=token_hash, deleted_at__isnull=True
    ).first()
    if not user:
        return None
    if not user.password_reset_expires or user.password_reset_expires < timezone.now():
        return None
    return user


# ── Invitation: validate + set-password ──────────────────────────────────────
def validate_invite(token: str) -> dict:
    """Validate an invite token WITHOUT consuming it. Returns the user's name +
    email so the set-password page can render a personalised greeting."""
    invitation = _find_invitation(token)
    if not invitation:
        return {"valid": False, "reason": "invalid"}
    if invitation.revoked_at:
        return {"valid": False, "reason": "revoked"}
    if invitation.accepted_at:
        return {"valid": False, "reason": "used"}
    if invitation.expires_at < timezone.now():
        return {"valid": False, "reason": "expired"}
    return {"valid": True, "email": invitation.user.email, "name": invitation.user.name}


def set_password(token: str, new_password: str, confirm: str) -> dict:
    """Consume an invite token + set the user's first password + activate.
    Single-use: marks the invitation accepted."""
    if new_password != confirm:
        raise BadRequest("Passwords do not match.")
    invitation = _find_invitation(token)
    if not invitation:
        raise BadRequest("This invitation link is invalid.")
    if invitation.revoked_at:
        raise BadRequest("This invitation has been revoked.")
    if invitation.accepted_at:
        raise BadRequest("This invitation has already been used.")
    if invitation.expires_at < timezone.now():
        raise BadRequest("This invitation has expired.")

    violations = validate_password(new_password, invitation.user.email)
    if violations:
        raise BadRequest(" ".join(violations))

    user = invitation.user
    user.set_password(new_password)
    user.password_set_at = timezone.now()
    user.status = "active"
    user.is_active = True
    invitation.accepted_at = timezone.now()
    with transaction.atomic():
        user.save(update_fields=["password", "password_set_at", "status", "is_active"])
        invitation.save(update_fields=["accepted_at"])
    return {"ok": True}


def _find_invitation(token: str) -> UserInvitation | None:
    token_hash = hash_token(token or "")
    return (
        UserInvitation.objects.select_related("user")
        .filter(token_hash=token_hash)
        .first()
    )


__all__ = [
    "login",
    "refresh",
    "logout",
    "forgot_password",
    "reset_password",
    "validate_invite",
    "set_password",
]
