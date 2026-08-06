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

_MANAGER_ROLES = {
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
}
_COUNTRY_DIRECTOR_DEFAULT_ROLES = {
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.PROGRAM_ACCOUNTANT.value,
    EdifyRole.CCEO.value,
}
_INTERNAL_MANAGED_ROLES = {
    role.value
    for role in EdifyRole
    if role
    not in {
        EdifyRole.ADMIN,
        EdifyRole.PARTNER_ADMIN,
        EdifyRole.PARTNER_FIELD_OFFICER,
    }
}


def _management_role(user) -> str | None:
    """Return the effective management role, preferring the active role."""
    if user.active_role in _MANAGER_ROLES:
        return user.active_role
    return next((role for role in (user.roles or []) if role in _MANAGER_ROLES), None)


def _profile_role_query(prefix: str, role: str) -> Q:
    """Match a StaffProfile relation whose user holds a role."""
    return Q(**{f"{prefix}__user__active_role": role}) | Q(
        **{f"{prefix}__user__roles__contains": [role]}
    )


def _eligible_managed_people(manager: StaffProfile, manager_role: str):
    """Same-country staff an Admin may place under this manager."""
    candidates = (
        StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__deleted_at__isnull=True,
            country=manager.country,
        )
        .exclude(id=manager.id)
        .select_related("user")
        .order_by("user__name")
    )
    if manager_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return [
            staff
            for staff in candidates
            if EdifyRole.CCEO.value
            in {staff.user.active_role, *(staff.user.roles or [])}
        ]
    allowed_roles = (
        _COUNTRY_DIRECTOR_DEFAULT_ROLES
        if manager_role == EdifyRole.COUNTRY_DIRECTOR.value
        else _INTERNAL_MANAGED_ROLES
    )
    return [
        staff
        for staff in candidates
        if {staff.user.active_role, *(staff.user.roles or [])} & allowed_roles
    ]


