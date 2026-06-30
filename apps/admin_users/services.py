"""Admin-users service — user provisioning (create+invite, lifecycle)."""
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User, UserInvitation
from apps.core.email import mailer
from apps.core.exceptions import BadRequest, ConflictError, NotFoundError
from apps.core.security import expiry_from_now_days, generate_token, hash_token


def list_users() -> list[dict]:
    qs = User.objects.filter(deleted_at__isnull=True).order_by("-created_at")
    out = []
    for u in qs:
        last_invite = u.invitations.order_by("-created_at").first() if hasattr(u, "invitations") else None
        inv_status = None
        if last_invite:
            if last_invite.accepted_at:
                inv_status = "accepted"
            elif last_invite.revoked_at:
                inv_status = "revoked"
            elif last_invite.expires_at < timezone.now():
                inv_status = "expired"
            else:
                inv_status = "pending"
        out.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "phone": u.phone,
            "roles": u.roles,
            "activeRole": u.active_role,
            "status": u.status,
            "isActive": u.is_active,
            "lastLoginAt": u.last_login_at.isoformat() if u.last_login_at else None,
            "passwordSet": bool(u.password_set_at),
            "invitation": (
                {"status": inv_status, "expiresAt": last_invite.expires_at.isoformat(), "createdAt": last_invite.created_at.isoformat()}
                if last_invite else None
            ),
        })
    return out


def create(data: dict, principal) -> dict:
    email = (data.get("email") or "").lower()
    if User.objects.filter(email=email, deleted_at__isnull=True).exists():
        raise ConflictError("A user with this email already exists.")
    role = data.get("role")
    if not role:
        raise BadRequest("role is required.")
    additional = data.get("additionalRoles") or []
    roles = list(dict.fromkeys([role, *additional]))

    with transaction.atomic():
        user = User.objects.create_user(
            email=email,
            name=data["name"],
            phone=data.get("phone"),
            roles=roles,
            active_role=role,
            password=None,  # set via the invite link
            status="pending_invited",
            is_active=False,
        )
        if data.get("primaryDistrictId"):
            from apps.accounts.models import StaffProfile

            StaffProfile.objects.create(user=user, primary_district_id=data["primaryDistrictId"])
        invite_token = _create_invitation(user.id, principal.user_id)

    mail = mailer.send_invitation(
        to=email, name=user.name, invited_by_name=principal.name, token=invite_token
    )
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "status": user.status},
        "inviteToken": None if mail.get("delivered") else invite_token,
    }


def _create_invitation(user_id: str, invited_by_id: str) -> str:
    raw = generate_token()
    UserInvitation.objects.create(
        user_id=user_id,
        invited_by_id=invited_by_id,
        token_hash=hash_token(raw),
        expires_at=expiry_from_now_days(getattr(settings, "INVITE_TOKEN_TTL_DAYS", 7)),
    )
    return raw


def resend_invite(user_id: str, principal) -> dict:
    user = _get_user(user_id)
    token = _create_invitation(user.id, principal.user_id)
    mailer.send_invitation(to=user.email, name=user.name, invited_by_name=principal.name, token=token)
    return {"ok": True, "inviteToken": token if not settings.IS_PRODUCTION else None}


def revoke_invite(user_id: str, principal) -> dict:
    UserInvitation.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=timezone.now())
    return {"ok": True}


def suspend(user_id: str, principal) -> dict:
    return _set_status(user_id, "suspended", is_active=False)


def disable(user_id: str, principal) -> dict:
    return _set_status(user_id, "disabled", is_active=False)


def reactivate(user_id: str, principal) -> dict:
    return _set_status(user_id, "active", is_active=True)


def force_password_reset(user_id: str, principal) -> dict:
    user = _get_user(user_id)
    raw = generate_token()
    user.password_reset_token_hash = hash_token(raw)
    user.password_reset_expires = expiry_from_now_days(1)
    user.save(update_fields=["password_reset_token_hash", "password_reset_expires"])
    from apps.core.security import expiry_from_now
    user.password_reset_expires = expiry_from_now(45)
    user.save(update_fields=["password_reset_expires"])
    mailer.send_password_reset(to=user.email, name=user.name, token=raw)
    return {"ok": True, "resetToken": raw if not settings.IS_PRODUCTION else None}


def _set_status(user_id: str, status: str, is_active: bool) -> dict:
    user = _get_user(user_id)
    user.status = status
    user.is_active = is_active
    user.save(update_fields=["status", "is_active"])
    return {"id": user.id, "status": user.status, "isActive": user.is_active}


def _get_user(user_id: str) -> User:
    user = User.objects.filter(id=user_id, deleted_at__isnull=True).first()
    if not user:
        raise NotFoundError("User not found.")
    return user
