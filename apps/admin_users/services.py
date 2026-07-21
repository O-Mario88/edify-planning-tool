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
        last_invite = (
            u.invitations.order_by("-created_at").first()
            if hasattr(u, "invitations")
            else None
        )
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
        out.append(
            {
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
                    {
                        "status": inv_status,
                        "expiresAt": last_invite.expires_at.isoformat(),
                        "createdAt": last_invite.created_at.isoformat(),
                    }
                    if last_invite
                    else None
                ),
            }
        )
    return out


def assert_may_administer(target, principal, *, requested_roles=None):
    """The Admin-only guard rails, in one place.

    USER_MANAGE is held by CountryDirector and HumanResources as well as
    Admin, because they must do routine staff-role changes (CCEO -> Program
    Lead). They must never be able to grant the unrestricted Admin role, nor
    touch an existing Admin's account and take it over.

    This started life inline in update_user(). reset_password and create()
    never got a copy, which left two live escalation paths: an HR user could
    set an arbitrary password on a sitting Admin, and could create a new
    active account carrying role='Admin'. Both were reproduced against the
    development database before this guard existed. Hence one function that
    every privileged path calls, rather than three copies that drift.

    `target` may be None when creating a user who does not exist yet.
    """
    from apps.core.navigation import get_user_role_slug
    from apps.core.rbac import EdifyRole

    acting_role = get_user_role_slug(principal)
    admin_role = EdifyRole.ADMIN.value
    is_admin = acting_role == "ADMIN"

    if target is not None and not is_admin and admin_role in (target.roles or []):
        raise BadRequest("Only an Admin can modify another Admin's account.")

    if requested_roles and admin_role in requested_roles and not is_admin:
        raise BadRequest("Only an Admin can grant the Admin role.")


def create(data: dict, principal) -> dict:
    email = (data.get("email") or "").lower()
    if User.objects.filter(email=email, deleted_at__isnull=True).exists():
        raise ConflictError("A user with this email already exists.")
    role = data.get("role")
    if not role:
        raise BadRequest("role is required.")
    additional = data.get("additionalRoles") or []
    roles = list(dict.fromkeys([role, *additional]))
    # No target yet, but the requested roles still need the Admin-grant guard.
    assert_may_administer(None, principal, requested_roles=roles)

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
                # A provisioner-chosen password is known to someone other than
                # its owner, so it must not survive first login. The HTML page
                # set this and the service did not; consolidating on the
                # service would otherwise have quietly dropped the guarantee.
                must_change_password=True,
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
            title=role,
            # Country and department were never captured at provisioning, so
            # `country` sat on its "Uganda" default and `department` stayed
            # NULL for everyone — which made the country-scoped HR surfaces
            # inert and left workforce planning grouping by "Unassigned".
            country=(data.get("country") or "Uganda"),
            department=data.get("department") or None,
        )

        # Assign the supervisor. `StaffSupervisorAssignment` had NO writer
        # outside the demo seeder and no field on any form, so every person
        # provisioned through this service had no reporting line — which
        # simultaneously emptied their Program Lead's team scope, left their
        # leave with no authorized approver, gave field-debrief routing no
        # target, gave PD approval routing no target, and dropped them from
        # Team Targets. system_health could already detect the condition; it
        # had no way to fix it.
        supervisor_staff_id = (data.get("supervisorStaffId") or "").strip()
        if supervisor_staff_id:
            from apps.accounts.supervisor_service import assign_supervisor

            assign_supervisor(
                sp.id, {"supervisorId": supervisor_staff_id}, principal
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

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.user_created",
        subject_kind="user",
        subject_id=user.id,
        actor_id=principal.id,
        actor_role=getattr(principal, "active_role", None),
        payload={"email": email, "roles": roles, "invited": invite_token is not None},
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "status": user.status,
        },
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
    token = _create_invitation(user.id, principal.id)
    mailer.send_invitation(
        to=user.email, name=user.name, invited_by_name=principal.name, token=token
    )
    _audit_lifecycle("admin.invite_resent", user, principal)
    return {"ok": True, "inviteToken": token if not settings.IS_PRODUCTION else None}


def revoke_invite(user_id: str, principal) -> dict:
    user = _get_user(user_id)
    UserInvitation.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    _audit_lifecycle("admin.invite_revoked", user, principal)
    return {"ok": True}


def suspend(user_id: str, principal) -> dict:
    return _set_status(user_id, "suspended", is_active=False, principal=principal)


def disable(user_id: str, principal) -> dict:
    return _set_status(user_id, "disabled", is_active=False, principal=principal)


def reactivate(user_id: str, principal) -> dict:
    return _set_status(user_id, "active", is_active=True, principal=principal)


def force_password_reset(user_id: str, principal) -> dict:
    user = _get_user(user_id)
    raw = generate_token()
    user.password_reset_token_hash = hash_token(raw)
    user.password_reset_expires = expiry_from_now_days(1)
    user.save(update_fields=["password_reset_token_hash", "password_reset_expires"])
    from apps.core.security import expiry_from_now

    user.password_reset_expires = expiry_from_now(45)
    user.save(update_fields=["password_reset_expires"])
    # A forced reset is exactly the moment a credential may be compromised —
    # revoke live refresh tokens the same way self-service reset_password
    # does, rather than leaving the old session usable until the new
    # password is actually set.
    from apps.accounts.models import RefreshToken

    RefreshToken.objects.filter(user_id=user.id, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    mailer.send_password_reset(to=user.email, name=user.name, token=raw)
    _audit_lifecycle("admin.password_reset_forced", user, principal)
    return {"ok": True, "resetToken": raw if not settings.IS_PRODUCTION else None}


def _set_status(user_id: str, status: str, is_active: bool, principal=None) -> dict:
    user = _get_user(user_id)
    user.status = status
    user.is_active = is_active
    user.save(update_fields=["status", "is_active"])
    if not is_active:
        from apps.accounts.models import RefreshToken

        RefreshToken.objects.filter(user_id=user.id, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )
    if principal is not None:
        _audit_lifecycle(f"admin.user_{status}", user, principal)
    return {"id": user.id, "status": user.status, "isActive": user.is_active}


def _audit_lifecycle(action: str, user: User, principal) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="user",
        subject_id=user.id,
        actor_id=principal.id,
        actor_role=getattr(principal, "active_role", None),
        payload={"email": user.email},
    )