def managed_people_team(manager: StaffProfile) -> dict | None:
    """Build the Admin role-configuration card for a management-capable user.

    Country Directors receive their country team automatically. Other
    management roles are explicit so Admin can model the actual organisation.
    """
    manager_role = _management_role(manager.user)
    if not manager_role:
        return None

    people = _eligible_managed_people(manager, manager_role)
    automatic = manager_role == EdifyRole.COUNTRY_DIRECTOR.value
    assigned_ids = (
        {str(person.id) for person in people}
        if automatic
        else set(
            StaffSupervisorAssignment.objects.filter(supervisor=manager).values_list(
                "supervisee_id", flat=True
            )
        )
    )
    if manager_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        assigned_ids.update(
            str(staff_id)
            for staff_id in StaffSupervisorAssignment.objects.filter(
                supervisor=manager
            ).values_list("supervisee_id", flat=True)
        )

    other_leads_by_staff: dict[str, list[str]] = {}
    if manager_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        links = (
            StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=[person.id for person in people]
            )
            .filter(
                _profile_role_query("supervisor", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
            )
            .select_related("supervisor__user")
        )
        for link in links:
            if link.supervisor_id != manager.id:
                other_leads_by_staff.setdefault(str(link.supervisee_id), []).append(
                    link.supervisor.user.name
                )

    return {
        "role": manager_role,
        "country": manager.country,
        "automatic": automatic,
        "assigned_count": len(assigned_ids),
        "people": [
            {
                "id": person.id,
                "name": person.user.name,
                "email": person.user.email,
                "role": person.user.active_role,
                "status": person.user.status,
                "assigned": str(person.id) in assigned_ids,
                "other_manager": ", ".join(
                    other_leads_by_staff.get(str(person.id), [])
                ),
            }
            for person in people
        ],
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
        expected_role = _SUPERVISOR_ROLE.get(sp.user.active_role)
        direct_links = sp.supervisor_links.select_related("supervisor__user")
        if expected_role:
            direct_links = direct_links.filter(
                _profile_role_query("supervisor", expected_role)
            )
        sup_link = direct_links.first()
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

    direct_links = supervisee.supervisor_links.select_related("supervisor__user")
    if expected:
        direct_links = direct_links.filter(_profile_role_query("supervisor", expected))
    old = direct_links.first()
    old_id = old.supervisor_id if old else None
    # Replace only the direct reporting line. IA/RVP oversight rows for the
    # same person stay intact.
    if old and old.supervisor_id != supervisor.id:
        old.delete()
        old = None
    if old is None:
        StaffSupervisorAssignment.objects.get_or_create(
            supervisee=supervisee,
            supervisor=supervisor,
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
            cceo.user.name for cceo in cceos if cceo.country != program_lead.country
        ]
        if wrong_country:
            raise BadRequest(
                "A Program Lead can only manage CCEOs in the same country."
            )

        competing_program_lead = _profile_role_query(
            "supervisor", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        locked_links = list(
            StaffSupervisorAssignment.objects.select_for_update()
            .filter(
                Q(supervisor=program_lead)
                | (Q(supervisee_id__in=selected_ids) & competing_program_lead)
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
            ).filter(competing_program_lead).exclude(supervisor=program_lead).delete()

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


def configure_managed_people(
    manager_id: str, managed_staff_ids: list[str], principal
) -> dict:
    """Replace the explicit managed-people list for PL, IA, or RVP.

    PL assignments also update the direct reporting relationship because that
    relationship powers approvals and PL team scope. IA/RVP oversight remains
    deliberately separate so it can overlap a person's reporting line. A CD's
    country team is derived automatically and therefore cannot drift through a
    manually maintained list.
    """
    if getattr(principal, "active_role", None) != EdifyRole.ADMIN.value:
        raise Forbidden("Only an Admin can configure managed people.")

    selected_ids = list(
        dict.fromkeys(
            str(staff_id).strip() for staff_id in managed_staff_ids if staff_id
        )
    )

    with transaction.atomic():
        manager = (
            StaffProfile.objects.select_for_update()
            .select_related("user")
            .filter(id=manager_id, deleted_at__isnull=True)
            .first()
        )
        if not manager:
            raise NotFoundError("Manager profile not found.")

        manager_role = _management_role(manager.user)
        if not manager_role:
            raise BadRequest(
                "Managed people can only be configured for PL, CD, IA, or RVP roles."
            )
        if manager_role == EdifyRole.COUNTRY_DIRECTOR.value:
            raise BadRequest(
                "Country Directors automatically manage every PL, IA, Accountant, "
                "and CCEO in their country."
            )

        eligible = _eligible_managed_people(manager, manager_role)
        eligible_ids = {str(person.id) for person in eligible}
        if set(selected_ids) - eligible_ids:
            if manager_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
                raise BadRequest(
                    "A Program Lead can only manage CCEOs in the same country."
                )
            raise BadRequest(
                f"A {manager_role} can only manage eligible staff in the same country."
            )

        # Preserve the existing PL reporting-line semantics while recording
        # the new generic management relationship for the shared UI.
        if manager_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            configure_program_lead_team(manager.id, selected_ids, principal)

        previous_ids = set(
            str(staff_id)
            for staff_id in StaffSupervisorAssignment.objects.select_for_update()
            .filter(supervisor=manager)
            .values_list("supervisee_id", flat=True)
        )
        selected_set = set(selected_ids)
        StaffSupervisorAssignment.objects.filter(supervisor=manager).exclude(
            supervisee_id__in=selected_ids
        ).delete()
        existing_ids = set(
            str(staff_id)
            for staff_id in StaffSupervisorAssignment.objects.filter(
                supervisor=manager,
                supervisee_id__in=selected_ids,
            ).values_list("supervisee_id", flat=True)
        )
        StaffSupervisorAssignment.objects.bulk_create(
            [
                StaffSupervisorAssignment(
                    supervisor=manager,
                    supervisee_id=staff_id,
                )
                for staff_id in selected_ids
                if staff_id not in existing_ids
            ]
        )

        from apps.audit.services import log as audit_log

        audit_log(
            action="admin.managed_people_configured",
            subject_kind="staff_profile",
            subject_id=manager.id,
            actor_id=getattr(principal, "id", None),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "managerRole": manager_role,
                "managedStaffIds": selected_ids,
                "addedStaffIds": sorted(selected_set - previous_ids),
                "removedStaffIds": sorted(previous_ids - selected_set),
            },
        )

    return {
        "managerId": str(manager.id),
        "managerName": manager.user.name,
        "managerRole": manager_role,
        "assignedCount": len(selected_ids),
        "changedAt": timezone.now().isoformat(),
    }


__all__ = [
    "list_staff",
    "assign_supervisor",
    "configure_program_lead_team",
    "configure_managed_people",
    "managed_people_team",
]
