"""Special-projects service — project directory + school/partner assignment + impact."""

from __future__ import annotations


from apps.core.exceptions import BadRequest, NotFoundError

from .models import Project, ProjectPartnerAssignment, ProjectSchoolAssignment


def list_projects() -> list[dict]:
    return [_serialize(p) for p in Project.objects.filter(deleted_at__isnull=True)]


def get_one(project_id: str) -> dict:
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    return _serialize(p)


def impact(project_id: str) -> list[dict]:
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


def set_manager(project_id: str, data: dict) -> dict:
    """Set the project's manager (a single staff user id). CD assigns a staff
    member to own the project; clears it when managerStaffId is empty."""
    from apps.core.exceptions import NotFoundError

    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    manager_id = (data.get("managerStaffId") or "").strip() or None
    p.manager_staff_id = manager_id
    p.save(update_fields=["manager_staff_id", "updated_at"])
    return _serialize(p)


def _serialize(p: Project) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "category": p.category,
        "intervention": p.intervention,
        "managerStaffId": p.manager_staff_id,
        "schoolCount": p.school_assignments.count(),
        "partnerCount": p.partner_assignments.count(),
    }
