"""Onboarding a Cluster Leader (owner, 2026-11-11: "add cluster leader user
category so the staff can onboard them").

A Cluster Leader is a school leader, not staff: the account holds the Cluster
Leader role alone (no web permission, no staff profile) and starts with an
invitation, so nobody but the leader ever knows its password. It may be
created by an Admin, a Programme Lead, or the CCEO responsible for the cluster
the leader will lead. Every other account stays the Admin's alone (owner,
2026-10-09); an email that already belongs to a staff or partner account is
never turned into a leader.

The Go gateway gives the leader the cluster once the account exists
(cluster_leadership.leader_assignment); this module only writes the account.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.models import User
from apps.admin_users.services import _create_invitation
from apps.clusters.models import Cluster
from apps.core.blocking_io_guard import send_after_commit
from apps.core.email import mailer
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.core.scoping import cluster_owner_ids, resolve_user_scope

LEADER = EdifyRole.CLUSTER_LEADER.value
ANY_CLUSTER = {EdifyRole.ADMIN.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}
MAX_NAME = 200
MAX_PHONE = 40


def may_onboard(principal, cluster: Cluster) -> bool:
    """Admin and Programme Lead for any cluster; a CCEO for their own (the
    cluster filed under their user or staff-profile id)."""
    role = getattr(principal, "active_role", "") or ""
    if role in ANY_CLUSTER:
        return True
    if role != EdifyRole.CCEO.value:
        return False
    owner = (cluster.responsible_staff_id or "").strip()
    return bool(owner) and owner in cluster_owner_ids(
        resolve_user_scope(principal), direct_only=True
    )


def _clean(data: dict) -> tuple[str, str, str]:
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    if not name:
        raise BadRequest("The leader's name is required.")
    if len(name) > MAX_NAME or len(phone) > MAX_PHONE:
        raise BadRequest("The name or phone number is too long.")
    if not email:
        raise BadRequest("An email address is required: the invitation goes there.")
    try:
        validate_email(email)
    except DjangoValidationError as error:
        raise BadRequest("Enter a valid email address.") from error
    return name, email, phone


def onboard_cluster_leader(cluster_id: str, data: dict, principal) -> dict:
    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if cluster is None:
        raise NotFoundError("No such cluster.")
    if not may_onboard(principal, cluster):
        raise Forbidden("You may not onboard leaders for this cluster.")
    name, email, phone = _clean(data)

    existing = User.objects.filter(email=email, deleted_at__isnull=True).first()
    if existing is not None:
        if list(existing.roles or []) != [LEADER]:
            raise ConflictError(
                "This email belongs to an Edify staff or partner account. A Cluster Leader needs their own email."
            )
        return {"user": _summary(existing), "existing": True, "inviteToken": None}

    with transaction.atomic():
        user = User.objects.create_user(
            email=email,
            name=name,
            phone=phone or None,
            roles=[LEADER],
            active_role=LEADER,
            password=None,  # set by the leader through the invitation
            status="pending_invited",
            is_active=False,
        )
        token = _create_invitation(user.id, principal.user_id)

    def _notify() -> None:
        mailer.send_invitation(
            to=email, name=name, invited_by_name=principal.name, token=token
        )

    send_after_commit(_notify)

    from apps.audit.services import log as audit_log

    audit_log(
        action="cluster_leader.onboarded",
        subject_kind="user",
        subject_id=user.id,
        actor_id=principal.id,
        actor_role=getattr(principal, "active_role", None),
        payload={"email": email, "clusterId": cluster.id},
    )
    return {
        "user": _summary(user),
        "existing": False,
        # Handed back only when email cannot reach the leader, so the person
        # onboarding them can pass the link on.
        "inviteToken": None if mailer.is_configured else token,
    }


def _summary(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "status": user.status,
    }
