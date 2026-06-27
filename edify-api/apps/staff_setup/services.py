"""Staff-setup candidate service — Admin resolution of uploaded staff names.

Three resolution paths:
  • create_user  — Admin adds an email (+phone, role); a User + StaffProfile are
                   created (pending_invited). ALL schools whose account_owner_name_raw
                   normalizes to this candidate's name are linked to the new staff
                   via StaffSchoolAssignment + flipped to account_owner_status=matched.
  • match_existing — Admin picks an existing user id; the same school re-link happens;
                     the candidate is marked merged.
  • ignore       — invalid name; candidate marked ignored (schools keep raw name).
"""
from __future__ import annotations

from django.db import transaction

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSetupCandidate,
    StaffSetupCandidateStatus,
    User,
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
    schools = School.objects.filter(id__in=(c.sample_school_ids or [])).values("school_id", "name", "district__name")
    data["sampleSchools"] = [{"schoolId": s["school_id"], "name": s["name"], "district": s["district__name"]} for s in schools]
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
    if role not in ("CCEO", "CountryProgramLead"):
        raise BadRequest("Role must be CCEO or PL.")

    with transaction.atomic():
        if User.objects.filter(email=email).exists():
            raise BadRequest(f"A user with email {email} already exists — use 'match existing user' instead.")
        user = User.objects.create_user(
            email=email,
            name=c.full_name,
            roles=[role],
            active_role=role,
            password=None,  # invited — sets an unusable password
            is_active=True,
        )
        user.status = "pending_invited"
        if data.get("phone"):
            user.phone = data["phone"]
        user.save()
        sp = StaffProfile.objects.create(user=user, title=role)

        _link_schools(c, sp.id)
        c.matched_user_id = user.id
        c.email = email
        c.phone = data.get("phone") or c.phone
        c.suggested_role = role
        c.status = StaffSetupCandidateStatus.ACTIVE.value
        c.save(update_fields=["matched_user_id", "email", "phone", "suggested_role", "status", "updated_at"])
    return _serialize(c)


def match_existing(candidate_id: str, data: dict, principal) -> dict:
    """Merge a candidate with an existing user (by user id). Links the affected
    schools to that user's staff profile. Candidate → merged."""
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
        _link_schools(c, sp.id)
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


def _link_schools(candidate: StaffSetupCandidate, staff_profile_id: str) -> tuple[int, int]:
    """Link every School whose account_owner_name_raw normalizes to the
    candidate's name to the resolved staff profile. Writes StaffSchoolAssignment
    (so the schools enter planning scope) + updates account_owner_* fields.

    Returns (schools_linked, assignments_created)."""
    norm = candidate.normalized_name
    # Schools whose raw owner name normalizes to this candidate.
    affected = [s for s in School.objects.filter(account_owner_name_raw__isnull=False) if normalize_name(s.account_owner_name_raw) == norm]
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
        for s in affected if s.id not in existing
    ]
    if new_assignments:
        StaffSchoolAssignment.objects.bulk_create(new_assignments)
    return len(affected), len(new_assignments)


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
