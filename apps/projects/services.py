"""Special-projects service — project directory + school/partner assignment + impact."""

from __future__ import annotations


from apps.core.exceptions import BadRequest, NotFoundError

from .models import (
    Project,
    ProjectCategory,
    ProjectPartnerAssignment,
    ProjectSchoolAssignment,
    ProjectStatus,
)


def list_projects(principal=None) -> list[dict]:
    # Unscoped by default only for internal callers that have already scoped;
    # every request path passes a principal.
    if principal is None:
        return [_serialize(p) for p in Project.objects.filter(deleted_at__isnull=True)]
    from .scoping import scoped_projects

    return [_serialize(p) for p in scoped_projects(principal)]


def get_one(project_id: str, principal=None) -> dict:
    if principal is not None:
        from .scoping import get_scoped_project

        return _serialize(get_scoped_project(project_id, principal))
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    return _serialize(p)


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


def assign_school(project_id: str, data: dict) -> dict:
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

    school = School.objects.filter(school_id=data.get("schoolId")).first()
    if not school:
        raise BadRequest("Unknown school.")

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
        project=p, school=school
    )
    updates = []
    if matched and assignment.matched_intervention != matched:
        assignment.matched_intervention = matched
        updates.append("matched_intervention")
    if reason and assignment.assignment_reason != reason:
        assignment.assignment_reason = reason
        updates.append("assignment_reason")
    if updates:
        assignment.save(update_fields=[*updates, "updated_at"])
    return {"ok": True, "projectId": project_id, "schoolId": school.school_id}


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


def create_project(data: dict, principal) -> dict:
    """Create a Special Project.

    No creation path existed at all — the "New Project" affordance on the
    projects command centre pointed at nothing, so every project had to be
    seeded or inserted by hand. Projects start `proposed`: the CD frames it,
    the RVP ratifies it into `active` via the strategic-decision flow.
    """
    from apps.audit.services import log as audit_log
    from apps.core.enums import SsaIntervention

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

    project = Project.objects.create(
        name=name,
        code=code,
        category=category,
        target_interventions=targets,
        measurement_start_fy=(data.get("measurementStartFy") or "").strip() or None,
        measurement_end_fy=(data.get("measurementEndFy") or "").strip() or None,
        manager_staff_id=(data.get("managerStaffId") or "").strip() or None,
        budget_ceiling_ugx=ceiling,
        status=ProjectStatus.PROPOSED.value,
        status_changed_at=None,
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
        },
    )
    return _serialize(project)


def _serialize(p: Project) -> dict:
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
        "schoolCount": p.school_assignments.count(),
        "partnerCount": p.partner_assignments.count(),
    }
