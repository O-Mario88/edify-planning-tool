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
from apps.core.exceptions import BadRequest, Unauthorized
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

    from apps.accounts.auth_failure_service import AuthenticationFailureService
    from apps.accounts.lockout_service import AuthenticationLockoutService

    email = (email or "").lower().strip()
    existing = User.objects.filter(email=email, deleted_at__isnull=True).first()

    # Locked? Reject before checking the password (don't reset the clock).
    # authenticate() re-checks this itself; this pre-check exists only so a
    # locked account never even reaches the password compare. The PUBLIC
    # response is identical to every other rejection (SEC-02) — only the
    # audit log records the real reason.
    if existing:
        state = AuthenticationLockoutService.check_lockout(existing)
        if state.locked:
            message = AuthenticationFailureService.reject(
                email=email,
                user=existing,
                reason="account_locked_escalated"
                if state.escalated
                else "account_locked",
            )
            raise Unauthorized(message)

    user = authenticate(email=email, password=password)
    if user is None:
        # Same status code + message regardless of cause — unknown email,
        # wrong password, or inactive/suspended status must be externally
        # indistinguishable (SEC-02).
        message = AuthenticationFailureService.reject(
            email=email,
            user=existing,
            reason="invalid_password" if existing else "unknown_email",
        )
        raise Unauthorized(message)

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
def _revoke_family(family_id: str) -> None:
    """Revoke every still-live token in a family — used when a consumed (or
    already-revoked) token is replayed, since the whole chain may be
    compromised (SEC-03)."""
    RefreshToken.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _audit_refresh_reuse(record: RefreshToken) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="auth.refresh_token_reuse_detected",
            subject_kind="User",
            subject_id=record.user_id,
            actor_id=record.user_id,
            actor_role=getattr(record.user, "active_role", None) or "Unknown",
            success=False,
            reason=(
                "A refresh token that was already consumed or revoked was "
                "presented again — the entire token family has been revoked."
            ),
            payload={"family_id": record.family_id, "token_id": record.id},
        )
    except Exception:  # noqa: BLE001 — reuse handling must never itself crash
        pass


def refresh(refresh_token: str) -> dict:
    """Validate a refresh token, revoke it (single-use), and issue a fresh
    pair in the same family.

    SEC-03 — reuse detection: a refresh token is consumed (both revoked_at
    and consumed_at stamped) the moment it's rotated. If that SAME token is
    ever presented again — the token was already consumed by a legitimate
    rotation, or already revoked by a prior reuse event — it's treated as a
    stolen token being replayed, and the entire family is revoked, forcing
    re-authentication everywhere that family's descendants were live.

    Concurrency: select_for_update() serializes two simultaneous refreshes
    of the same raw token on the same DB row — the first to commit its
    consumption wins; the second re-reads the now-revoked row and takes the
    reuse-detected path, which also revokes the winner's freshly-issued
    child. The winner's child token is minted INSIDE the same atomic block
    as its consumption write (not after) — otherwise there's a window,
    between that commit and the child's creation, where a concurrently
    unblocking loser's family-wide revocation could run before the child
    exists and miss it entirely, leaving two valid descendants. Two
    concurrent presentations of one token can therefore never both end up
    with a valid descendant.

    The reuse branch's writes (family revocation, reuse_detected_at) must
    outlive this function — raising inside transaction.atomic() rolls back
    everything written in that block, which would silently undo the very
    revocation this is meant to enforce. So the atomic block only writes and
    decides; the exception (and the audit log entry, a separate write) are
    raised/recorded AFTER it has committed.
    """
    token_hash = hash_token(refresh_token or "")
    reused_record = None
    new_tokens = None
    with transaction.atomic():
        record = (
            RefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=token_hash)
            .first()
        )
        if not record or not record.user or record.user.status != "active":
            raise Unauthorized("Invalid or expired refresh token.")
        if record.expires_at <= timezone.now():
            raise Unauthorized("Invalid or expired refresh token.")

        if record.revoked_at is not None:
            record.reuse_detected_at = timezone.now()
            record.save(update_fields=["reuse_detected_at"])
            _revoke_family(record.family_id)
            reused_record = record
        else:
            now = timezone.now()
            record.revoked_at = now
            record.consumed_at = now
            record.save(update_fields=["revoked_at", "consumed_at"])
            new_tokens = issue_token_pair(
                record.user_id,
                record.user.active_role,
                family_id=record.family_id,
                parent_id=record.id,
            )

    if reused_record is not None:
        _audit_refresh_reuse(reused_record)
        raise Unauthorized("Invalid or expired refresh token.")

    return new_tokens


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
def _send_password_reset_async(to: str, name: str, token: str) -> None:
    """Fire-and-forget the real (network-bound, up to 15s) provider send on
    a background thread — SEC-04. If forgot_password() awaited this like the
    unknown-email branch's instant return, response timing alone would
    reveal whether the account exists. Needs no DB access, so no
    request-scoped connection crosses the thread boundary."""
    import logging
    import threading

    def _run() -> None:
        try:
            mailer.send_password_reset(to=to, name=name, token=token)
        except Exception:  # noqa: BLE001 — a background send must never surface here
            logging.getLogger("edify.auth").exception(
                "Background password-reset email failed"
            )

    threading.Thread(target=_run, daemon=True).start()


def forgot_password(email: str) -> dict:
    """If the email exists, generate a single-use reset token + email it.
    Always returns the same generic response (no user enumeration).

    SEC-04 — timing: the real provider send is network-bound and only ever
    happens on the known-email path; awaiting it synchronously would make
    response latency itself an account-existence oracle. In production
    (mailer.is_configured) it's backgrounded so both branches return in
    comparable time. Console/dev delivery has no network cost, so it stays
    synchronous there to keep the devPreview/devResetToken convenience for
    local testing.
    """
    user = User.objects.filter(
        email=(email or "").lower().strip(), deleted_at__isnull=True
    ).first()
    if not user:
        return {"ok": True}  # generic — don't reveal existence

    raw_token = generate_token()
    user.password_reset_token_hash = hash_token(raw_token)
    user.password_reset_expires = expiry_from_now(_reset_ttl_minutes())
    user.save(update_fields=["password_reset_token_hash", "password_reset_expires"])

    if mailer.is_configured:
        _send_password_reset_async(user.email, user.name, raw_token)
        return {"ok": True}

    # Console/dev — cheap (a log line, no network I/O), so send synchronously
    # and surface the dev token/preview so the flow is testable without a
    # real email provider.
    result = mailer.send_password_reset(to=user.email, name=user.name, token=raw_token)
    response = {"ok": True}
    if not settings.IS_PRODUCTION:
        response["devResetToken"] = raw_token
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

    from apps.audit.services import log as audit_log

    audit_log(
        action="auth.invite_accepted",
        subject_kind="user",
        subject_id=user.id,
        actor_id=user.id,
        actor_role=getattr(user, "active_role", None),
        payload={"email": user.email},
    )
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
