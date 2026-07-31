"""Supervisor assignment — CD/HR/Admin sets or changes a staff member's supervisor.

Writes StaffSupervisorAssignment (the load-bearing row for PL team scope:
resolve_user_scope derives a PL's supervised_staff_ids from this table). The
previous assignment (if any) is replaced, and the old→new change is audited.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.rbac import EdifyRole
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

from .models import StaffProfile, StaffSupervisorAssignment


# The role that should supervise each supervisee role (the chain).
_SUPERVISOR_ROLE = {
    EdifyRole.CCEO.value: EdifyRole.COUNTRY_PROGRAM_LEAD.value,  # CCEO → PL
    EdifyRole.COUNTRY_PROGRAM_LEAD.value: EdifyRole.COUNTRY_DIRECTOR.value,  # PL → CD
}


def list_staff(principal=None) -> list[dict]:
    """Staff roster with their supervisor + assigned-school count.

    Backs the CD staff-management page. Takes a principal because the endpoint
    is gated on `staffPerformance.view`, which the Program Lead also holds —
    and the row set includes each person's supervisor, so an unscoped roster
    let one PL enumerate exactly which CCEOs belong to every other PL. A PL is
    narrowed to the staff they supervise; country roles keep the full roster.
    """
    qs = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")
    if principal is not None:
        from apps.core.scoping import resolve_user_scope

        role = getattr(principal, "active_role", "")
        if role != "Admin":
            scope = resolve_user_scope(principal)
            if not scope.country_scope:
                supervised = list(scope.supervised_staff_ids or [])
                own = getattr(principal, "staff_profile_id", None)
                allowed = supervised + ([own] if own else [])
                qs = qs.filter(id__in=allowed or ["__none__"])

    rows = []
    for sp in qs:
        sup_link = sp.supervisor_links.first()
        supervisor = sup_link.supervisor if sup_link else None
        rows.append(
            {
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
            }
        )
    return rows


def assign_supervisor(staff_id: str, data: dict, principal) -> dict:
    """Set or change a staff member's supervisor. Validates the supervisor holds
    the right level (PL supervises CCEO; CD supervises PL). Replaces any prior
    assignment. The old→new change is captured for audit."""
    supervisee = StaffProfile.objects.filter(
        id=staff_id, deleted_at__isnull=True
    ).first()
    if not supervisee:
        raise NotFoundError("Staff member not found.")
    supervisor_id = (
        data.get("supervisorId") or data.get("newSupervisorId") or ""
    ).strip()
    if not supervisor_id:
        raise BadRequest("A supervisorId is required.")
    supervisor = StaffProfile.objects.filter(
        id=supervisor_id, deleted_at__isnull=True
    ).first()
    if not supervisor:
        raise NotFoundError("Supervisor not found.")
    if supervisor.id == supervisee.id:
        raise BadRequest("A staff member cannot supervise themselves.")

    # Level check: the supervisor's role must match the expected level for the
    # supervisee's role (unless the actor is an Admin override).
    expected = _SUPERVISOR_ROLE.get(supervisee.user.active_role)
    if (
        expected
        and supervisor.user.active_role != expected
        and principal.active_role != EdifyRole.ADMIN.value
    ):
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
        supervisee=supervisee,
        defaults={"supervisor": supervisor},
    )

    from apps.audit.services import log as audit_log

    audit_log(
        action="admin.supervisor_reassigned",
        subject_kind="staff_profile",
        subject_id=supervisee.id,
        actor_id=getattr(principal, "id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"oldSupervisorId": old_id, "newSupervisorId": supervisor.id},
    )
    return {
        "staffId": supervisee.id,
        "oldSupervisorId": old_id,
        "newSupervisorId": supervisor.id,
        "newSupervisorName": supervisor.user.name,
        "changedAt": timezone.now().isoformat(),
    }


def configure_program_lead_team(
    program_lead_id: str, cceo_ids: list[str], principal
) -> dict:
    """Replace one Program Lead's CCEO team from Role Configuration.

    The reporting line is the source of truth for team dashboards, approvals,
    targets, and planning scope. A CCEO may have only one effective Program
    Lead: selecting a CCEO already assigned elsewhere moves that relationship
    in the same transaction.
    """
    if getattr(principal, "active_role", None) != EdifyRole.ADMIN.value:
        raise Forbidden("Only an Admin can configure Program Lead teams.")

    selected_ids = list(
        dict.fromkeys(str(cceo_id).strip() for cceo_id in cceo_ids if cceo_id)
    )

    with transaction.atomic():
        program_lead = (
            StaffProfile.objects.select_for_update()
            .select_related("user")
            .filter(id=program_lead_id, deleted_at__isnull=True)
            .filter(
                Q(user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value)
                | Q(user__roles__contains=[EdifyRole.COUNTRY_PROGRAM_LEAD.value])
            )
            .first()
        )
        if not program_lead:
            raise NotFoundError("Program Lead not found.")

        cceos = list(
            StaffProfile.objects.select_for_update()
            .select_related("user")
            .filter(id__in=selected_ids, deleted_at__isnull=True)
            .filter(
                Q(user__active_role=EdifyRole.CCEO.value)
                | Q(user__roles__contains=[EdifyRole.CCEO.value])
            )
        )
        found_ids = {str(cceo.id) for cceo in cceos}
        missing_ids = set(selected_ids) - found_ids
        if missing_ids:
            raise BadRequest("One or more selected CCEOs are unavailable.")

        wrong_country = [
            cceo.user.name
            for cceo in cceos
            if cceo.country != program_lead.country
        ]
        if wrong_country:
            raise BadRequest(
                "A Program Lead can only manage CCEOs in the same country."
            )

        locked_links = list(
            StaffSupervisorAssignment.objects.select_for_update()
            .filter(
                Q(supervisor=program_lead)
                | Q(supervisee_id__in=selected_ids)
            )
            .select_related("supervisor__user")
        )
        current_ids = {
            str(link.supervisee_id)
            for link in locked_links
            if link.supervisor_id == program_lead.id
        }
        previous_leads = {
            str(link.supervisee_id): str(link.supervisor_id)
            for link in locked_links
            if link.supervisor_id != program_lead.id
        }

        selected_set = set(selected_ids)
        removed_ids = sorted(current_ids - selected_set)
        added_ids = sorted(selected_set - current_ids)
        reassigned_ids = sorted(selected_set & set(previous_leads))

        # Remove CCEOs deselected from this lead, plus any competing supervisor
        # links for selected CCEOs. Existing correct links retain their history.
        StaffSupervisorAssignment.objects.filter(supervisor=program_lead).exclude(
            supervisee_id__in=selected_ids
        ).delete()
        if selected_ids:
            StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=selected_ids
            ).exclude(supervisor=program_lead).delete()

        existing_ids = set(
            StaffSupervisorAssignment.objects.filter(
                supervisor=program_lead, supervisee_id__in=selected_ids
            ).values_list("supervisee_id", flat=True)
        )
        StaffSupervisorAssignment.objects.bulk_create(
            [
                StaffSupervisorAssignment(
                    supervisee_id=cceo_id,
                    supervisor=program_lead,
                )
                for cceo_id in selected_ids
                if cceo_id not in existing_ids
            ]
        )

        from apps.audit.services import log as audit_log

        audit_log(
            action="admin.program_lead_team_configured",
            subject_kind="staff_profile",
            subject_id=program_lead.id,
            actor_id=getattr(principal, "id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "programLeadId": str(program_lead.id),
                "cceoIds": selected_ids,
                "addedCceoIds": added_ids,
                "removedCceoIds": removed_ids,
                "reassignedCceoIds": reassigned_ids,
            },
        )

    return {
        "programLeadId": str(program_lead.id),
        "programLeadName": program_lead.user.name,
        "assignedCount": len(selected_ids),
        "addedCount": len(added_ids),
        "removedCount": len(removed_ids),
        "reassignedCount": len(reassigned_ids),
        "changedAt": timezone.now().isoformat(),
    }


__all__ = ["list_staff", "assign_supervisor", "configure_program_lead_team"]
