"""Partners service — directory + self-service + eligibility."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.scoping import resolve_partner_ids, resolve_user_scope

from .models import Partner, PartnerAssignment, PartnerUserSetupStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .models import PartnerMember


def _assert_partner_directory_manager(principal) -> None:
    """Partner-directory membership is a people-administration decision.

    The Users page is shared with HR, but the business rule for partner
    organisations is deliberately narrower: only the active Admin or Country
    Director role may activate, deactivate or remove them. Keeping this guard
    in the canonical service protects the HTML page and the API equally.
    Creating and correcting an organisation is wider (IA holds it) and is
    guarded by its own permission below.
    """
    from apps.core.navigation import get_user_role_slug

    if getattr(principal, "is_superuser", False):
        return
    if get_user_role_slug(principal) not in {"ADMIN", "CD"}:
        raise Forbidden(
            "Only an Admin or Country Director can manage partner organisations."
        )


def _assert_permission(principal, permission, message: str) -> None:
    from apps.core.permissions import has_permission

    if getattr(principal, "is_superuser", False):
        return
    if not has_permission(principal, permission.value):
        raise Forbidden(message)


def may_create_partner_organisation(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.PARTNER_ORGANISATION_CREATE.value)
    )


def may_manage_partner_users(principal) -> bool:
    """Partner logins are user administration: Admin and the Country Director
    (owner, 2026-09-15). Impact Assessment adds organisations and never
    reaches this."""
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    if getattr(principal, "is_superuser", False):
        return True
    return has_permission(
        principal, Permission.PARTNER_USER_MANAGE.value
    ) and has_permission(principal, Permission.USER_MANAGE.value)


def partner_login_roles() -> frozenset[str]:
    """The roles an account partner staff sign in with holds."""
    from apps.core.rbac import EdifyRole

    return frozenset(
        {EdifyRole.PARTNER_ADMIN.value, EdifyRole.PARTNER_FIELD_OFFICER.value}
    )


def is_partner_login(user) -> bool:
    """Is this the account a partner's people sign in with, rather than a
    member of staff's? Read from the role it works in."""
    return (getattr(user, "active_role", "") or "") in partner_login_roles()


def login_organisation(user) -> Partner | None:
    """The organisation this account is the login for, if it is one's."""
    if user is None:
        return None
    return Partner.objects.filter(user_id=user.pk).first()


def partner_login(partner: Partner):
    """The account an organisation signs in with, or None: nothing linked, or
    an account that has since been deleted."""
    user = partner.user if partner.user_id else None
    if user is None or user.deleted_at is not None:
        return None
    return user


def assert_partner_activity_allowance(
    partner_id: str,
    school_id: str,
    activity_type: str,
    fy: str,
    *,
    exclude_activity_id: str | None = None,
) -> None:
    """The partner activity allowance, lifted (owner, 2026-09-28).

    This refused a second non-core partner activity per partner per school per
    FY unless a PartnerActivityAllowance grant allowed more (§F). The owner
    kept it on 2026-09-27 and lifted it the next day: "lift all restrictions.
    the only restriction is for client schools to have one visit from the
    staff." A partner may now be given as much work at a school as it is
    asked to deliver. The callers keep calling this seam, so the rule has one
    place to return to if it is asked for again.
    """
    return None


def _serialize(p: Partner) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "regionName": p.region_name,
        "regionNames": p.regions,
        "trainsOn": p.trains_on,
        "notes": p.notes,
        "contactPerson": p.contact_person,
        "email": p.email,
        "phone": p.phone,
        "coverageDistricts": p.coverage_districts,
        "contractStatus": p.contract_status,
        "isCertified": p.is_certified,
        "certificationStatus": p.certification_status,
        "expertiseAreas": p.expertise_areas,
        "ssaIntervention": p.ssa_intervention,
        "ssaInterventionLabel": p.ssa_intervention_label,
        "ssaInterventions": list(p.ssa_interventions or []),
        "activityCodes": list(p.activity_codes or []),
        "activeStatus": p.active_status,
        "userSetupStatus": p.user_setup_status,
        "hasLogin": bool(p.user_id),
    }


def list_partners(principal, query: dict) -> list[dict]:
    qs = Partner.objects.filter(deleted_at__isnull=True)
    if str(query.get("activeOnly", "")).lower() == "true":
        qs = qs.filter(active_status=True)
    return [_serialize(p) for p in qs.order_by("name")]


