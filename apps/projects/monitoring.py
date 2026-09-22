"""Watching a Special Project without being able to touch it.

Owner, 2026-09-21:

  "Add project page to CCEO, PL and IA to monitor all the project activities
  (training scheduled and completed, school visits ...etc) by project
  coordinator and his partner but they Only have read only access. Project
  coordinator is in control of all the project activities (scheduling or
  assigning to partner) and project contribution to ssa intervention
  improvement should be clearly shown. But the CCEO and PL can only see the
  schools they added to the project but not schools added by other cceos and
  pls."

Two rules, and they are different from the ordinary project scope:

* **Read only, for everyone here.** This module computes; it never writes,
  and the page it feeds carries no control that would. Scheduling a project
  activity and handing one to a partner stay where they were — the
  coordinator's Project Planning surface. A watcher who wants work done asks
  the coordinator.
* **Contribution, not the whole project.** A CCEO or Programme Lead sees the
  enrolments they added themselves (``ProjectSchoolAssignment.assigned_by``),
  never another officer's. Impact Assessment, the Country Director and Admin
  see the project whole, because verification and country oversight are
  exactly the jobs that need it.

Every figure is read live from the Activity ledger and the SSA impact engine
(``apps.projects.ssa_impact``), and the SSA cohort is narrowed by the same
enrolment lens — so the improvement a CCEO reads is over the schools they
contributed, with its own denominator shown, rather than the project's total
dressed up as theirs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.core.rbac import EdifyRole

__all__ = [
    "WHOLE_PROJECT_ROLES",
    "ProjectMonitoringRow",
    "ProjectMonitoring",
    "project_monitoring",
    "sees_whole_project",
]

#: Roles that read a project whole rather than their own contribution. IA
#: verifies the work, the CD owns the country picture, and Admin observes
#: everything. A CCEO or Programme Lead is deliberately absent: the owner's
#: rule is that they see the schools they added and nobody else's.
#:
#: Bound to the enum rather than spelled as strings, so renaming a role
#: cannot quietly drop it out of the whole-project lens.
WHOLE_PROJECT_ROLES = frozenset(
    {
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    }
)


def sees_whole_project(principal) -> bool:
    return getattr(principal, "active_role", "") in WHOLE_PROJECT_ROLES


@dataclass
class ProjectMonitoringRow:
    """One project, as the person watching it may see it."""

    id: str
    code: str
    name: str
    status_label: str
    coordinator: str
    partners: list[str] = field(default_factory=list)
    schools: int = 0
    #: The enrolments this reader contributed — equal to ``schools`` for a
    #: whole-project reader, and the point of the page for everyone else.
    my_schools: int = 0
    trainings_scheduled: int = 0
    trainings_completed: int = 0
    visits_scheduled: int = 0
    visits_completed: int = 0
    other_scheduled: int = 0
    other_completed: int = 0
    partner_delivered: int = 0
    staff_delivered: int = 0
    interventions: list[str] = field(default_factory=list)
    impact: dict = field(default_factory=dict)

    @property
    def activities_scheduled(self) -> int:
        return self.trainings_scheduled + self.visits_scheduled + self.other_scheduled

    @property
    def activities_completed(self) -> int:
        return self.trainings_completed + self.visits_completed + self.other_completed

    @property
    def completion_label(self) -> str:
        """Plain counting, never a percentage over a denominator of nothing."""
        if not self.activities_scheduled:
            return "Nothing planned yet"
        return f"{self.activities_completed} of {self.activities_scheduled} delivered"


@dataclass
class ProjectMonitoring:
    rows: list[ProjectMonitoringRow] = field(default_factory=list)
    whole_project: bool = False
    #: Said on the page, so a reader knows which question the numbers answer.
    lens_note: str = ""

    @property
    def projects(self) -> int:
        return len(self.rows)

    @property
    def schools(self) -> int:
        return sum(row.my_schools for row in self.rows)

    @property
    def trainings_scheduled(self) -> int:
        return sum(row.trainings_scheduled for row in self.rows)

    @property
    def trainings_completed(self) -> int:
        return sum(row.trainings_completed for row in self.rows)

    @property
    def visits_scheduled(self) -> int:
        return sum(row.visits_scheduled for row in self.rows)

    @property
    def visits_completed(self) -> int:
        return sum(row.visits_completed for row in self.rows)

    @property
    def schools_improved(self) -> int:
        return sum(row.impact.get("improved", 0) for row in self.rows)


def _visible_assignments(principal, project_ids):
    """The enrolments this reader may see, by the owner's rule."""
    from apps.core.scoping import owner_ids
    from apps.projects.models import ProjectSchoolAssignment

    rows = ProjectSchoolAssignment.objects.filter(
        project_id__in=project_ids
    ).select_related("school", "school__district", "project")
    if sees_whole_project(principal):
        return rows
    mine = [value for value in owner_ids(principal) if value]
    if not mine:
        return rows.none()
    return rows.filter(assigned_by__in=mine)


