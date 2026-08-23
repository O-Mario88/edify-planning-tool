"""Special-projects service — project directory + school/partner assignment + impact."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Prefetch, Q

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission

from .models import (
    OPEN_PROJECT_STATUSES,
    Project,
    ProjectCategory,
    ProjectPartnerAssignment,
    ProjectSchoolAssignment,
    ProjectSchoolFocus,
    ProjectStaffAssignment,
    ProjectStatus,
)

# Country-scoped roles may act on any Project. Project Coordinators now hold
# PROJECT_CONFIGURE_PRIORITIES too, but remain object-scoped to Projects they
# manage; keeping this set narrow prevents that permission from widening school
# assignment beyond their portfolio.
PROJECT_COUNTRY_ASSIGNER_ROLES = {
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.ADMIN.value,
}


def _assert_project_configurer(principal) -> None:
    from apps.core.exceptions import Forbidden

    if principal is None or not has_permission(
        principal,
        Permission.PROJECT_CONFIGURE_PRIORITIES.value,
    ):
        raise Forbidden(
            "Only a Special Project Coordinator, Impact Assessment, the "
            "Country Director, or Admin may create Projects and assign them "
            "as staff priorities."
        )


def list_projects(principal=None) -> list[dict]:
    # Unscoped by default only for internal callers that have already scoped;
    # every request path passes a principal.
    if principal is None:
        projects = Project.objects.filter(deleted_at__isnull=True)
        return [_serialize(p) for p in _serialization_queryset(projects)]
    from .scoping import scoped_projects

    return [_serialize(p) for p in _serialization_queryset(scoped_projects(principal))]


def get_one(project_id: str, principal=None) -> dict:
    if principal is not None:
        from .scoping import get_scoped_project

        return _serialize(get_scoped_project(project_id, principal))
    else:
        p = (
            _serialization_queryset(Project.objects.filter(deleted_at__isnull=True))
            .filter(id=project_id)
            .first()
        )
    if not p:
        raise NotFoundError("Project not found.")
    return _serialize(p)


def _serialization_queryset(queryset):
    from apps.activity_catalogue.models import ActivityProjectMapping

    return (
        queryset.annotate(
            serialized_school_count=Count("school_assignments", distinct=True),
            serialized_partner_count=Count("partner_assignments", distinct=True),
            serialized_staff_count=Count(
                "staff_assignments",
                filter=Q(staff_assignments__is_active=True),
                distinct=True,
            ),
        )
        .prefetch_related(
            Prefetch(
                "allowed_catalogue_activities",
                queryset=ActivityProjectMapping.objects.filter(
                    active=True
                ).select_related("catalogue_item"),
                to_attr="serialized_catalogue_activities",
            )
        )
        .order_by("name")
    )


def impact(project_id: str, principal=None) -> list[dict]:
    if principal is not None:
        from .scoping import get_scoped_project

        p = get_scoped_project(project_id, principal)
    else:
        p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    return [
        {"fy": s.fy, "metrics": s.metrics_json, "createdAt": s.created_at.isoformat()}
        for s in p.impact_snapshots.order_by("-fy")
    ]


def partners(project_id: str) -> list[dict]:
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    return [
        {"id": a.partner_id, "name": a.partner.name}
        for a in p.partner_assignments.select_related("partner")
    ]


def evaluate_school_need(project, school) -> str | None:
    """Return the first project target intervention the school's latest
    CONFIRMED SSA is genuinely weak in (< 7.0), or None. None with declared
    targets means the assignment is off-recommendation and needs a reason."""
    targets = project.target_intervention_list()
    if not targets:
        return None
    from apps.ssa.services import latest_applicable_record

    record = latest_applicable_record(school)
    if not record:
        return None
    weak = {
        row["intervention"]
        for row in record.scores.all().values("intervention", "score")
        if (row["score"] or 0) < 7.0
    }
    return next((t for t in targets if t in weak), None)


def school_project_limit(school) -> int:
    """Client Schools carry one Project; Core Schools may carry four."""
    return 4 if school.school_type == "core" else 1


def _assert_school_capacity(project, school) -> None:
    if project.school_focus == ProjectSchoolFocus.CORE and school.school_type != "core":
        raise BadRequest(
            f"'{project.name}' is limited to Core Schools; {school.name} is "
            f"classified as {school.get_school_type_display()}."
        )
    if (
        project.school_focus == ProjectSchoolFocus.CLIENT
        and school.school_type == "core"
    ):
        raise BadRequest(
            f"'{project.name}' is limited to Client Schools; {school.name} is Core."
        )
    active_count = (
        ProjectSchoolAssignment.objects.filter(
            school=school,
            project__deleted_at__isnull=True,
            project__status__in=[status.value for status in OPEN_PROJECT_STATUSES],
        )
        .exclude(project=project)
        .count()
    )
    limit = school_project_limit(school)
    if active_count >= limit:
        label = "Core School" if limit == 4 else "Client School"
        raise BadRequest(
            f"{school.name} is a {label} and already has its maximum of "
            f"{limit} active Project{'s' if limit != 1 else ''}."
        )


def _assert_staff_can_plan_project(project, school, principal) -> None:
    if principal is None or getattr(principal, "active_role", "") in (
        PROJECT_COUNTRY_ASSIGNER_ROLES
    ):
        return
    from apps.core.exceptions import Forbidden
    from apps.core.scoping import resolve_user_scope

    staff_id = getattr(principal, "staff_profile_id", None)
    assigned = staff_id and (
        str(project.manager_staff_id or "") == str(staff_id)
        or ProjectStaffAssignment.objects.filter(
            project=project,
            staff_id=staff_id,
            is_active=True,
        ).exists()
    )
    if not assigned:
        raise Forbidden("This Project is not assigned to you as a staff priority.")
    scope = resolve_user_scope(principal)
    if school.id not in set(scope.school_ids or []):
        raise Forbidden("You may add only Schools in your own or supervised portfolio.")


@transaction.atomic
def assign_school(project_id: str, data: dict, principal=None) -> dict:
    """Assign a school to a Special Project using verified SSA need.

    Ecosystem rule: if the project declares target interventions, the school's
    latest CONFIRMED SSA must show genuine weakness (< 7.0) in at least one of
    them — otherwise assignment requires an explicit override reason, which is
    persisted on the assignment. Schools with no confirmed SSA also require a
    reason (never fabricate need)."""
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    assert_accepts_new_work(p)
    from apps.schools.models import School

    school = (
        School.objects.select_for_update()
        .filter(school_id=data.get("schoolId"))
        .first()
    )
    if not school:
        raise BadRequest("Unknown school.")
    _assert_staff_can_plan_project(p, school, principal)
    _assert_school_capacity(p, school)

    targets = p.target_intervention_list()
    reason = (data.get("reason") or data.get("notes") or "").strip()
    matched = evaluate_school_need(p, school)
    if targets and not matched and not reason:
        raise BadRequest(
            "This school's confirmed SSA shows no weakness in the project's "
            "target interventions — provide an override reason to assign it "
            "anyway."
        )

    assignment, _created = ProjectSchoolAssignment.objects.get_or_create(
        project=p,
        school=school,
        defaults={
            "assigned_by": (getattr(principal, "user_id", None) if principal else None),
            "project_type": data.get("projectType") or None,
            "participation_type": data.get("participationType") or None,
            "start_date": data.get("startDate") or None,
            "support_area": data.get("supportArea") or None,
            "notes": data.get("notes") or None,
        },
    )
    updates = []
    if matched and assignment.matched_intervention != matched:
        assignment.matched_intervention = matched
        updates.append("matched_intervention")
    if reason and assignment.assignment_reason != reason:
        assignment.assignment_reason = reason
        updates.append("assignment_reason")

    # The baseline is what the school scored the day it joined, captured once
    # and never recomputed. Reading it live would let an assessment taken
    # during delivery become the thing delivery is judged against, which
    # flatters or damns a project by accident of timing.
    #
    # A school with no confirmed assessment gets no baseline rather than a
    # zero: it is enrolled, and the project simply cannot claim SSA movement
    # for it until one exists.
    if assignment.baseline_score is None:
        _capture_baseline(assignment, matched or (p.intervention or ""))
        updates.extend(
            [
                "baseline_ssa",
                "baseline_score",
                "baseline_band",
                "baseline_captured_at",
                "impact_classification",
            ]
        )

    if updates:
        assignment.save(update_fields=[*updates, "updated_at"])
    return {"ok": True, "projectId": project_id, "schoolId": school.school_id}


def _capture_baseline(assignment, intervention: str) -> None:
    """Snapshot the score this enrolment will later be measured against."""
    from django.utils import timezone

    from apps.projects.ssa_impact import Impact, baseline_for

    if not intervention:
        # Nothing to measure against yet. Honest, and visible to IA as a
        # project school awaiting a baseline.
        assignment.impact_classification = Impact.INSUFFICIENT_EVIDENCE
        return

    reading = baseline_for(assignment.school_id, intervention)
    if reading is None:
        assignment.impact_classification = Impact.INSUFFICIENT_EVIDENCE
        return

    assignment.baseline_ssa_id = reading.record_id
    assignment.baseline_score = reading.score
    assignment.baseline_band = reading.band
    assignment.baseline_captured_at = timezone.now()
    assignment.impact_classification = Impact.NOT_YET_MEASURABLE


def staff_assignments(project_id: str, principal=None) -> list[dict]:
    if principal is not None:
        from .scoping import get_scoped_project

        project = get_scoped_project(project_id, principal)
    else:
        project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not project:
        raise NotFoundError("Project not found.")
    return [
        {
            "id": assignment.id,
            "staffId": assignment.staff_id,
            "staffName": assignment.staff.user.name,
            "role": assignment.staff.user.active_role,
            "responsibility": assignment.responsibility,
            "fy": assignment.fy,
            "status": "active" if assignment.is_active else "revoked",
            "startDate": assignment.start_date,
            "dueDate": assignment.due_date,
        }
        for assignment in project.staff_assignments.select_related(
            "staff__user"
        ).order_by("-fy", "staff__user__name")
    ]


@transaction.atomic
def assign_staff(project_id: str, data: dict, principal) -> dict:
    """Assign one Project to selected staff or complete CCEO/PL role groups."""
    _assert_project_configurer(principal)
    if principal.active_role == EdifyRole.PROJECT_COORDINATOR.value:
        # Permission answers *what* a coordinator may do; project scope answers
        # *where*. Do not let the new authoring permission cross coordinator
        # portfolio boundaries.
        from .scoping import get_scoped_project

        get_scoped_project(project_id, principal)
    project = (
        Project.objects.select_for_update()
        .filter(
            id=project_id,
            deleted_at__isnull=True,
        )
        .first()
    )
    if not project:
        raise NotFoundError("Project not found.")
    assert_accepts_new_work(project)
    raw_ids = data.get("staffIds") or []
    if isinstance(raw_ids, str):
        raw_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]
    role_groups = data.get("roleGroups") or []
    if isinstance(role_groups, str):
        role_groups = [
            value.strip() for value in role_groups.split(",") if value.strip()
        ]
    allowed_groups = {
        EdifyRole.CCEO.value,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    }
    unknown_groups = set(role_groups) - allowed_groups
    if unknown_groups:
        raise BadRequest("Role groups may be CCEO or Program Lead.")

    from apps.accounts.models import StaffProfile
    from apps.core.fy import get_operational_fy

    candidates = list(
        StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__status="active",
            user__deleted_at__isnull=True,
        ).select_related("user")
    )
    selected = {
        str(staff.id): staff
        for staff in candidates
        if str(staff.id) in {str(value) for value in raw_ids}
        or bool(set(staff.user.roles or []) & set(role_groups))
    }
    if not selected:
        raise BadRequest("Select at least one staff member or role group.")
    responsibility = (data.get("responsibility") or "execute").strip()
    if responsibility not in {"execute", "supervise"}:
        raise BadRequest("Responsibility must be execute or supervise.")
    start_date = data.get("startDate") or None
    due_date = data.get("dueDate") or None
    fy = (
        data.get("fy") or project.measurement_start_fy or get_operational_fy()
    ).strip()
    created = reactivated = 0
    for staff in selected.values():
        assignment, was_created = ProjectStaffAssignment.objects.update_or_create(
            project=project,
            staff=staff,
            fy=fy,
            defaults={
                "responsibility": responsibility,
                "is_active": True,
                "assigned_by": (
                    getattr(principal, "user_id", None) or str(principal.id)
                ),
                "assigned_by_role": principal.active_role,
                "start_date": start_date,
                "due_date": due_date,
                "notes": (data.get("notes") or "").strip(),
            },
        )
        created += int(was_created)
        reactivated += int(not was_created)
    from apps.audit.services import log as audit_log

    audit_log(
        action="project.assign_staff_priorities",
        subject_kind="Project",
        subject_id=project.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=principal.active_role,
        payload={
            "staffIds": sorted(selected),
            "roleGroups": role_groups,
            "responsibility": responsibility,
        },
    )
    return {
        "ok": True,
        "projectId": project.id,
        "assigned": len(selected),
        "created": created,
        "reactivated": reactivated,
    }


@transaction.atomic
def revoke_staff(project_id: str, staff_id: str, principal) -> dict:
    _assert_project_configurer(principal)
    if principal.active_role == EdifyRole.PROJECT_COORDINATOR.value:
        from .scoping import get_scoped_project

        get_scoped_project(project_id, principal)
    updated = ProjectStaffAssignment.objects.filter(
        project_id=project_id,
        staff_id=staff_id,
        is_active=True,
    ).update(is_active=False)
    if not updated:
        raise NotFoundError("Active staff Project assignment not found.")
    return {"ok": True, "projectId": project_id, "staffId": staff_id}


def remove_school(project_id: str, school_id: str) -> dict:
    ProjectSchoolAssignment.objects.filter(
        project_id=project_id, school__school_id=school_id
    ).delete()
    return {"ok": True}


def assign_partner(project_id: str, data: dict) -> dict:
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    from apps.partners.models import Partner

    partner = Partner.objects.filter(
        id=data.get("partnerId"), deleted_at__isnull=True
    ).first()
    if not partner:
        raise BadRequest("Unknown partner.")
    ProjectPartnerAssignment.objects.get_or_create(project=p, partner=partner)
    return {"ok": True, "projectId": project_id, "partnerId": partner.id}


def remove_partner(project_id: str, partner_id: str) -> dict:
    ProjectPartnerAssignment.objects.filter(
        project_id=project_id, partner_id=partner_id
    ).delete()
    return {"ok": True}


def set_manager(project_id: str, data: dict, principal=None) -> dict:
    """Set the project's manager (a single staff id).

    Reassigning ownership is a country-leadership act. Without a scope check a
    Project Coordinator could PATCH any project — including seizing a peer's
    project or orphaning it by clearing the manager.
    """
    from apps.core.exceptions import Forbidden, NotFoundError

    if principal is not None:
        from .scoping import get_scoped_project

        p = get_scoped_project(project_id, principal)
        role = getattr(principal, "active_role", "")
        if role == "ProjectCoordinator":
            raise Forbidden(
                "Project ownership is assigned by country leadership, not by "
                "coordinators."
            )
    else:
        p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
        if not p:
            raise NotFoundError("Project not found.")
    manager_id = (data.get("managerStaffId") or "").strip() or None
    p.manager_staff_id = manager_id
    p.save(update_fields=["manager_staff_id", "updated_at"])
    return _serialize(p)


# ── Lifecycle ────────────────────────────────────────────────────────────────


def assert_accepts_new_work(project: Project) -> None:
    """Refuse to attach new work to a paused or closed project.

    This is what makes an RVP pause/close mean something: without it the
    decision was an audit row that every assignment path ignored.
    """
    if not project.accepts_new_work:
        raise BadRequest(
            f"'{project.name}' is {project.status_label.lower()} — no new schools "
            "or activities can be assigned to it. Ask the RVP to reactivate it "
            "first."
        )


# What each RVP strategic decision does to project state. Decisions absent from
# this map (continue / measure / budget changes) are deliberately status-neutral
# — they are guidance, not lifecycle moves.
DECISION_STATUS = {
    "scale": ProjectStatus.SCALING.value,
    "pause": ProjectStatus.PAUSED.value,
    "close": ProjectStatus.CLOSED.value,
    "redesign": ProjectStatus.UNDER_REVIEW.value,
    "continue": ProjectStatus.ACTIVE.value,
}


def apply_decision(project: Project, action: str, principal, reason: str = "") -> bool:
    """Move a project's lifecycle to match a strategic decision.

    Returns whether the status actually changed. The audit row and CD
    notification are the caller's job (they predate this); what was missing was
    any effect on the project itself.
    """
    from django.utils import timezone

    new_status = DECISION_STATUS.get(action)
    if not new_status or new_status == project.status:
        return False
    project.status = new_status
    project.status_changed_at = timezone.now()
    project.status_changed_by = getattr(principal, "user_id", None)
    project.status_reason = reason or ""
    project.save(
        update_fields=[
            "status",
            "status_changed_at",
            "status_changed_by",
            "status_reason",
            "updated_at",
        ]
    )
    return True


@transaction.atomic
def create_project(data: dict, principal) -> dict:
    """Create a Special Project.

    No creation path existed at all — the "New Project" affordance on the
    projects command centre pointed at nothing, so every project had to be
    seeded or inserted by hand. Projects start `proposed`: the CD frames it,
    the RVP ratifies it into `active` via the strategic-decision flow.
    """
    from apps.audit.services import log as audit_log
    from apps.core.enums import SsaIntervention

    _assert_project_configurer(principal)
    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("A project name is required.")
    category = (data.get("category") or "").strip()
    valid_categories = {c.value for c in ProjectCategory}
    if category not in valid_categories:
        raise BadRequest(
            f"Category must be one of: {', '.join(sorted(valid_categories))}."
        )

    targets = data.get("targetInterventions") or []
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",") if t.strip()]
    valid_interventions = {i.value for i in SsaIntervention}
    unknown = [t for t in targets if t not in valid_interventions]
    if unknown:
        raise BadRequest(f"Unknown target intervention(s): {', '.join(unknown)}.")
    if not targets:
        # The model already documents this: a project with no declared target
        # cannot be measured for impact, and the assignment gate has nothing to
        # evaluate school need against.
        raise BadRequest(
            "Declare at least one target SSA intervention — impact measurement "
            "and the school-assignment need check both depend on it."
        )

    code = (data.get("code") or "").strip() or None
    if code and Project.objects.filter(code=code).exists():
        raise BadRequest(f"Project code '{code}' is already in use.")

    ceiling = data.get("budgetCeilingUgx")
    try:
        ceiling = int(ceiling) if ceiling not in (None, "") else None
    except (TypeError, ValueError):
        raise BadRequest("Budget ceiling must be a whole number of UGX.")
    if ceiling is not None and ceiling < 0:
        raise BadRequest("Budget ceiling cannot be negative.")
    school_focus = (data.get("schoolFocus") or ProjectSchoolFocus.ALL).strip()
    if school_focus not in ProjectSchoolFocus.values:
        raise BadRequest("School focus must be all, client, or core.")

    manager_staff_id = (data.get("managerStaffId") or "").strip() or None
    if principal.active_role == EdifyRole.PROJECT_COORDINATOR.value:
        # A coordinator-created Project must remain visible in the coordinator's
        # object-scoped portfolio after the success redirect. Coordinators may
        # not use project creation to assign ownership to a peer.
        manager_staff_id = str(getattr(principal, "staff_profile_id", "") or "")
        if not manager_staff_id:
            raise BadRequest(
                "A Special Project Coordinator needs an active staff profile "
                "before creating Projects."
            )

    project = Project.objects.create(
        name=name,
        code=code,
        category=category,
        target_interventions=targets,
        measurement_start_fy=(data.get("measurementStartFy") or "").strip() or None,
        measurement_end_fy=(data.get("measurementEndFy") or "").strip() or None,
        manager_staff_id=manager_staff_id,
        budget_ceiling_ugx=ceiling,
        school_focus=school_focus,
        status=ProjectStatus.PROPOSED.value,
        status_changed_at=None,
    )
    catalogue_ids = data.get("catalogueItemIds") or []
    if isinstance(catalogue_ids, str):
        catalogue_ids = [
            value.strip() for value in catalogue_ids.split(",") if value.strip()
        ]
    if not catalogue_ids:
        raise BadRequest(
            "Select at least one approved Activity Catalogue item for this Project."
        )
    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityProjectMapping,
        CatalogueStatus,
    )

    items = list(
        ActivityCatalogueItem.objects.filter(
            id__in=catalogue_ids,
            status=CatalogueStatus.ACTIVE,
            project_delivery_allowed=True,
        )
    )
    if len(items) != len(set(catalogue_ids)):
        raise BadRequest(
            "One or more selected Catalogue Activities are inactive or not "
            "approved for Project delivery."
        )
    ActivityProjectMapping.objects.bulk_create(
        [
            ActivityProjectMapping(
                project=project,
                catalogue_item=item,
                required_or_optional="optional",
                staff_delivery_allowed=item.staff_delivery_allowed,
                partner_delivery_allowed=item.partner_delivery_allowed,
            )
            for item in items
        ]
    )
    audit_log(
        action="project_create",
        subject_kind="Project",
        subject_id=project.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "name": project.name,
            "category": project.category,
            "targetInterventions": targets,
            "budgetCeilingUgx": ceiling,
            "catalogueItemIds": catalogue_ids,
            "schoolFocus": school_focus,
        },
    )
    return _serialize(project)


def _serialize(p: Project) -> dict:
    catalogue_activities = getattr(
        p,
        "serialized_catalogue_activities",
        None,
    )
    if catalogue_activities is None:
        catalogue_activities = p.allowed_catalogue_activities.filter(
            active=True
        ).select_related("catalogue_item")
    school_count = getattr(p, "serialized_school_count", None)
    if school_count is None:
        school_count = p.school_assignments.count()
    staff_count = getattr(p, "serialized_staff_count", None)
    if staff_count is None:
        staff_count = p.staff_assignments.filter(is_active=True).count()
    partner_count = getattr(p, "serialized_partner_count", None)
    if partner_count is None:
        partner_count = p.partner_assignments.count()
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "category": p.category,
        "status": p.status,
        "statusLabel": p.status_label,
        "acceptsNewWork": p.accepts_new_work,
        "budgetCeilingUgx": p.budget_ceiling_ugx,
        "intervention": p.intervention,
        "managerStaffId": p.manager_staff_id,
        "schoolFocus": p.school_focus,
        "schoolFocusLabel": p.get_school_focus_display(),
        "schoolCount": school_count,
        "staffCount": staff_count,
        "partnerCount": partner_count,
        "catalogueActivities": [
            {
                "id": mapping.catalogue_item_id,
                "stableCode": mapping.catalogue_item.stable_code,
                "displayName": mapping.catalogue_item.display_name,
                "requirement": mapping.required_or_optional,
            }
            for mapping in catalogue_activities
        ],
    }