def my_partner(principal) -> dict:
    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        raise NotFoundError("No partner linked to your account.")
    p = Partner.objects.filter(id=partner_ids[0], deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Partner not found.")
    return _serialize(p)


def my_activities(principal) -> list[dict]:
    """The partner's work queue — only activities where the partner still has a
    pending action (assigned, scheduled, or mid-completion). Once the activity is
    submitted for PL/IA review or reaches a terminal state it leaves the partner's
    queue: their part is done and the handoff has moved on."""
    from apps.activities.models import Activity
    from apps.activities.services import _serialize as serialize_activity

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        return []
    qs = Activity.objects.filter(
        assigned_partner_id__in=partner_ids, deleted_at__isnull=True
    ).exclude(
        status__in=[
            # Terminal states.
            "completed",
            "cancelled",
            "rejected",
            "deferred",
            # Handed off past the partner — PL review / IA verification / payment.
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
        ]
    )
    return [serialize_activity(a) for a in qs.select_related("school")]


def schedule_activity(activity_id: str, data: dict, principal) -> dict:
    """Partner self-schedules an assigned activity."""
    from apps.activities.services import partner_schedule

    return partner_schedule(activity_id, data, principal)


def eligible(query: dict) -> list[dict]:
    """Partners eligible for a district + expertise, and able to take new work.

    Held partners are excluded here too — the API is a second door to the same
    choice, and a rule enforced only in the HTML picker is not a rule.
    """
    qs = assignable_partners()
    district = query.get("districtName")
    if district:
        qs = qs.filter(coverage_districts__contains=[district])
    expertise = query.get("expertise")
    if expertise:
        qs = qs.filter(expertise_areas__contains=[expertise])
    return [_serialize(p) for p in qs.order_by("name")]


@transaction.atomic
def onboard(data: dict, principal) -> dict:
    """Add a partner organisation. Creates the organisation and nothing else.

    Held by Admin, the Country Director and Impact Assessment
    (PARTNER_ORGANISATION_CREATE). Until 2026-09-15 an email on the form also
    minted an active PartnerAdmin login; with IA now able to add
    organisations that was a way to create an account without user
    administration. The organisation is saved with its user setup pending and
    the user administrators are told (Configure Partner Users); a login is
    created or linked only through `configure_partner_user`.
    """
    from django.utils import timezone

    from apps.core.rbac import Permission

    _assert_permission(
        principal,
        Permission.PARTNER_ORGANISATION_CREATE,
        "Only an Admin, Country Director or Impact Assessment can add a partner "
        "organisation.",
    )

    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("Partner organisation name is required.")
    if Partner.objects.filter(name__iexact=name).exists():
        raise ConflictError(f"A partner organisation named '{name}' already exists.")

    email = (data.get("email") or "").strip().lower()
    regions = region_list(data) or []
    actor_id = getattr(principal, "user_id", None) or str(getattr(principal, "id", ""))
    p = Partner.objects.create(
        name=name,
        # Inactive until someone activates it (owner, 2026-09-07: "when it has
        # just been added, the button should be activate"). An organisation
        # that has just been typed in is not yet somebody a CCEO can assign a
        # school to; activation is the moment it becomes one, and it is a
        # separate, audited act rather than a side effect of saving a form.
        active_status=bool(data.get("activeStatus", False)),
        # Every region it works in (owner, 2026-09-23); `region_name` stays
        # the first of them, as `ssa_intervention` does for interventions.
        region_name=regions[0] if regions else None,
        region_names=regions,
        trains_on=data.get("trainsOn", []),
        notes=data.get("notes"),
        contact_person=data.get("contactPerson") or data.get("contact_person"),
        email=email,
        phone=data.get("phone"),
        ssa_intervention=data.get("ssaIntervention") or data.get("ssa_intervention"),
        # What the organisation does, as many answers as it has (owner,
        # 2026-09-22). `ssa_intervention` above stays the first of them.
        ssa_interventions=list(data.get("ssaInterventions") or []),
        activity_codes=list(data.get("activityCodes") or []),
        coverage_districts=data.get("coverageDistricts", []),
        contract_status=data.get("contractStatus", "pending"),
        is_certified=bool(data.get("isCertified")),
        certification_status=data.get("certificationStatus"),
        expertise_areas=_expertise_list(data.get("expertiseAreas", [])),
        user=None,
        user_setup_status=PartnerUserSetupStatus.PENDING,
        onboarded_by_user_id=actor_id,
        onboarded_at=timezone.now(),
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.created",
        subject_kind="partner",
        subject_id=p.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "previous": None,
            "new": {
                "name": p.name,
                "email": p.email,
                "region": p.region_name,
                "regions": p.regions,
                "userSetupStatus": p.user_setup_status,
            },
        },
    )
    transaction.on_commit(lambda: _notify_partner_user_setup(p.id, principal))
    return _serialize(p)


def partner_user_administrators(partner: Partner | None = None) -> list:
    """Who configures a partner's logins: active Admins and Country Directors."""
    from apps.accounts.models import User
    from apps.core.rbac import EdifyRole

    return list(
        User.objects.filter(
            Q(roles__contains=[EdifyRole.ADMIN.value])
            | Q(roles__contains=[EdifyRole.COUNTRY_DIRECTOR.value]),
            is_active=True,
            deleted_at__isnull=True,
        )
    )


def _notify_partner_user_setup(partner_id: str, principal) -> None:
    """Tell the user administrators an organisation waits for its logins.

    Only when someone who cannot set them up added it: an Admin or Country
    Director who adds an organisation is already the person who would act.
    """
    import logging

    try:
        if may_manage_partner_users(principal):
            return
        partner = Partner.objects.filter(id=partner_id).first()
        if partner is None:
            return
        from apps.notifications.services import WorkflowNotificationService

        actor = getattr(principal, "name", "") or "Impact Assessment"
        WorkflowNotificationService.trigger(
            event_type="partner_user_setup_required",
            category="partner",
            priority="high",
            title="Configure Partner Users",
            body=(
                f"{actor} added the partner organisation {partner.name}. "
                "Its sign-in accounts have not been set up."
            ),
            context_type="partner",
            context_id=partner.id,
            recipients=partner_user_administrators(partner),
        )
    except Exception:  # noqa: BLE001 - a notification never undoes the save
        logging.getLogger(__name__).warning(
            "partner user setup notification failed for %s", partner_id, exc_info=True
        )


@transaction.atomic
def configure_partner_user(partner_id: str, data: dict, principal) -> dict:
    """Set up an organisation's login — the user-administration half.

    ``mode`` is one of:

    * ``link`` — link an existing partner account by email;
    * ``invite`` — create a Partner Admin account through the canonical user
      service (an invitation, audited as ``admin.user_created``) and link it;
    * ``not_required`` — record that the organisation needs no login yet.

    Held only by Admin and the Country Director (PARTNER_USER_MANAGE with
    USER_MANAGE). Every outcome closes the Configure Partner Users condition.
    """
    from django.utils import timezone

    from apps.accounts.models import User
    from apps.core.rbac import EdifyRole

    if not may_manage_partner_users(principal):
        raise Forbidden("Only a user administrator can set up partner logins.")
    partner = Partner.objects.select_for_update().filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    mode = (data.get("mode") or "").strip()
    previous = {"userId": partner.user_id, "userSetupStatus": partner.user_setup_status}
    partner_roles = partner_login_roles()

    if mode == "not_required":
        partner.user_setup_status = PartnerUserSetupStatus.NOT_REQUIRED
    elif mode in ("link", "invite"):
        email = (data.get("email") or "").strip().lower()
        if not email:
            raise BadRequest("Enter the email address of the partner login.")
        existing = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if mode == "link":
            if existing is None:
                raise BadRequest(
                    f"No account uses {email}. Choose Invite to create one."
                )
            if not partner_roles.intersection(existing.roles or []):
                raise BadRequest(
                    f"{existing.name} is not a partner account. Only a Partner "
                    "Admin or Partner Field Officer login can be linked."
                )
            user = existing
        else:
            if existing is not None:
                raise ConflictError(
                    f"An account already uses {email}. Choose Link instead."
                )
            from apps.admin_users.services import create as create_user

            created = create_user(
                {
                    "email": email,
                    "name": (data.get("name") or "").strip()
                    or partner.contact_person
                    or partner.name,
                    "role": EdifyRole.PARTNER_ADMIN.value,
                },
                principal,
            )
            user = User.objects.get(id=created["user"]["id"])
        other = (
            Partner.objects.filter(user=user, deleted_at__isnull=True)
            .exclude(id=partner.id)
            .first()
        )
        if other is not None:
            raise ConflictError(f"{user.email} is already the login for {other.name}.")
        partner.user = user
        partner.user_setup_status = PartnerUserSetupStatus.CONFIGURED
    else:
        raise BadRequest("Choose Link, Invite or No login required.")

    partner.user_setup_updated_by = getattr(principal, "user_id", None) or str(
        getattr(principal, "id", "")
    )
    partner.user_setup_updated_at = timezone.now()
    partner.save(
        update_fields=[
            "user",
            "user_setup_status",
            "user_setup_updated_by",
            "user_setup_updated_at",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log
    from apps.notifications.services import resolve_condition

    audit_log(
        action="partner.user_setup_changed",
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "mode": mode,
            "previous": previous,
            "new": {
                "userId": partner.user_id,
                "userSetupStatus": partner.user_setup_status,
            },
        },
    )
    resolve_condition("partner_user_setup_required", "partner", partner.id)
    return _serialize(partner)


@transaction.atomic
def delete_partner(partner_id: str, principal) -> dict:
    """Soft-delete a partner while preserving assignments and audit history."""
    _assert_partner_directory_manager(principal)
    partner = Partner.objects.select_related("user").filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")

    snapshot = {
        "id": partner.id,
        "name": partner.name,
        "email": partner.email,
        "linkedUserId": partner.user_id,
    }
    partner.active_status = False
    partner.save(update_fields=["active_status", "updated_at"])
    partner.soft_delete()

    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.deleted",
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload=snapshot,
    )
    return {**snapshot, "deleted": True}


