"""Supervisor assignment — CD/HR/Admin sets or changes a staff member's supervisor.

Writes StaffSupervisorAssignment (the load-bearing row for PL team scope:
resolve_user_scope derives a PL's supervised_staff_ids from this table). The
previous assignment (if any) is replaced, and the old→new change is audited.
"""
from __future__ import annotations

from django.utils import timezone

from apps.core.rbac import EdifyRole
from apps.core.exceptions import BadRequest, NotFoundError

from .models import StaffProfile, StaffSupervisorAssignment


# The role that should supervise each supervisee role (the chain).
_SUPERVISOR_ROLE = {
    EdifyRole.CCEO.value: EdifyRole.COUNTRY_PROGRAM_LEAD.value,        # CCEO → PL
    EdifyRole.COUNTRY_PROGRAM_LEAD.value: EdifyRole.COUNTRY_DIRECTOR.value,  # PL → CD
}


def list_staff() -> list[dict]:
    """Staff roster with their supervisor + assigned-school count — backs the CD
    staff-management page. Each row carries enough for assignment decisions."""
    rows = []
    for sp in StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user"):
        sup_link = sp.supervisor_links.first()
        supervisor = sup_link.supervisor if sup_link else None
        rows.append({
            "id": sp.id,
            "userId": sp.user_id,
            "name": sp.user.name,
            "email": sp.user.email,
            "role": sp.user.active_role,
            "title": sp.title,
            "onboardingState": sp.onboarding_state,
            "supervisorId": supervisor.id if supervisor else None,
            "supervisorName": supervisor.user.name if supervisor else None,
            "assignedSchoolCount": sp.school_links.count(),
            "primaryDistrictId": sp.primary_district_id,
        })
    return rows


def assign_supervisor(staff_id: str, data: dict, principal) -> dict:
    """Set or change a staff member's supervisor. Validates the supervisor holds
    the right level (PL supervises CCEO; CD supervises PL). Replaces any prior
    assignment. The old→new change is captured for audit."""
    supervisee = StaffProfile.objects.filter(id=staff_id, deleted_at__isnull=True).first()
    if not supervisee:
        raise NotFoundError("Staff member not found.")
    supervisor_id = (data.get("supervisorId") or data.get("newSupervisorId") or "").strip()
    if not supervisor_id:
        raise BadRequest("A supervisorId is required.")
    supervisor = StaffProfile.objects.filter(id=supervisor_id, deleted_at__isnull=True).first()
    if not supervisor:
        raise NotFoundError("Supervisor not found.")
    if supervisor.id == supervisee.id:
        raise BadRequest("A staff member cannot supervise themselves.")

    # Level check: the supervisor's role must match the expected level for the
    # supervisee's role (unless the actor is an Admin override).
    expected = _SUPERVISOR_ROLE.get(supervisee.user.active_role)
    if expected and supervisor.user.active_role != expected and principal.active_role != EdifyRole.ADMIN.value:
        raise BadRequest(
            f"A {supervisee.user.active_role} should be supervised by a {expected}, "
            f"not a {supervisor.user.active_role}."
        )

    old = supervisee.supervisor_links.first()
    old_id = old.supervisor_id if old else None
    # Replace the assignment (one supervisor per supervisee — the unique constraint
    # is on (supervisee, supervisor); we remove any prior links first).
    if old and old.supervisor_id != supervisor.id:
        old.delete()
    StaffSupervisorAssignment.objects.update_or_create(
        supervisee=supervisee, defaults={"supervisor": supervisor},
    )
    return {
        "staffId": supervisee.id,
        "oldSupervisorId": old_id,
        "newSupervisorId": supervisor.id,
        "newSupervisorName": supervisor.user.name,
        "changedAt": timezone.now().isoformat(),
    }


__all__ = ["list_staff", "assign_supervisor"]
