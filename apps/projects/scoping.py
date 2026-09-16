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

Enrolling a school into a project is a separate question with its own answer,
`assignable_projects`: the school's owner decides, so they are offered every
project still accepting work.
"""

from __future__ import annotations

from django.db.models import Q

from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.scoping import country_bound, country_staff_ids, resolve_user_scope

from .models import OPEN_PROJECT_STATUSES, Project


def scoped_projects(principal, base=None):
    """The Project queryset this principal may read."""
    qs = base if base is not None else Project.objects.filter(deleted_at__isnull=True)
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        if country_bound(scope):
            # A country role reads the projects that reach their country: by
            # the schools enrolled or by the person running them. A project
            # with neither is unplaced rather than somebody else's, so it
            # stays visible until it is — the same rule as an ownerless
            # cluster.
            unplaced = Q(school_assignments__isnull=True) & (
                Q(manager_staff_id__isnull=True) | Q(manager_staff_id="")
            )
            qs = qs.filter(
                Q(school_assignments__school__region__country=scope.country)
                | Q(manager_staff_id__in=country_staff_ids(scope))
                | unplaced
            ).distinct()
        return qs.order_by("name")

    staff_id = getattr(principal, "staff_profile_id", None)
    if getattr(principal, "active_role", "") == "ProjectCoordinator":
        if not staff_id:
            return qs.none()
        return (
            qs.filter(
                Q(manager_staff_id=staff_id)
                | Q(
                    staff_assignments__staff_id=staff_id,
                    staff_assignments__is_active=True,
                )
            )
            .distinct()
            .order_by("name")
        )

    school_ids = list(scope.school_ids or [])
    project_filter = Q()
    if staff_id:
        project_filter |= Q(manager_staff_id=staff_id)
        project_filter |= Q(
            staff_assignments__staff_id=staff_id,
            staff_assignments__is_active=True,
        )
    if school_ids:
        project_filter |= Q(school_assignments__school_id__in=school_ids)
    if not project_filter:
        return qs.none()
    return qs.filter(project_filter).distinct().order_by("name")


def assignable_projects(principal, base=None):
    """The projects this principal may enrol one of their schools into.

    A different question from :func:`scoped_projects`, which answers "what may
    this person read". A Project Coordinator creates the project; the CCEO or
    Programme Lead who owns the school is the one who enrols it (owner,
    2026-09-16). Before this they could not: `scoped_projects` shows a
    school-scoped role only the projects already reaching their schools, so a
    coordinator's new cohort was invisible to the very people meant to fill
    it, and the coordinator's own scope is derived from those assignments, so
    nobody could make the first one.

    Country roles keep the read scope they already have. Everyone else is
    offered every project still accepting work, because enrolling a school is
    a decision about the school, which is theirs, not about the project, which
    is the coordinator's. Closed and paused projects are never offered —
    `assert_accepts_new_work` refuses them anyway, and a control that leads to
    a refusal is worse than no control.
    """
    qs = base if base is not None else Project.objects.filter(deleted_at__isnull=True)
    scope = resolve_user_scope(principal)
    open_statuses = [status.value for status in OPEN_PROJECT_STATUSES]
    if scope.country_scope:
        return scoped_projects(principal, base=qs).filter(status__in=open_statuses)
    if not (scope.school_ids or getattr(principal, "staff_profile_id", None)):
        return qs.none()
    return qs.filter(status__in=open_statuses).distinct().order_by("name")


def enrollable_schools(principal, base=None):
    """The schools this principal may enrol into a project.

    Own portfolio *and* supervised team, which is wider than the
    `direct_portfolio_schools` rule the School Directory's other bulk actions
    use. That rule exists for a good reason — a Programme Lead was editing,
    clustering and staff-matching their CCEOs' schools as if they were their
    own — and this is a deliberate, narrow exception to it (owner, 2026-09-16:
    "the cceo and PL should be able to assign schools to projects created by
    the project coordinator"). A PL holds no school directly, so under the
    direct rule they could see a coordinator's project in the dropdown and
    still be refused on save, which is the worst of both.

    It stays an exception: enrolling a school in a project, and nothing else.
    Editing the school, clustering it and matching its staff are still the
    owner's alone, and a school outside both the caller's portfolio and their
    team is refused here as everywhere.
    """
    from apps.core.scoping import school_queryset

    scope = resolve_user_scope(principal)
    qs = school_queryset(scope)
    if qs is None:  # pragma: no cover - schools app not ready
        return None
    qs = qs.filter(deleted_at__isnull=True)
    return qs if base is None else qs.filter(id__in=base.values("id"))


def annotate_coordinator_names(projects):
    """Tag each project with the name of the coordinator who runs it.

    `assignable_projects` spans every open cohort in the country, so a bare
    "Numeracy Boost" does not tell the CCEO whose project they are enrolling a
    school into. One query for the whole page, attached as `coordinator_name`.
    """
    from apps.accounts.models import StaffProfile

    projects = list(projects)
    staff_ids = [p.manager_staff_id for p in projects if p.manager_staff_id]
    names = {
        row["id"]: row["user__name"]
        for row in StaffProfile.objects.filter(id__in=staff_ids).values(
            "id", "user__name"
        )
    }
    for project in projects:
        project.coordinator_name = names.get(project.manager_staff_id or "")
    return projects


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


__all__ = [
    "annotate_coordinator_names",
    "enrollable_schools",
    "assignable_projects",
    "scoped_projects",
    "get_scoped_project",
]