def _expertise_list(value) -> list[str]:
    """Expertise arrives as a list from the API and as one comma-separated
    field from the drawer; either way it is stored as a list of trimmed,
    de-duplicated names."""

    if isinstance(value, str):
        value = value.split(",")
    seen: list[str] = []
    for item in value or []:
        text = str(item).strip()
        if text and text.casefold() not in {x.casefold() for x in seen}:
            seen.append(text)
    return seen


def region_list(data: dict) -> list[str] | None:
    """The regions a payload names, or None when it names none at all.

    Most partners work in more than one region (owner, 2026-09-23), so the
    drawer posts `regionNames` as a list. A caller still sending the single
    `regionName` gets a one-item list rather than being ignored. None, not an
    empty list, means "not asked": an update that does not mention regions
    must leave them alone, while an empty `regionNames` clears them.
    """

    if "regionNames" in data:
        value = data.get("regionNames")
    elif "regionName" in data or "region_name" in data:
        value = data.get("regionName", data.get("region_name"))
    else:
        return None
    if isinstance(value, str):
        value = [value]
    return _expertise_list([item for item in value or [] if item is not None])


def set_partner_status(partner_id: str, active: bool, principal) -> dict:
    """Activate or deactivate a partner organisation (owner, 2026-09-07).

    The routine lifecycle action, and the one the directory's button toggles:
    "activate" on an organisation that has just been added, "deactivate" once
    it is live. `active_status` is what every assignment surface already keys
    on — the planning modal, oversight, withdrawal replacement, the partner
    login's own scope — so deactivating is exactly "stop receiving work"
    without touching a single historical record.
    """

    _assert_partner_directory_manager(principal)
    partner = Partner.objects.filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    if partner.active_status == bool(active):
        return _serialize(partner)
    partner.active_status = bool(active)
    partner.save(update_fields=["active_status", "updated_at"])

    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.activated" if active else "partner.deactivated",
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"name": partner.name},
    )
    return _serialize(partner)


def _is_admin(principal) -> bool:
    from apps.core.navigation import get_user_role_slug

    return (
        bool(getattr(principal, "is_superuser", False))
        or get_user_role_slug(principal) == "ADMIN"
    )


def partner_history_counts(partner: Partner) -> dict:
    """What a permanent delete would take with it."""

    from apps.activities.models import Activity

    return {
        "assignments": PartnerAssignment.objects.filter(partner=partner).count(),
        "activities": Activity.all_objects.filter(
            assigned_partner_id=partner.id
        ).count()
        if hasattr(Activity, "all_objects")
        else Activity.objects.filter(assigned_partner_id=partner.id).count(),
        "holds": partner.holds.count() if hasattr(partner, "holds") else 0,
    }


def purge_partner(partner_id: str, principal) -> dict:
    """Delete a partner organisation permanently — Admin only (owner,
    2026-09-07: "delete buttons is to delete the partner permanently and that
    should only be done by the admin").

    This is the one hard DELETE the partner tables allow, and it is fenced two
    ways. Only the Admin role may call it — a Country Director deactivates.
    And it refuses an organisation with history: assignments cascade, holds
    cascade and activities lose their partner, which is the audit trail of what
    that partner was asked to do and what it delivered. An organisation that
    was added by mistake and never given work can go; one that has worked is
    deactivated instead, and its record stays.
    """

    if not _is_admin(principal):
        raise Forbidden("Only an Admin can delete a partner organisation permanently.")
    partner = Partner.all_objects.select_related("user").filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    history = partner_history_counts(partner)
    if any(history.values()):
        raise ConflictError(
            f"'{partner.name}' has history — "
            f"{history['assignments']} assignment(s), {history['activities']} "
            f"activit(y/ies), {history['holds']} hold(s). Deactivate it instead; "
            "the record stays for the audit trail."
        )
    snapshot = {
        "id": partner.id,
        "name": partner.name,
        "email": partner.email,
        "linkedUserId": partner.user_id,
    }
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.purged",
        subject_kind="partner",
        subject_id=partner.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload=snapshot,
    )
    partner.delete()
    return {**snapshot, "purged": True}


def add_member(partner_id: str, data: dict, principal) -> "PartnerMember":
    """Add a person to a partner's roster — staff or volunteer."""

    from .models import PartnerMember, PartnerMemberRole

    partner = Partner.objects.filter(id=partner_id).first()
    if partner is None:
        raise NotFoundError("Partner organisation not found.")
    scope = resolve_user_scope(principal)
    if not (
        _is_admin(principal) or scope.country_scope or partner.id in scope.partner_ids
    ):
        raise Forbidden("You may only manage the roster of a partner in your scope.")
    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("A name is required.")
    role = (data.get("role") or PartnerMemberRole.STAFF).strip()
    if role not in PartnerMemberRole.values:
        raise BadRequest("Role must be staff or volunteer.")
    return PartnerMember.objects.create(
        partner=partner,
        name=name,
        role=role,
        title=(data.get("title") or "").strip(),
        phone=(data.get("phone") or "").strip(),
        email=(data.get("email") or "").strip().lower(),
        added_by_user_id=getattr(
            principal, "user_id", str(getattr(principal, "id", ""))
        ),
    )