def _get_user(user_id: str) -> User:
    user = User.objects.filter(id=user_id, deleted_at__isnull=True).first()
    if not user:
        raise NotFoundError("User not found.")
    return user


def update_user(user_id: str, data: dict, principal) -> dict:
    """Updates a user's details, email, roles, and status.

    Guard rails (mirrors delete_user()'s Admin-only protections, closing a
    privilege-escalation hole: USER_MANAGE is also held by CountryDirector
    and HumanResources, who must be able to do routine staff-role changes
    (e.g. CCEO -> Program Lead) but must never be able to grant the
    unrestricted Admin role to themselves or anyone else, or tamper with an
    existing Admin's account to take it over via a changed email + a
    forgot-password reset):
      - Only an acting Admin may change ANY field on another Admin's account.
      - Only an acting Admin may grant the Admin role to anyone.
      - Nobody may change their own role/roles through this endpoint (that
        would let a non-Admin silently self-promote); role switching among
        already-granted roles goes through auth_views.switch_role_view.
    """
    user = _get_user(user_id)
    assert_may_administer(user, principal)

    role = data.get("role")
    additional = data.get("additionalRoles") or []
    requested_roles = list(dict.fromkeys([role, *additional])) if role else additional
    if requested_roles:
        if user.id == principal.id:
            raise BadRequest(
                "You cannot change your own role. Switch among your already-"
                "granted roles from the role switcher, or ask another Admin."
            )
        assert_may_administer(user, principal, requested_roles=requested_roles)

    email = (data.get("email") or "").lower().strip()
    if email and email != user.email:
        if (
            User.objects.filter(email=email, deleted_at__isnull=True)
            .exclude(id=user.id)
            .exists()
        ):
            raise ConflictError("A user with this email already exists.")
        user.email = email

    name = data.get("name")
    if name:
        user.name = name.strip()

    phone = data.get("phone")
    if phone is not None:
        user.phone = phone.strip()

    if role:
        user.roles = requested_roles
        user.active_role = role

        # Sync with StaffProfile title if profile exists
        from apps.accounts.models import StaffProfile

        sp = StaffProfile.objects.filter(user=user).first()
        if sp:
            sp.title = role
            sp.save(update_fields=["title"])

    user.save()

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.user_updated",
        subject_kind="user",
        subject_id=user.id,
        actor_id=principal.id,
        actor_role=getattr(principal, "active_role", None),
        payload={"email": user.email, "roles": user.roles},
    )
    return {"ok": True, "id": user.id}


def delete_user(user_id: str, principal) -> dict:
    """Admin-only user deletion: soft-delete plus full access revocation.

    Guard rails: only an acting Admin may delete; nobody deletes themselves;
    the last active Admin can never be deleted. Revocation matters because
    User.objects does NOT filter tombstones — a soft-deleted row with
    is_active=True would keep existing sessions alive on every request, so
    the delete also disables the account, tombstones the staff profile, and
    purges the user's sessions.
    """
    from django.contrib.sessions.models import Session

    from apps.accounts.models import StaffProfile
    from apps.audit.services import log as audit_log
    from apps.core.navigation import get_user_role_slug
    from apps.core.rbac import EdifyRole

    if get_user_role_slug(principal) != "ADMIN":
        raise BadRequest("Only an Admin can delete users.")

    user = _get_user(user_id)
    if user.id == principal.id:
        raise BadRequest("You cannot delete your own account.")

    admin_role = EdifyRole.ADMIN.value
    if admin_role in (user.roles or []):
        other_admins = (
            User.objects.filter(
                deleted_at__isnull=True,
                is_active=True,
                roles__contains=[admin_role],
            )
            .exclude(id=user.id)
            .exists()
        )
        if not other_admins:
            raise BadRequest("Cannot delete the last active Admin account.")

    original_email = user.email
    with transaction.atomic():
        user.soft_delete()
        user.status = "disabled"
        user.is_active = False
        # The email column is DB-unique with no deleted_at scoping, so free
        # the address for future accounts. The original email is preserved
        # in the audit payload below.
        user.email = f"deleted-{user.id}@deleted.invalid"
        user.save(update_fields=["status", "is_active", "email", "updated_at"])

        profile = StaffProfile.objects.filter(user=user).first()
        if profile:
            profile.soft_delete()

    # Session purge is defence-in-depth (is_active=False already fails
    # ModelBackend.user_can_authenticate on the next request).
    for session in Session.objects.all():
        if session.get_decoded().get("_auth_user_id") == user.id:
            session.delete()

    audit_log(
        action="admin.user_deleted",
        subject_kind="user",
        subject_id=user.id,
        actor_id=principal.id,
        actor_role=getattr(principal, "active_role", None),
        payload={"email": original_email, "name": user.name, "roles": user.roles},
    )
    return {"ok": True}