def _projects_for(principal):
    """Every live project a watcher may read.

    Not ``_scoped_projects``: that answers "whose project is this to run",
    which is the coordinator's question. Watching is a different one — a CCEO
    watches any project they put a school into, and IA watches all of them —
    and the enrolment lens below is what bounds what they actually see.
    """
    from apps.projects.models import LIVE_PROJECT_STATUSES, Project

    live = [status.value for status in LIVE_PROJECT_STATUSES]
    projects = Project.objects.filter(deleted_at__isnull=True, status__in=live)
    if sees_whole_project(principal):
        return projects.order_by("name")

    from apps.core.scoping import owner_ids

    mine = [value for value in owner_ids(principal) if value]
    if not mine:
        return projects.none()
    return (
        projects.filter(school_assignments__assigned_by__in=mine)
        .distinct()
        .order_by("name")
    )


def project_monitoring(
    principal, *, fy: str | None = None, project_id: str = ""
) -> ProjectMonitoring:
    """What the coordinator and their partners have done, for this reader."""
    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.projects.ssa_impact import project_impact

    fy = str(fy or get_operational_fy())
    whole = sees_whole_project(principal)
    result = ProjectMonitoring(
        whole_project=whole,
        lens_note=(
            "Every school in every live project."
            if whole
            else "Only the schools you added to a project. Schools other "
            "officers added are theirs to watch."
        ),
    )

    projects = list(_projects_for(principal))
    if project_id:
        projects = [project for project in projects if project.id == project_id]
    if not projects:
        return result

    project_ids = [project.id for project in projects]
    assignments = list(_visible_assignments(principal, project_ids))
    by_project: dict[str, list] = {}
    for assignment in assignments:
        by_project.setdefault(assignment.project_id, []).append(assignment)

    school_ids = {assignment.school_id for assignment in assignments}
    totals = _activity_totals(project_ids, school_ids, fy=fy, whole=whole)
    coordinators = _coordinator_names(projects)
    partners = _partner_names(project_ids)
    intervention_labels = dict(SsaIntervention.choices)

    for project in projects:
        mine = by_project.get(project.id, [])
        if not whole and not mine:
            # A project this reader has contributed nothing to in view. It is
            # not theirs to watch, and an empty row would read as a project
            # that has done nothing.
            continue
        counts = totals.get(project.id, {})
        primary, supporting = project.intervention_plan()
        row = ProjectMonitoringRow(
            id=project.id,
            code=project.code or "",
            name=project.name,
            status_label=project.status_label,
            coordinator=coordinators.get(project.id, "Not assigned"),
            partners=partners.get(project.id, []),
            schools=counts.get("enrolled_total", len(mine)),
            my_schools=len(mine),
            trainings_scheduled=counts.get("training_scheduled", 0),
            trainings_completed=counts.get("training_completed", 0),
            visits_scheduled=counts.get("visit_scheduled", 0),
            visits_completed=counts.get("visit_completed", 0),
            other_scheduled=counts.get("other_scheduled", 0),
            other_completed=counts.get("other_completed", 0),
            partner_delivered=counts.get("partner_delivered", 0),
            staff_delivered=counts.get("staff_delivered", 0),
            interventions=[
                intervention_labels.get(code, code)
                for code in ([primary] if primary else []) + supporting
            ],
            # The cohort travels with the lens: a CCEO reads the movement of
            # the schools they contributed, with its own denominator.
            impact=project_impact(
                project,
                intervention=primary,
                assignments=None if whole else mine,
            ),
        )
        result.rows.append(row)
    return result