def remove_member(partner_id: str, member_id: str, principal) -> None:
    from .models import PartnerMember

    member = PartnerMember.objects.filter(id=member_id, partner_id=partner_id).first()
    if member is None:
        raise NotFoundError("Roster entry not found.")
    scope = resolve_user_scope(principal)
    if not (
        _is_admin(principal)
        or scope.country_scope
        or member.partner_id in scope.partner_ids
    ):
        raise Forbidden("You may only manage the roster of a partner in your scope.")
    member.delete()


def update(partner_id: str, data: dict, principal) -> dict:
    p = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Partner not found.")
    # PARTNER_MANAGE alone isn't ownership — mirrors the scope check every
    # other domain service applies before mutation (e.g. clusters._scope_filter
    # gating writes by district_ids). Country-scoped roles (Admin, CD) manage
    # every partner by design; any role holding PARTNER_MANAGE without country
    # scope is restricted to the partner(s) actually in their resolved scope.
    scope = resolve_user_scope(principal)
    own_login = p.id in (scope.partner_ids or [])
    if not own_login:
        from apps.core.rbac import Permission

        # Country reach alone is not authority over the record (2026-09-15):
        # the Accountant and the RVP read every partner and correct none.
        _assert_permission(
            principal,
            Permission.PARTNER_ORGANISATION_EDIT,
            "You may only update a partner organisation you are authorised to edit.",
        )
        if not scope.country_scope and not getattr(principal, "is_superuser", False):
            raise Forbidden("You may only update a partner within your scope.")
    before = {
        "name": p.name,
        "contactPerson": p.contact_person,
        "email": p.email,
        "phone": p.phone,
        "regionName": p.region_name,
        "regionNames": p.regions,
    }
    for field_name in (
        "name",
        "notes",
        "contact_person",
        "email",
        "phone",
        "contract_status",
        "certification_status",
    ):
        camel = _camel(field_name)
        if camel in data:
            setattr(p, field_name, data[camel])
    regions = region_list(data)
    if regions is not None:
        # Every region, and the first of them in the column the older readers
        # use; unticking them all clears both.
        p.region_names = regions
        p.region_name = regions[0] if regions else None
    for arr_field in ("trains_on", "coverage_districts", "expertise_areas"):
        camel = _camel(arr_field)
        if camel in data:
            setattr(p, arr_field, data[camel])
    if "isCertified" in data:
        p.is_certified = bool(data["isCertified"])
    if "activeStatus" in data:
        # Activation is the directory manager's act (set_partner_status), not
        # a field any editor of the record may flip.
        _assert_partner_directory_manager(principal)
        p.active_status = bool(data["activeStatus"])
    p.save()
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner.updated",
        subject_kind="partner",
        subject_id=p.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "previous": before,
            "new": {
                "name": p.name,
                "contactPerson": p.contact_person,
                "email": p.email,
                "phone": p.phone,
                "regionName": p.region_name,
                "regionNames": p.regions,
            },
        },
    )
    return _serialize(p)


_CAMEL_MAP = {
    "contact_person": "contactPerson",
    "coverage_districts": "coverageDistricts",
    "contract_status": "contractStatus",
    "certification_status": "certificationStatus",
    "expertise_areas": "expertiseAreas",
    "trains_on": "trainsOn",
}


def _camel(snake: str) -> str:
    return _CAMEL_MAP.get(snake, snake)


__all__ = [
    "list_partners",
    "my_partner",
    "my_activities",
    "schedule_activity",
    "eligible",
    "onboard",
    "configure_partner_user",
    "may_create_partner_organisation",
    "may_manage_partner_users",
    "update",
]


def mark_assignment_scheduled(assignment, *, scheduled_date, activity):
    """Move a PartnerAssignment from pending to scheduled, once its Activity exists.

    Both planning views -- the single handoff and the bulk one -- wrote this
    three-line transition inline and identically. Keeping it here means the
    assignment lifecycle has one owner: a handoff that stays stuck at
    `pending_scheduling` after its Activity was created is a real defect people
    have hit, and it is easier to see and to fix in one function than in two
    copies inside unrelated view bodies.

    `activity` is required, not optional. A scheduled assignment whose activity
    is not recorded is exactly the row planning oversight cannot resolve: it has
    to decide whether the assignment and some activity are one item or two, and
    without the id it is guessing. Making the argument mandatory means a future
    caller cannot create that row by omission.

    Idempotent: re-running it on an already-scheduled assignment rewrites the
    same values rather than raising, so a retried HTMX POST is harmless.
    """
    assignment.status = PartnerAssignment.STATUS_PARTNER_SCHEDULED
    assignment.scheduled_date = scheduled_date
    assignment.scheduled_activity = activity
    assignment.save(
        update_fields=[
            "status",
            "scheduled_date",
            "scheduled_activity",
            "updated_at",
        ]
    )
    return assignment


#: What cancelling a partner's activity did to the hand-over it belonged to.
HANDOVER_REOPENED = "reopened"
HANDOVER_CLOSED = "closed"


