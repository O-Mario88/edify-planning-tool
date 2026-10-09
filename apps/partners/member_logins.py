"""A team member's own sign-in, set up by the organisation's admin.

Owner, 2026-10-09: "partner admin onbosrd their thea members and configure
their logins", and "Partner admin can re-assign the school and activities to
the team members".

The roster (``PartnerMember``) was names only: one login per organisation,
shared by whoever went to the school. A member can now hold a login of their
own. It is a Partner Field Officer account that signs in as the organisation
(``apps.core.scoping.resolve_partner_ids``), with no People record: these are
not Edify staff.

Who leads the team, and so adds its people, gives them logins, resets their
passwords and decides who looks after which school and activity: the
organisation's own login, any login of the organisation that works as Partner
Admin, and the Admin. A member's Field Officer login does none of it.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError

from .models import Partner, PartnerMember


def leads_team(principal, partner) -> bool:
    """May this person run the organisation's team?"""
    from apps.core.navigation import get_user_role_slug
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import resolve_partner_ids

    if getattr(principal, "is_superuser", False):
        return True
    if get_user_role_slug(principal) == "ADMIN":
        return True
    if partner.user_id and partner.user_id == getattr(principal, "id", None):
        return True
    return getattr(
        principal, "active_role", None
    ) == EdifyRole.PARTNER_ADMIN.value and partner.id in resolve_partner_ids(principal)


def assert_leads_team(principal, partner) -> None:
    if not leads_team(principal, partner):
        raise Forbidden(
            "Only the organisation's Partner Admin or an Edify Admin manages "
            "its team's logins, schools and activities."
        )


def _member(partner_id: str, member_id: str, principal, *, lock: bool = False):
    partner = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    assert_leads_team(principal, partner)
    members = PartnerMember.objects.filter(id=member_id, partner=partner)
    if lock:
        members = members.select_for_update()
    member = members.select_related("user").first() if not lock else members.first()
    if member is None:
        raise NotFoundError("This person is not on the organisation's team.")
    return partner, member


def member_login(member):
    """The member's account, or None: none given, or since deleted."""
    user = member.user if member.user_id else None
    if user is None or user.deleted_at is not None:
        return None
    return user


def _audit(action: str, partner, member, principal, **payload) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None) or getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"memberId": member.id, "memberName": member.name, **payload},
    )


@transaction.atomic
def create_login(partner_id: str, member_id: str, data: dict, principal) -> dict:
    """Give a team member a sign-in: a first password to be changed at first
    sign-in, or, left blank, an emailed invitation to set their own."""
    from apps.accounts.models import User
    from apps.admin_users import services as accounts
    from apps.core.rbac import EdifyRole
    from apps.core.security import validate_password
    from apps.core.blocking_io_guard import send_after_commit
    from apps.core.email import mailer

    partner, member = _member(partner_id, member_id, principal, lock=True)
    if not member.active:
        raise BadRequest("This person is no longer on the team.")
    if member_login(member) is not None:
        raise ConflictError(f"{member.name} already has a login.")
    email = (data.get("email") or member.email or "").strip().lower()
    if not email:
        raise BadRequest("Enter the email address this person will sign in with.")
    if User.objects.filter(email=email, deleted_at__isnull=True).exists():
        raise ConflictError(f"An account already uses {email}.")
    password = (data.get("password") or "").strip()
    if password:
        violations = validate_password(password, email)
        if violations:
            raise BadRequest(" ".join(violations))

    role = EdifyRole.PARTNER_FIELD_OFFICER.value
    common = {
        "email": email,
        "name": member.name,
        "phone": member.phone or None,
        "roles": [role],
        "active_role": role,
    }
    if password:
        user = User.objects.create_user(
            **common,
            password=password,
            status="active",
            is_active=True,
            password_set_at=timezone.now(),
            must_change_password=True,
        )
        token = None
    else:
        user = User.objects.create_user(
            **common, password=None, status="pending_invited", is_active=False
        )
        token = accounts._create_invitation(user.id, principal.user_id)
    member.user = user
    if not member.email:
        member.email = email
    member.save(update_fields=["user", "email", "updated_at"])

    def _notify() -> None:
        if password:
            mailer.send_temporary_password_notification(
                to=email, name=user.name, invited_by_name=principal.name
            )
        else:
            mailer.send_invitation(
                to=email, name=user.name, invited_by_name=principal.name, token=token
            )

    send_after_commit(_notify)
    _audit(
        "partner.member_login_created",
        partner,
        member,
        principal,
        userId=user.id,
        email=email,
        invited=not password,
    )
    return {"member": member.name, "email": email, "invited": not password}


def reset_password(partner_id: str, member_id: str, password: str, principal) -> dict:
    """A new one-time password for a member's login."""
    from apps.admin_users.services import set_temporary_password

    partner, member = _member(partner_id, member_id, principal)
    user = member_login(member)
    if user is None:
        raise BadRequest(f"{member.name} has no login yet.")
    if not (password or "").strip():
        raise BadRequest("Enter the new password.")
    set_temporary_password(user.id, password.strip(), principal)
    _audit("partner.member_login_password_reset", partner, member, principal)
    return {"member": member.name}


def set_active(partner_id: str, member_id: str, active: bool, principal) -> dict:
    """Stop a member's login from signing in, or let it sign in again."""
    from apps.admin_users.services import disable, reactivate

    partner, member = _member(partner_id, member_id, principal)
    user = member_login(member)
    if user is None:
        raise BadRequest(f"{member.name} has no login yet.")
    if user.id == getattr(principal, "id", None):
        raise BadRequest("You cannot deactivate the login you are signed in with.")
    (reactivate if active else disable)(user.id, principal)
    _audit(
        "partner.member_login_activated"
        if active
        else "partner.member_login_deactivated",
        partner,
        member,
        principal,
    )
    return {"member": member.name, "active": active}