def _activity_totals(project_ids, school_ids, *, fy: str, whole: bool) -> dict:
    """Scheduled and delivered counts per project, in two queries.

    A watcher's counts are bounded by the schools they may see, so a CCEO's
    "12 trainings" is twelve trainings at their own schools — never the
    project's total relabelled as theirs.
    """
    from django.db.models import Count, Q

    from apps.activities.models import Activity
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NON_FUNDABLE_ACTIVITY_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.projects.models import ProjectSchoolAssignment

    live = Activity.objects.filter(
        project_id__in=project_ids, fy=fy, deleted_at__isnull=True
    ).exclude(status__in=(*NON_FUNDABLE_ACTIVITY_STATUSES, "not_planned"))
    enrolled = ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
    if not whole:
        if not school_ids:
            return {}
        live = live.filter(school_id__in=school_ids)
        enrolled = enrolled.filter(school_id__in=school_ids)

    done = Q(status__in=COMPLETED_WORK_STATUSES)
    rows = live.values("project_id").annotate(
        training_scheduled=Count("id", filter=Q(activity_type__in=TRAINING_TYPES)),
        training_completed=Count(
            "id", filter=Q(activity_type__in=TRAINING_TYPES) & done
        ),
        visit_scheduled=Count("id", filter=Q(activity_type__in=VISIT_TYPES)),
        visit_completed=Count("id", filter=Q(activity_type__in=VISIT_TYPES) & done),
        other_scheduled=Count(
            "id",
            filter=~Q(activity_type__in=(*TRAINING_TYPES, *VISIT_TYPES)),
        ),
        other_completed=Count(
            "id",
            filter=~Q(activity_type__in=(*TRAINING_TYPES, *VISIT_TYPES)) & done,
        ),
        partner_delivered=Count("id", filter=Q(delivery_type="partner")),
        staff_delivered=Count("id", filter=~Q(delivery_type="partner")),
    )
    totals = {row.pop("project_id"): row for row in rows}
    for row in enrolled.values("project_id").annotate(n=Count("id")):
        totals.setdefault(row["project_id"], {})["enrolled_total"] = row["n"]
    return totals


def _coordinator_names(projects) -> dict[str, str]:
    """Who is in control of each project's activities."""
    from apps.accounts.models import StaffProfile

    ids = {project.manager_staff_id for project in projects if project.manager_staff_id}
    if not ids:
        return {}
    names = {
        profile.id: (profile.user.name if profile.user_id else "")
        for profile in StaffProfile.objects.filter(id__in=ids).select_related("user")
    }
    return {
        project.id: names.get(project.manager_staff_id, "Not assigned")
        for project in projects
        if project.manager_staff_id
    }


def _partner_names(project_ids) -> dict[str, list[str]]:
    from apps.projects.models import ProjectPartnerAssignment

    out: dict[str, list[str]] = {}
    for row in ProjectPartnerAssignment.objects.filter(
        project_id__in=project_ids
    ).select_related("partner"):
        out.setdefault(row.project_id, []).append(row.partner.name)
    for names in out.values():
        names.sort()
    return out