def undo_assignment_scheduling(
    activity, *, partner_dated: bool, reason: str = "", actor_id: str = ""
) -> str:
    """Undo the scheduling a cancelled activity stood for (owner, 2026-10-08:
    "cancelled activities should undo the scheduling done and should apply to
    both staff and partner cancelled activities").

    Cancelling staff's own work already put the school back where it was. A
    Partner's work did not come back: the hand-over stayed "scheduled by the
    partner" on the cancelled day, pointing at the cancelled activity, so the
    Partner was refused when it tried to date the school again ("This
    assignment is already scheduled") and the school was on no list — neither
    waiting for the Partner nor on its plan.

    What is undone is what the scheduling did, and no more:

    * **The Partner had dated it** (``partner_dated``). The date is what was
      scheduled, so the date is what goes: the hand-over is waiting for the
      Partner again, with no day and no activity, and the Partner dates it
      afresh. The school stays assigned — taking it back from the Partner is
      a withdrawal, with its own reasons and notices. ``HANDOVER_REOPENED``.
    * **Staff had booked it** — a Certified Partner Agency put on a day, or
      work created already carrying a Partner that the Partner never dated.
      The booking is what was scheduled, so the booking goes: its hand-over
      is closed, with nothing left for anybody to decide, and no longer holds
      the school, a package slot or a place among the school's Partners.
      ``HANDOVER_CLOSED``.

    Returns which, or "" when the activity belongs to no live hand-over. Call
    inside the cancellation's transaction; the hand-over row is locked. A
    withdrawal does not come through here: it decides the hand-over itself.
    """
    from apps.audit.services import log as audit_log

    assignment = (
        PartnerAssignment.objects.select_for_update(of=("self",))
        .select_related("school", "partner")
        .filter(scheduled_activity_id=activity.id)
        .first()
    )
    if assignment is None or assignment.status not in (
        PartnerAssignment.SCHEDULED_STATUSES
    ):
        return ""
    reason = (reason or "").strip()
    before = {
        "status": assignment.status,
        "scheduledDate": (
            assignment.scheduled_date.isoformat() if assignment.scheduled_date else None
        ),
        "activityId": activity.id,
    }
    # One open hand-over per school and partner (the model's own rule): with
    # another already waiting, this one cannot wait beside it.
    reopen = partner_dated and assignment.open_duplicate() is None
    assignment.scheduled_date = None
    assignment.scheduled_activity = None
    fields = ["status", "scheduled_date", "scheduled_activity", "updated_at"]
    if reopen:
        assignment.status = PartnerAssignment.STATUS_PENDING_SCHEDULING
        if not assignment.training_course_id and activity.training_course_id:
            # Work created in one step names its training on the activity
            # alone; the Partner dating it again must deliver the same one.
            assignment.training_course_id = activity.training_course_id
            fields.append("training_course")
    else:
        now = timezone.now()
        assignment.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        assignment.returned_at = now
        assignment.return_reason = f"The booking was cancelled. {reason}".strip()[
            :RETURN_REASON_MAX_LENGTH
        ]
        assignment.resolution = PartnerAssignment.RESOLUTION_SUPPORT_CLOSED
        assignment.resolution_note = "Closed with the cancelled activity."
        assignment.resolved_at = now
        assignment.resolved_by = actor_id or None
        fields += [
            "returned_at",
            "return_reason",
            "resolution",
            "resolution_note",
            "resolved_at",
            "resolved_by",
        ]
    assignment.save(update_fields=fields)
    if reopen:
        # Waiting again, it holds a place in a Core School's package as any
        # waiting hand-over does. Bookkeeping: it never blocks a cancellation.
        from apps.core_schools.package_credit import hold_slot_again

        try:
            with transaction.atomic():
                hold_slot_again(assignment)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Core slot reservation failed for reopened assignment %s",
                assignment.id,
                exc_info=True,
            )
    outcome = HANDOVER_REOPENED if reopen else HANDOVER_CLOSED
    audit_log(
        action=f"partner_assignment.scheduling_{outcome}",
        subject_kind="PartnerAssignment",
        subject_id=assignment.id,
        actor_id=str(actor_id or ""),
        payload={
            "before": before,
            "after": {"status": assignment.status},
            "school": getattr(assignment.school, "name", ""),
            "partner": getattr(assignment.partner, "name", ""),
            "reason": reason,
        },
    )
    return outcome


# ── Returning an assignment to staff ─────────────────────────────────────────
# Minimum is long enough to rule out "no" and "busy"; maximum is short enough
# that the field stays a sentence rather than becoming a report. Staff need
# enough to choose the next action, not a narrative.
RETURN_REASON_MIN_LENGTH = 10
RETURN_REASON_MAX_LENGTH = 300


