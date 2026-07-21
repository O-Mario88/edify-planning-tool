"""One rule for which projects a principal may see or touch.

The rule was reimplemented in six places and diverged: the coordinator's own
landing page (`/dashboard`) and the whole `/api/special-projects/*` surface
applied no filter at all, so a Project Coordinator could read every project in
the country — and `PATCH /api/special-projects/<id>` let them reassign a peer's
project to themselves.

The rule:
  • country roles (CD/IA/Accountant/Admin) — everything;
  • a Project Coordinator — only projects they manage;
  • other school-scoped roles (PL, CCEO) — projects reaching their schools,
    which is what supervision needs;
  • anyone else — nothing.
"""

from __future__ import annotations

from django.db.models import Q

from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.scoping import resolve_user_scope

from .models import Project


def scoped_projects(principal, base=None):
    """The Project queryset this principal may read."""
    qs = base if base is not None else Project.objects.filter(deleted_at__isnull=True)
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return qs.order_by("name")

    staff_id = getattr(principal, "staff_profile_id", None)
    if getattr(principal, "active_role", "") == "ProjectCoordinator":
        if not staff_id:
            return qs.none()
        return qs.filter(manager_staff_id=staff_id).order_by("name")

    school_ids = list(scope.school_ids or [])
    project_filter = Q()
    if staff_id:
        project_filter |= Q(manager_staff_id=staff_id)
    if school_ids:
        project_filter |= Q(school_assignments__school_id__in=school_ids)
    if not project_filter:
        return qs.none()
    return qs.filter(project_filter).distinct().order_by("name")


def get_scoped_project(project_id: str, principal) -> Project:
    """Fetch a project this principal is entitled to, or refuse.

    Deliberately raises NotFound rather than Forbidden for an out-of-scope id:
    a coordinator has no business learning that a project they cannot see
    exists.
    """
    project = scoped_projects(principal).filter(id=project_id).first()
    if not project:
        if Project.objects.filter(id=project_id, deleted_at__isnull=True).exists():
            raise Forbidden("You do not manage this project.")
        raise NotFoundError("Project not found.")
    return project


__all__ = ["scoped_projects", "get_scoped_project"]
