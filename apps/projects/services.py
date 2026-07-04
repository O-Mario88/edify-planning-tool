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
    return [{"id": a.partner_id, "name": a.partner.name} for a in p.partner_assignments.select_related("partner")]


def assign_school(project_id: str, data: dict) -> dict:
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    from apps.schools.models import School
    school = School.objects.filter(school_id=data.get("schoolId")).first()
    if not school:
        raise BadRequest("Unknown school.")
    ProjectSchoolAssignment.objects.get_or_create(project=p, school=school)
    return {"ok": True, "projectId": project_id, "schoolId": school.school_id}


def remove_school(project_id: str, school_id: str) -> dict:
    ProjectSchoolAssignment.objects.filter(project_id=project_id, school__school_id=school_id).delete()
    return {"ok": True}


def assign_partner(project_id: str, data: dict) -> dict:
    p = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if not p:
        raise NotFoundError("Project not found.")
    from apps.partners.models import Partner
    partner = Partner.objects.filter(id=data.get("partnerId"), deleted_at__isnull=True).first()
    if not partner:
        raise BadRequest("Unknown partner.")
    ProjectPartnerAssignment.objects.get_or_create(project=p, partner=partner)
    return {"ok": True, "projectId": project_id, "partnerId": partner.id}


def remove_partner(project_id: str, partner_id: str) -> dict:
    ProjectPartnerAssignment.objects.filter(project_id=project_id, partner_id=partner_id).delete()
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