def return_assignment(assignment_id: str, data: dict, principal) -> dict:
    """Partner hands an unscheduled assignment back to the managing staff.

    Return exists only before scheduling. Once a partner has scheduled, the
    assignment has an Activity, a catalogue-snapshotted cost and a place in the
    week/month/quarter/FY budget, and unpicking that silently is what
    rescheduling, release and cancellation are for. So this refuses rather than
    reaching into finance.

    Idempotent: returning an already-returned assignment is a no-op that
    reports success. A partner double-tapping on a slow connection should not
    get an error for something that already happened, and a second audit row
    would misrepresent one decision as two.
    """
    from django.utils import timezone

    from apps.audit.services import log as audit_log
    from apps.partners.models import PartnerAssignment, PartnerReturnReason

    partner_ids = resolve_partner_ids(principal)
    if not partner_ids:
        raise Forbidden("Only a partner user may return an assignment.")

    category = ((data or {}).get("reason_category") or "").strip()
    reason = ((data or {}).get("reason") or "").strip()

    valid_categories = {c.value for c in PartnerReturnReason}
    if category not in valid_categories:
        raise BadRequest("Choose a reason category.")
    # Length is measured on the stripped value, so whitespace padding cannot
    # buy the minimum.
    if len(reason) < RETURN_REASON_MIN_LENGTH:
        raise BadRequest(
            f"Explain briefly why you cannot take this assignment "
            f"(at least {RETURN_REASON_MIN_LENGTH} characters)."
        )
    if len(reason) > RETURN_REASON_MAX_LENGTH:
        raise BadRequest(
            f"Keep the explanation under {RETURN_REASON_MAX_LENGTH} characters."
        )

    with transaction.atomic():
        # Locked because the staff side can withdraw or reassign the same row,
        # and a partner page open in another tab can be stale.
        assignment = (
            PartnerAssignment.objects.select_for_update()
            .filter(id=assignment_id, partner_id__in=partner_ids)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Assignment not found.")

        if assignment.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
            return _serialize_assignment(assignment)

        if assignment.status not in PartnerAssignment.UNSCHEDULED_STATUSES:
            raise ConflictError(
                "This assignment has already been scheduled. Use Reschedule or "
                "request release instead of returning it."
            )

        assignment.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        assignment.return_reason_category = category
        assignment.return_reason = reason
        assignment.returned_at = timezone.now()
        assignment.returned_by = getattr(principal, "user_id", None) or getattr(
            principal, "id", None
        )
        assignment.save(
            update_fields=[
                "status",
                "return_reason_category",
                "return_reason",
                "returned_at",
                "returned_by",
                "updated_at",
            ]
        )
        # The Core package slot the handover held goes back to the package,
        # open to be scheduled again (owner, 2026-09-27).
        from apps.core_schools.package_credit import release_assignment_slot

        release_assignment_slot(assignment)

    audit_log(
        action="partner.assignment_returned",
        subject_kind="PartnerAssignment",
        subject_id=assignment.id,
        actor_id=assignment.returned_by or "unknown",
        actor_role=getattr(principal, "active_role", "") or "",
        success=True,
        payload={
            "partner_id": assignment.partner_id,
            "school_id": assignment.school_id,
            "cluster_id": assignment.cluster_id,
            "reason_category": category,
            "reason": reason,
        },
    )
    # After commit, so a notification never announces a return that rolled back.
    _notify_assignment_returned(assignment, principal, category, reason)
    return _serialize_assignment(assignment)


def _serialize_assignment(assignment) -> dict:
    return {
        "id": assignment.id,
        "status": assignment.status,
        "schoolId": assignment.school_id,
        "clusterId": assignment.cluster_id,
        "partnerId": assignment.partner_id,
        "returnReasonCategory": assignment.return_reason_category,
        "returnReason": assignment.return_reason,
        "returnedAt": (
            assignment.returned_at.isoformat() if assignment.returned_at else None
        ),
        "returnedBy": assignment.returned_by,
    }


def _notify_assignment_returned(assignment, principal, category, reason) -> None:
    """Tell the managing staff, with the reason, and close the partner's To-Do.

    Bookkeeping must not break the return itself: the assignment is already
    committed by the time this runs, and a notification backend being down is
    not a reason to tell the partner their return failed.
    """
    import logging

    from apps.partners.models import PartnerReturnReason

    logger = logging.getLogger(__name__)
    try:
        from apps.notifications.services import (
            WorkflowNotificationService,
            resolve_condition,
        )

        # The partner's own "new assignment from Edify staff" notification is
        # answered by the return exactly as it is by scheduling — leaving it
        # open forever was audit finding F9b.
        resolve_condition(
            "partner_scheduled_activity", "partner_assignment", assignment.id
        )

        staff_id = assignment.assigning_staff_id
        if not staff_id:
            return
        label = dict(PartnerReturnReason.choices).get(category, category)
        where = getattr(assignment.school, "name", None) or getattr(
            assignment.cluster, "name", "an assignment"
        )
        WorkflowNotificationService.trigger(
            event_type="partner_assignment_returned",
            category="partner",
            # High: this is work that will not happen unless the staff member
            # acts, and the schedule-by date keeps running while it waits.
            priority="high",
            title="A partner returned an assignment",
            body=(
                f"{getattr(principal, 'name', 'A partner')} returned "
                f"{where} — {label}. {reason}"
            ),
            context_type="partner_assignment",
            context_id=assignment.id,
            recipients=[staff_id],
        )
    except Exception:  # pragma: no cover — bookkeeping must not break the flow
        logger.warning("partner.assignment_returned notification failed", exc_info=True)


def assignable_partners():
    """Partners who may receive NEW work right now.

    The one place that question is answered, because six views built the
    picker independently and a held partner was still offered by all of them —
    the assignment failed at save with a conflict, after the person had chosen
    a school, an activity and a reason. Offering a choice the system will
    refuse is a worse experience than not offering it, and it teaches people
    that the error is arbitrary.

    Excludes held partners. Does NOT exclude partners with withdrawn history:
    a partner who lost one assignment to a closed school is not disqualified
    from the next one, and quietly hiding them would be a performance
    judgement made by a query.
    """
    from apps.partners.withdrawal_models import PartnerHold

    held = PartnerHold.objects.filter(lifted_at__isnull=True).values_list(
        "partner_id", flat=True
    )
    return (
        Partner.objects.filter(deleted_at__isnull=True, active_status=True)
        .exclude(id__in=held)
        .order_by("name")
    )


#: Certification states that permit new bookings. A blank value is the
#: historic shape for a partner flagged certified before the status column
#: existed, and is treated as certified rather than as a refusal.
BOOKABLE_CERTIFICATION_STATES = {"", "certified", "active"}


def bookable_certified_agencies(*, activity_type: str = "", district_name: str = ""):
    """Certified agencies Edify staff may book onto a date right now (§16).

    Certified-agency booking is a stronger act than assignment: staff choose
    the date, the Activity is scheduled immediately, budget moves, and the
    booking lands in the agency's My Plan as work they are expected to
    prepare for. So the picker offers only agencies that will actually pass
    the booking transaction — every condition here is re-checked at write
    time, and offering a choice the system will refuse teaches people that
    the error is arbitrary.

    Ordinary uncertified partners are never included. They receive work
    through assignment and choose their own dates.
    """
    qs = assignable_partners().filter(is_certified=True)
    qs = qs.filter(
        Q(certification_status__isnull=True)
        | Q(certification_status__in=BOOKABLE_CERTIFICATION_STATES)
    )
    if district_name:
        # An empty coverage list means "not yet scoped", which the directory
        # treats as unrestricted everywhere else; narrowing it here only would
        # hide agencies the assignment picker offers.
        qs = qs.filter(
            Q(coverage_districts__len=0)
            | Q(coverage_districts__contains=[district_name])
        )
    if activity_type:
        qs = qs.filter(Q(trains_on__len=0) | Q(trains_on__contains=[activity_type]))
    return qs


ALLOWANCE_GRANT_ROLES = ("CountryDirector", "Program Lead", "Admin")


def grant_partner_activity_allowance(principal, data: dict):
    """§F the auditable grant: more partner work at one school, with who
    allowed it, why, and (optionally) until when. The allowance gate reads
    these rows — this is the ONLY writer."""
    from apps.core.exceptions import BadRequest, Forbidden

    if getattr(principal, "active_role", None) not in ALLOWANCE_GRANT_ROLES:
        raise Forbidden(
            "Only a Country Director, Program Lead or Admin can grant "
            "additional partner activity allowances."
        )
    from apps.schools.models import School

    from .models import Partner, PartnerActivityAllowance

    partner = Partner.objects.filter(
        id=data.get("partner_id"), deleted_at__isnull=True
    ).first()
    school = School.objects.filter(
        id=data.get("school_id"), deleted_at__isnull=True
    ).first()
    reason = str(data.get("reason") or "").strip()
    if partner is None:
        raise BadRequest("Choose the partner organisation.")
    if school is None:
        raise BadRequest("Choose the school.")
    if not reason:
        raise BadRequest("A reason for the additional allowance is required.")
    try:
        additional = max(1, int(data.get("additional_activities") or 1))
    except (TypeError, ValueError):
        additional = 1
    from apps.core.fy import get_operational_fy

    return PartnerActivityAllowance.objects.create(
        partner=partner,
        school=school,
        fy=str(data.get("fy") or get_operational_fy()),
        additional_activities=additional,
        activity_type=str(data.get("activity_type") or "").strip() or None,
        granted_by=getattr(principal, "user_id", None) or str(principal.id),
        reason=reason,
        expires_at=data.get("expires_at") or None,
    )


def create_assignment(**fields):
    """THE creation door for partner handovers (§30, audit F10).

    Seven creation sites used to hand-pick the opening workflow status as a
    create() kwarg, and four spellings of "unscheduled" reached the database
    before UNSCHEDULED_STATUSES was invented to contain them. Callers never
    choose the opening status here — a new handover always starts
    pending_scheduling, and the partner's Schedule/Return decision is the
    only thing that moves it. Audit + partner notification ride on the
    post_save signal (apps/partners/signals.py), which covers every creation
    path by construction.

    Nor do callers date it (owner, 2026-10-05: "the date on the partner
    assignment drawer should change from target date to assigned date so that
    the staff cannot schedule for the partner"). A hand-over carries the day
    it was made, which is ``created_at``; ``scheduled_date`` is written when
    the partner schedules the work and by nothing before that.
    """
    from apps.schools.lifecycle_service import assert_operating

    from .models import PartnerAssignment

    from .handover_policy import past_school_rules

    fields.pop("status", None)
    fields.pop("scheduled_date", None)
    school = fields.get("school")
    assert_operating(school)
    # A project's hand-over goes past the school rules below for now (owner,
    # 2026-10-05; `handover_policy`). A closed school takes no new work either
    # way.
    if not past_school_rules(fields.get("project"), fields.get("project_id")):
        _assert_school_takes_partner_work(school)
        _assert_partner_half_open(school, fields)
        _assert_project_partner(fields)
        _assert_partner_delivers(fields)
    try:
        # A savepoint of its own, so a lost race leaves the caller's
        # transaction usable for the error it reports.
        with transaction.atomic():
            _hold_training_ceiling(school, fields)
            assignment = PartnerAssignment.objects.create(
                status=PartnerAssignment.STATUS_PENDING_SCHEDULING, **fields
            )
            # A handover at a Core School from the Planning page holds one of
            # the package's slots while it waits for the partner, as a Core
            # Schools handover does (owner, 2026-09-27). One that names its
            # slot is committed by its caller (commit_assign).
            from apps.core_schools.package_credit import reserve_for_assignment

            try:
                reserve_for_assignment(assignment)
            except Exception:  # noqa: BLE001 - bookkeeping never blocks a handover
                logger.warning(
                    "Core slot reservation failed for assignment %s",
                    assignment.id,
                    exc_info=True,
                )
            return assignment
    except IntegrityError as exc:
        # Two submissions that both passed PartnerAssignment.save's check
        # before either committed: the index refuses the second, and it gets
        # the same sentence the check would have given it.
        if "uniq_open_partner_school_assignment" not in str(exc):
            raise
        raise ConflictError(
            f"{getattr(school, 'name', None) or 'This school'} is already "
            "assigned to this partner and is waiting for the partner to "
            "schedule it. A school is assigned to the same partner only once."
        ) from exc


def _hold_training_ceiling(school, fields: dict) -> None:
    """A school handed to a Partner for a training is committed to that
    training from this moment, so it takes a place under the training ceiling
    of the staff member the hand-over is filed under (owner, 2026-10-08:
    "Assigned must still count toward training coverage/capacity"). Here, at
    the one creation door, inside the write's transaction. A project's
    hand-over is the project's: its schools are held by the capacity its
    coordinator set, never by a training ceiling."""
    if school is None or fields.get("project") or fields.get("project_id"):
        return
    course = fields.get("training_course")
    course_id = fields.get("training_course_id") or getattr(course, "id", None)
    if not course_id:
        item = fields.get("catalogue_item")
        if item is not None and getattr(item, "is_training_course", False):
            course_id = item.id
    if not course_id:
        return
    from apps.planning.training_ceilings import reserve_for_handover

    reserve_for_handover(
        school_id=school.id,
        course_id=course_id,
        monitoring_staff_id=fields.get("monitoring_staff_id"),
        assigning_staff_id=fields.get("assigning_staff_id"),
    )


def _assert_partner_delivers(fields: dict) -> None:
    """The training a hand-over delivers is one the partner is recorded as
    delivering (`capabilities.delivers`) — the course a training hand-over
    names, or a course chosen as the hand-over's catalogue item."""
    from .capabilities import assert_delivers

    partner = fields.get("partner")
    for item in (fields.get("training_course"), fields.get("catalogue_item")):
        assert_delivers(partner, item)


def _assert_project_partner(fields: dict) -> None:
    """Project work goes to the project's own partners, or carries a reason
    (`projects.services.assert_partner_on_project`). Here, at the one creation
    door, so the coordinator's bulk hand-over, the Planning drawer with a
    project and a reassignment all keep the same list."""
    project = fields.get("project")
    if project is None and fields.get("project_id"):
        from apps.projects.models import Project

        project = Project.objects.filter(id=fields["project_id"]).first()
    if project is None:
        return
    from apps.projects.services import assert_partner_on_project

    from .models import Partner

    partner = fields.get("partner")
    if partner is None and fields.get("partner_id"):
        partner = Partner.all_objects.filter(id=fields["partner_id"]).first()
    assert_partner_on_project(project, partner, fields.get("override_reason") or "")


def _assert_partner_half_open(school, fields: dict) -> None:
    """A Core package's partner half is two visits and two trainings (owner,
    2026-09-30). Here, at the one creation door, so the Core Schools drawer,
    the Planning drawer, a project's hand-over and every bulk path refuse the
    same third one. A replacement for a returned hand-over takes its place
    rather than adding one: the returned row no longer counts."""
    if school is None or getattr(school, "school_type", None) != "core":
        return
    from apps.core_schools.package_credit import assignment_kind
    from apps.core_schools.package_split import PARTNER, assert_side_open

    from .models import PartnerAssignment

    project = fields.get("project")
    course = fields.get("training_course")
    shape = PartnerAssignment(
        project_id=fields.get("project_id") or getattr(project, "id", None),
        # A universal training is on top of the package (owner, 2026-10-06).
        training_course_id=fields.get("training_course_id")
        or getattr(course, "id", None),
        support_type=fields.get("support_type"),
        visit_number=fields.get("visit_number"),
        training_number=fields.get("training_number"),
        expected_activity_type=fields.get("expected_activity_type"),
        purpose_of_visit=fields.get("purpose_of_visit"),
    )
    # None for the hand-over of a project outside the package (Alumni): it
    # takes none of the partner's two and is not refused over them.
    assert_side_open(school, assignment_kind(shape), PARTNER)


def _assert_school_takes_partner_work(school) -> None:
    """Champion schools are staff-delivered.

    Owner, 2026-09-21: Programme schools "can receive all the activities
    (visit, trainings) client schools should receive but cannot be assigned
    to partner". Core Trained and Core Graduate left that list on 2026-09-28
    and are planned like client schools; Champion takes only donor and story
    visits, which no partner delivers. The
    drawers grey the control and the visit gate carries the sentence; this is
    the same refusal at the one creation door, so a bulk path or an API client
    cannot walk around it.
    """
    from apps.core.exceptions import BadRequest
    from apps.planning.visit_gate import (
        OUTREACH_ONLY_SCHOOL_TYPES,
        programme_school_partner_refusal,
    )

    if school is None:
        return
    school_type = getattr(school, "school_type", "")
    if school_type in OUTREACH_ONLY_SCHOOL_TYPES:
        raise BadRequest(
            programme_school_partner_refusal(
                getattr(school, "name", "This school"), school_type
            )
        )


# ── Deciding what happens to work a Partner handed back ─────────────────────
def resolve_returned_assignment(assignment_id: str, data: dict, principal) -> dict:
    """Record the staff decision on a returned assignment — exactly once.

    The three governed outcomes (owner, 2026-09-23):

    * ``reassigned`` — the same support requirement goes to another Partner.
      A new assignment is opened through ``create_assignment`` carrying the
      returned one's slot identifiers and ``replaces_assignment``, so the
      school gains no second entitlement and no cost exists until the new
      Partner schedules.
    * ``staff_delivery`` — the owner's team delivers the support. Nothing is
      created here: the school is Staff Managed again on the next read and is
      planned from the normal Planning page, through the normal staff costing
      and fund-request workflow.
    * ``support_closed`` — the support is no longer required.

    The school's ownership never moves. Idempotent: a second submission (a
    double click, a retried request) returns the first decision and creates
    nothing, because the row is locked and its ``resolved_at`` is checked
    before anything is written.
    """
    from django.utils import timezone

    from apps.audit.services import log as audit_log
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.planning.partner_oversight_service import assignment_in_scope

    resolution = str((data or {}).get("resolution") or "").strip()
    note = str((data or {}).get("note") or "").strip()
    valid = {value for value, _label in PartnerAssignment.RESOLUTION_CHOICES}
    if resolution not in valid:
        raise BadRequest("Choose what happens to this returned work.")
    if not has_permission(principal, Permission.PARTNER_RETURN_RESOLVE.value):
        raise Forbidden("You do not have permission to resolve returned work.")
    if resolution == PartnerAssignment.RESOLUTION_REASSIGNED and not has_permission(
        principal, Permission.PARTNER_ASSIGNMENT_REASSIGN.value
    ):
        raise Forbidden("You do not have permission to reassign Partner work.")
    # Special Project work is its Project Coordinator's to decide, wherever
    # the school sits (owner, 2026-09-24): the coordinator reaches it through
    # the project, everyone else through the Partner Monitoring team lens —
    # and on project work, that lens reads but does not decide.
    from apps.projects.authority import directs_project_work, project_work_refusal

    project_id = (
        PartnerAssignment.objects.filter(id=assignment_id)
        .values_list("project_id", flat=True)
        .first()
    )
    directs = bool(project_id) and directs_project_work(principal, project_id)
    if not directs and not assignment_in_scope(principal, assignment_id):
        raise NotFoundError("Assignment not found.")
    if project_id and not directs:
        from apps.projects.models import Project

        raise Forbidden(
            project_work_refusal(
                Project.objects.filter(id=project_id).first(),
                action="decide what happens to work its Partner returned",
            )
        )

    replacement = None
    with transaction.atomic():
        assignment = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related("school", "partner")
            .filter(id=assignment_id)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Assignment not found.")
        if assignment.status != PartnerAssignment.STATUS_RETURNED_TO_STAFF:
            raise ConflictError(
                "Only work a Partner has returned can be resolved here."
            )
        if assignment.resolved_at is not None:
            # Already decided: report the decision rather than make another.
            return _serialize_resolution(assignment, None)

        if resolution == PartnerAssignment.RESOLUTION_REASSIGNED:
            partner_id = str((data or {}).get("partner_id") or "").strip()
            partner = assignable_partners().filter(id=partner_id).first()
            if partner is None:
                raise BadRequest("Choose an active Partner to take this work.")
            if partner.id == assignment.partner_id:
                raise BadRequest(
                    f"{partner.name} returned this work. Choose another Partner."
                )
            if assignment.project_id:
                # New work on the project: a paused or closed one takes none.
                from apps.projects.services import assert_accepts_new_work

                assert_accepts_new_work(assignment.project)
            replacement = create_assignment(
                school=assignment.school,
                cluster=assignment.cluster,
                partner=partner,
                assigning_staff_id=getattr(principal, "staff_profile_id", None)
                or getattr(principal, "id", None),
                monitoring_staff_id=assignment.monitoring_staff_id
                or assignment.assigning_staff_id,
                assignment_mode=assignment.assignment_mode,
                catalogue_item=assignment.catalogue_item,
                training_course=assignment.training_course,
                source_ssa=assignment.source_ssa,
                source_activity=assignment.source_activity,
                project=assignment.project,
                # A project's work to a partner outside its list needs a
                # reason; the decision's note is that reason.
                override_reason=note,
                purpose=assignment.purpose,
                focus_intervention=assignment.focus_intervention,
                purpose_of_visit=assignment.purpose_of_visit,
                expected_activity_type=assignment.expected_activity_type,
                support_type=assignment.support_type,
                visit_number=assignment.visit_number,
                training_number=assignment.training_number,
                catalogue_snapshot=assignment.catalogue_snapshot,
                replaces_assignment=assignment,
                reassignment_sequence=(assignment.reassignment_sequence or 0) + 1,
            )

        assignment.resolution = resolution
        assignment.resolution_note = note
        assignment.resolved_at = timezone.now()
        assignment.resolved_by = getattr(principal, "id", None)
        assignment.save(
            update_fields=[
                "resolution",
                "resolution_note",
                "resolved_at",
                "resolved_by",
                "updated_at",
            ]
        )

    audit_log(
        action="partner.assignment_return_resolved",
        subject_kind="PartnerAssignment",
        subject_id=assignment.id,
        actor_id=getattr(principal, "id", None) or "unknown",
        actor_role=getattr(principal, "active_role", "") or "",
        success=True,
        payload={
            "school_id": assignment.school_id,
            "partner_id": assignment.partner_id,
            "resolution": resolution,
            "replacement_assignment_id": getattr(replacement, "id", None),
        },
    )
    try:
        from apps.notifications.services import resolve_condition

        # The "a partner returned an assignment" notice is answered.
        resolve_condition(
            "partner_assignment_returned", "partner_assignment", assignment.id
        )
    except Exception:  # pragma: no cover — bookkeeping never breaks the decision
        pass
    return _serialize_resolution(assignment, replacement)


def _serialize_resolution(assignment, replacement) -> dict:
    return {
        **_serialize_assignment(assignment),
        "resolution": assignment.resolution,
        "resolutionNote": assignment.resolution_note,
        "resolvedAt": (
            assignment.resolved_at.isoformat() if assignment.resolved_at else None
        ),
        "replacementAssignmentId": getattr(replacement, "id", None)
        or next(
            iter(assignment.replaced_by.values_list("id", flat=True)[:1]),
            None,
        ),
    }
