"""Staff-setup candidate service — Admin resolution of uploaded staff names.

Three resolution paths:
  • create_user  — Admin adds an email (+phone, role); a User + StaffProfile are
                   created (pending_invited). ALL schools whose account_owner_name_raw
                   normalizes to this candidate's name are linked to the new staff
                   via StaffSchoolAssignment + flipped to account_owner_status=matched.
  • match_existing — Admin picks an existing user id; the same school re-link
                     happens, the placeholder's own work is carried across to
                     the real person, and the candidate is marked merged.
  • ignore       — invalid name; candidate marked ignored (schools keep raw name).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSetupCandidate,
    StaffSetupCandidateStatus,
    User,
    UserStatus,
)
from apps.accounts.staff_matching import normalize_name
from apps.core.enums import AccountOwnerStatus
from apps.core.exceptions import BadRequest, NotFoundError
from apps.schools.models import School


def list_candidates(query: dict) -> list[dict]:
    """Pending/active candidates, newest first. Optionally filter by status."""
    qs = StaffSetupCandidate.objects.all().order_by("-created_at")
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    return [_serialize(c) for c in qs[:200]]


def get_one(candidate_id: str) -> dict:
    c = StaffSetupCandidate.objects.filter(id=candidate_id).first()
    if not c:
        raise NotFoundError("Staff candidate not found.")
    data = _serialize(c)
    # Resolve the sample schools for the Admin to preview.
    schools = School.objects.filter(id__in=(c.sample_school_ids or [])).values(
        "school_id", "name", "district__name"
    )
    data["sampleSchools"] = [
        {"schoolId": s["school_id"], "name": s["name"], "district": s["district__name"]}
        for s in schools
    ]
    return data


def create_user(candidate_id: str, data: dict, principal) -> dict:
    """Create a User + StaffProfile from a candidate, then link every affected
    school. Requires email + role. Sends an invitation (pending_invited)."""
    c = StaffSetupCandidate.objects.filter(id=candidate_id).first()
    if not c:
        raise NotFoundError("Staff candidate not found.")
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "CCEO").strip()
    if not email:
        raise BadRequest("An email is required to create the staff profile.")
    if role not in ("CCEO", "Program Lead"):
        raise BadRequest("Role must be CCEO or PL.")

    with transaction.atomic():
        if c.matched_user_id:
            user = User.objects.filter(id=c.matched_user_id).first()
            if not user:
                raise NotFoundError("Matched user not found.")
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                raise BadRequest(f"A user with email {email} already exists.")
            user.email = email
            user.roles = [role]
            user.active_role = role
            user.is_active = True
            user.status = "pending_invited"
            if data.get("phone"):
                user.phone = data["phone"]
            user.save()

            sp, _ = StaffProfile.objects.get_or_create(
                user=user, defaults={"title": role}
            )
            if sp.title != role:
                sp.title = role
                sp.save(update_fields=["title"])
        else:
            if User.objects.filter(email=email).exists():
                raise BadRequest(
                    f"A user with email {email} already exists — use 'match existing user' instead."
                )
            user = User.objects.create_user(
                email=email,
                name=c.full_name,
                roles=[role],
                active_role=role,
                password=None,
                is_active=True,
            )
            user.status = "pending_invited"
            if data.get("phone"):
                user.phone = data["phone"]
            user.save()
            sp = StaffProfile.objects.create(user=user, title=role)

        _link_schools(c, sp.id, principal)
        c.matched_user_id = user.id
        c.email = email
        c.phone = data.get("phone") or c.phone
        c.suggested_role = role
        c.status = StaffSetupCandidateStatus.ACTIVE.value
        c.save(
            update_fields=[
                "matched_user_id",
                "email",
                "phone",
                "suggested_role",
                "status",
                "updated_at",
            ]
        )

        # status="pending_invited" above means the account cannot actually
        # authenticate (LockoutEnforcingModelBackend requires status ==
        # "active") until an invitation is accepted — this used to be a
        # dead end: nothing on this path ever created the UserInvitation
        # the login gate is waiting on.
        from apps.admin_users.services import _create_invitation
        from apps.core.email import mailer

        invite_token = _create_invitation(user.id, getattr(principal, "id", None))

    mailer.send_invitation(
        to=email, name=user.name, invited_by_name=principal.name, token=invite_token
    )

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.user_created",
        subject_kind="user",
        subject_id=user.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"email": email, "roles": [role], "source": "staff_setup"},
    )
    return _serialize(c)


def match_existing(candidate_id: str, data: dict, principal) -> dict:
    """Merge a candidate with an existing user (by user id).

    Links the affected schools to that user's staff profile AND carries the
    placeholder's own work across — see `_absorb_placeholder`. Candidate →
    merged.
    """
    c = StaffSetupCandidate.objects.filter(id=candidate_id).first()
    if not c:
        raise NotFoundError("Staff candidate not found.")
    user_id = (data.get("userId") or "").strip()
    if not user_id:
        raise BadRequest("An existing userId is required.")
    user = User.objects.filter(id=user_id).first()
    if not user:
        raise NotFoundError("User not found.")
    sp = getattr(user, "staff_profile", None)
    if sp is None:
        sp = StaffProfile.objects.create(user=user, title=user.active_role)

    with transaction.atomic():
        _link_schools(c, sp.id, principal)
        # Before repointing the candidate: the placeholder it currently names
        # is about to stop being anybody's account, and everything it owns has
        # to go somewhere first.
        _absorb_placeholder(c, target_user=user, target_profile=sp, principal=principal)
        c.matched_user_id = user.id
        c.status = StaffSetupCandidateStatus.MERGED.value
        c.save(update_fields=["matched_user_id", "status", "updated_at"])
    return _serialize(c)


def ignore(candidate_id: str, principal) -> dict:
    c = StaffSetupCandidate.objects.filter(id=candidate_id).first()
    if not c:
        raise NotFoundError("Staff candidate not found.")
    c.status = StaffSetupCandidateStatus.IGNORED.value
    c.save(update_fields=["status", "updated_at"])
    return _serialize(c)


def _link_schools(
    candidate: StaffSetupCandidate, staff_profile_id: str, principal=None
) -> tuple[int, int]:
    """Link every School whose account_owner_name_raw normalizes to the
    candidate's name to the resolved staff profile. Writes StaffSchoolAssignment
    (so the schools enter planning scope) + updates account_owner_* fields.

    Returns (schools_linked, assignments_created)."""
    norm = candidate.normalized_name
    # Schools whose raw owner name normalizes to this candidate.
    affected = [
        s
        for s in School.objects.filter(account_owner_name_raw__isnull=False)
        if normalize_name(s.account_owner_name_raw) == norm
    ]
    if not affected:
        return 0, 0
    # Bulk-update the school owner fields.
    School.objects.filter(id__in=[s.id for s in affected]).update(
        account_owner_id=staff_profile_id,
        account_owner_status=AccountOwnerStatus.MATCHED.value,
    )
    # Write StaffSchoolAssignment rows (idempotent — skip existing).
    existing = set(
        StaffSchoolAssignment.objects.filter(
            staff_id=staff_profile_id, school_id__in=[s.id for s in affected]
        ).values_list("school_id", flat=True)
    )
    new_assignments = [
        StaffSchoolAssignment(staff_id=staff_profile_id, school_id=s.id)
        for s in affected
        if s.id not in existing
    ]
    if new_assignments:
        StaffSchoolAssignment.objects.bulk_create(new_assignments)

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.schools_reassigned",
        subject_kind="staff_profile",
        subject_id=staff_profile_id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"schoolIds": [s.id for s in affected]},
    )
    return len(affected), len(new_assignments)


def _absorb_placeholder(
    candidate: StaffSetupCandidate, *, target_user, target_profile, principal=None
) -> dict:
    """Carry a placeholder's work across to the real person, then retire it.

    A school import that names an owner with no account creates a placeholder
    User + StaffProfile (`upload_service._ensure_staff_for_owner_name`) and
    assigns the school to it. Work then gets planned against those schools and
    recorded against the placeholder.

    `_link_schools` moves the *schools*. Without this, the *work* stayed
    behind: the admin resolves the queue, the schools reassign, the candidate
    reads "merged" — and every activity the placeholder owned stays attributed
    to an account nobody can sign in as. The real person inherits their schools
    with none of their own history, and the activities are stranded for good,
    because the placeholder is never resolved a second time.

    Only genuine placeholders are absorbed: an account somebody has actually
    used is somebody's, and merging it away would be destroying real access
    rather than tidying an import artefact.
    """
    placeholder_user_id = candidate.matched_user_id
    if not placeholder_user_id or placeholder_user_id == target_user.id:
        return {"absorbed": False}

    placeholder = User.objects.filter(id=placeholder_user_id).first()
    if placeholder is None or not _is_import_placeholder(placeholder):
        return {"absorbed": False}

    placeholder_profile = StaffProfile.all_objects.filter(user=placeholder).first()

    # responsible_staff_id and monitored_by_staff_id hold EITHER a StaffProfile
    # id or a User id depending on which path wrote them, so each space is
    # rewritten to its own counterpart. Collapsing both onto one space here
    # would silently disown whichever half of the work used the other.
    spaces = [(placeholder.id, target_user.id)]
    if placeholder_profile is not None:
        spaces.append((placeholder_profile.id, target_profile.id))

    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning.action_models import TeamAction

    moved = {"activities": 0, "assignments": 0, "actions": 0}
    for old_id, new_id in spaces:
        moved["activities"] += Activity.objects.filter(
            responsible_staff_id=old_id
        ).update(responsible_staff_id=new_id)
        moved["activities"] += Activity.objects.filter(
            monitored_by_staff_id=old_id
        ).update(monitored_by_staff_id=new_id)
        moved["assignments"] += PartnerAssignment.objects.filter(
            monitoring_staff_id=old_id
        ).update(monitoring_staff_id=new_id)
        moved["assignments"] += PartnerAssignment.objects.filter(
            assigning_staff_id=old_id
        ).update(assigning_staff_id=new_id)

    # An open action addressed to an account nobody can sign in as is exactly
    # the dead record the oversight pages exist to surface. Move it with the
    # rest rather than leaving it in a queue no one reads.
    moved["actions"] = TeamAction.objects.filter(recipient_id=placeholder.id).update(
        recipient_id=target_user.id
    )

    # Its school assignments are redundant now that _link_schools has written
    # the target's, and leaving them would keep the placeholder in scope
    # queries as a second owner of the same schools.
    if placeholder_profile is not None:
        StaffSchoolAssignment.objects.filter(staff_id=placeholder_profile.id).delete()
        placeholder_profile.deleted_at = timezone.now()
        placeholder_profile.save(update_fields=["deleted_at"])

    placeholder.status = UserStatus.DISABLED.value
    placeholder.is_active = False
    placeholder.save(update_fields=["status", "is_active"])

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.placeholder_absorbed",
        subject_kind="user",
        subject_id=target_user.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "placeholder_user_id": placeholder.id,
            "placeholder_email": placeholder.email,
            **moved,
        },
    )
    return {"absorbed": True, **moved}


def _is_import_placeholder(user) -> bool:
    """A never-used account the school import invented, not a real person's.

    Both conditions are required. The `pending.` prefix alone is not enough —
    an admin may have created a real account and not yet invited it — and
    `pending_invited` alone certainly is not, since that is the normal state
    of every genuine invitation awaiting its first sign-in.
    """
    return bool(
        (user.email or "").startswith("pending.")
        and user.status == UserStatus.PENDING_INVITED.value
    )


def _serialize(c: StaffSetupCandidate) -> dict:
    return {
        "id": c.id,
        "fullName": c.full_name,
        "normalizedName": c.normalized_name,
        "schoolCount": c.school_count,
        "suggestedRole": c.suggested_role,
        "email": c.email,
        "phone": c.phone,
        "status": c.status,
        "matchedUserId": c.matched_user_id,
        "createdAt": c.created_at.isoformat() if c.created_at else None,
    }


__all__ = ["list_candidates", "get_one", "create_user", "match_existing", "ignore"]
