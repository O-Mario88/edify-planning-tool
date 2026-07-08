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

    password = data.get("password")
    if password:
        from apps.core.security import validate_password
        violations = validate_password(password, email)
        if violations:
            raise BadRequest(" ".join(violations))

    with transaction.atomic():
        if password:
            user = User.objects.create_user(
                email=email,
                name=data["name"],
                phone=data.get("phone"),
                roles=roles,
                active_role=role,
                password=password,
                status="active",
                is_active=True,
                password_set_at=timezone.now(),
            )
            invite_token = None
        else:
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
            invite_token = _create_invitation(user.id, principal.user_id)

        from apps.accounts.models import StaffProfile, StaffGeographyAssignment
        primary_district_id = data.get("primaryDistrictId")
        additional_districts = data.get("additionalDistrictIds") or []
        
        sp = StaffProfile.objects.create(
            user=user,
            primary_district_id=primary_district_id,
            title=role
        )
        
        selected_districts = []
        if primary_district_id:
            selected_districts.append(primary_district_id)
        for d_id in additional_districts:
            if d_id:
                selected_districts.append(d_id)
        selected_districts = list(dict.fromkeys(selected_districts))
        
        for d_id in selected_districts:
            StaffGeographyAssignment.objects.create(staff=sp, district_id=d_id)

    if password:
        mail = mailer.send_temporary_password_notification(
            to=email, name=user.name, invited_by_name=principal.name
        )
    else:
        mail = mailer.send_invitation(
            to=email, name=user.name, invited_by_name=principal.name, token=invite_token
        )

    return {
        "user": {"id": user.id, "email": user.email, "name": user.name, "status": user.status},
        "inviteToken": None if (password or mail.get("delivered")) else invite_token,
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


def update_user(user_id: str, data: dict, principal) -> dict:
    """Updates a user's details, email, roles, and status."""
    user = _get_user(user_id)
    
    email = (data.get("email") or "").lower().strip()
    if email and email != user.email:
        if User.objects.filter(email=email, deleted_at__isnull=True).exclude(id=user.id).exists():
            raise ConflictError("A user with this email already exists.")
        user.email = email
        
    name = data.get("name")
    if name:
        user.name = name.strip()
        
    phone = data.get("phone")
    if phone is not None:
        user.phone = phone.strip()
        
    role = data.get("role")
    if role:
        additional = data.get("additionalRoles") or []
        user.roles = list(dict.fromkeys([role, *additional]))
        user.active_role = role
        
        # Sync with StaffProfile title if profile exists
        from apps.accounts.models import StaffProfile
        sp = StaffProfile.objects.filter(user=user).first()
        if sp:
            sp.title = role
            sp.save(update_fields=["title"])

    user.save()
    return {"ok": True, "id": user.id}


def delete_user(user_id: str, principal) -> dict:
    """Soft-deletes a user from the system."""
    user = _get_user(user_id)
    user.soft_delete()
    return {"ok": True}

