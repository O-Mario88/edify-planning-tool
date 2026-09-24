"""Who directs a Special Project's work.

Owner, 2026-09-24:

  "Schools assigned to project cannot be withdrawn by the staff but the
  project coordinator can withdraw from the partner they assigned to and
  reassign to another partner. ... They have read only access, Only Project
  coordinator can edit plan and do everything."

One rule, asked by every service that changes project work — taking a project
school's work back from its Partner, deciding what happens to project work a
Partner handed back, and removing a school from the project — and by the pages
that decide whether to draw those controls, so a page never offers what a
service will refuse.

The Project Coordinator who runs the project directs its work. Admin keeps the
platform-wide authority every withdrawal already honours
(``withdrawal_service.assert_may_withdraw``). Everyone else — the CCEO or
Programme Lead who added the school, and the country roles that watch the
project — reads it.

Closing a school is not a decision about the project: the school has shut, so
its Partner work stops whoever runs the project. That path says so explicitly
(``withdrawal_service.withdraw(..., school_closure=True)``) rather than being
refused here.
"""

from __future__ import annotations

from apps.core.rbac import EdifyRole

__all__ = [
    "coordinates_project",
    "directs_project_work",
    "project_work_refusal",
    "projects_directed_by",
]


def _is_admin(principal) -> bool:
    return bool(
        getattr(principal, "is_superuser", False)
        or getattr(principal, "active_role", "") == EdifyRole.ADMIN.value
    )


def _coordinated_ids(principal, project_ids) -> set[str]:
    """The projects among these that this Project Coordinator runs."""
    if getattr(principal, "active_role", "") != EdifyRole.PROJECT_COORDINATOR.value:
        return set()
    wanted = {str(pid) for pid in project_ids if pid}
    if not wanted:
        return set()
    from apps.projects.scoping import scoped_projects

    return {
        str(pid)
        for pid in scoped_projects(principal)
        .filter(id__in=wanted)
        .values_list("id", flat=True)
    }


def coordinates_project(principal, project_id) -> bool:
    """Whether this principal is a Project Coordinator running this project."""
    return bool(project_id) and str(project_id) in _coordinated_ids(
        principal, [project_id]
    )


def directs_project_work(principal, project_id) -> bool:
    """Whether this principal may change this project's work."""
    if not project_id:
        return False
    return _is_admin(principal) or coordinates_project(principal, project_id)


def projects_directed_by(principal, project_ids) -> set[str]:
    """Of these projects, the ones this principal may change — one query.

    For pages that draw a control per row: asking ``directs_project_work`` per
    row would cost a query each.
    """
    wanted = {str(pid) for pid in project_ids if pid}
    if not wanted:
        return set()
    if _is_admin(principal):
        return wanted
    return _coordinated_ids(principal, wanted)


def project_work_refusal(project=None, *, action: str = "withdraw it") -> str:
    """What a reader who may not act is told, naming the project."""
    name = getattr(project, "name", "") or "a Special Project"
    return (
        f"This school's work belongs to {name}. Only its Project Coordinator "
        f"can {action}."
    )
