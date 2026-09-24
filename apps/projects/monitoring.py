"""Following a Special Project school by school.

Owner, 2026-09-21:

  "Add project page to CCEO, PL and IA to monitor all the project activities
  (training scheduled and completed, school visits ...etc) by project
  coordinator and his partner but they Only have read only access. Project
  coordinator is in control of all the project activities (scheduling or
  assigning to partner) and project contribution to ssa intervention
  improvement should be clearly shown. But the CCEO and PL can only see the
  schools they added to the project but not schools added by other cceos and
  pls."

Owner, 2026-09-24:

  "Project Monitoring should show you a list of all the schools you have
  assigned to a project grouped by project, and track if the schools have been
  assigned to a partner and the partner has scheduled them, or
  scheduled/planned for by project coordinator. The staff except Project
  coordinator have read only access. But they should monitor if the school has
  been planned for, execution has taken place, improvement against their focus
  ssa interventions."

The rules:

* **Read only, except for the coordinator.** This module computes; it never
  writes. Scheduling a project activity and handing one to a partner stay the
  coordinator's, through the same drawers Project Planning opens — and the page
  draws those two controls for the Project Coordinator alone. Everyone else
  reads, and asks the coordinator for work they need.
* **Contribution, not the whole project.** A CCEO or Programme Lead sees the
  enrolments they added themselves (``ProjectSchoolAssignment.assigned_by``),
  never another officer's. Impact Assessment, the Country Director and Admin
  see the project whole, because verification and country oversight are
  exactly the jobs that need it. The coordinator sees every school in the
  projects they run (``planning_service._scoped_projects``), because they
  deliver to all of them.
* **One row per enrolled school, one answer per question.** Each school row
  says who has the work (the coordinator's staff, or a partner still to
  schedule it, or a partner who has), whether it happened, and whether the
  school's focus intervention moved. The project figures above the rows are
  counted from the same ledger rows, so a project and its schools cannot
  disagree.

Every figure is read live from the Activity ledger, the Partner assignments and
the SSA impact engine (``apps.projects.ssa_impact``), whose honesty rules this
page keeps: a missing follow-up is "awaiting follow-up", never "no change", and
a movement is only called an improvement by the engine's verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.core.rbac import EdifyRole

__all__ = [
    "WHOLE_PROJECT_ROLES",
    "ProjectMonitoringRow",
    "ProjectMonitoring",
    "ProjectSchoolRow",
    "controls_project_work",
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


def controls_project_work(principal) -> bool:
    """The one reader who may schedule or hand work to a partner from here."""
    return getattr(principal, "active_role", "") == EdifyRole.PROJECT_COORDINATOR.value


# ── What a school row can say ────────────────────────────────────────────────
#: Who has the work at this school, in the order a coordinator acts on it.
PLAN_NOT_PLANNED = "not_planned"
PLAN_PARTNER_RETURNED = "partner_returned"
PLAN_PARTNER_AWAITING = "partner_awaiting"
PLAN_PARTNER_SCHEDULED = "partner_scheduled"
PLAN_STAFF_PLANNED = "staff_planned"

#: Short on purpose: a status sits on one table line, and the platform's
#: table fitter truncates a long one rather than wrap it.
PLAN_LABELS = {
    PLAN_NOT_PLANNED: "Not planned",
    PLAN_PARTNER_RETURNED: "Returned by partner",
    PLAN_PARTNER_AWAITING: "Awaiting partner",
    PLAN_PARTNER_SCHEDULED: "Partner scheduled",
    PLAN_STAFF_PLANNED: "Coordinator planned",
}

#: Colour vocabulary, spelled as the ``edify-status-badge`` tones the project
#: tables already use, so a school reads in the same colours on Project
#: Planning and here.
TONE_NEUTRAL = "neutral"
TONE_WARNING = "warning"
TONE_DANGER = "danger"
TONE_INFO = "info"
TONE_SUCCESS = "success"
TONE_PURPLE = "pending"

PLAN_TONES = {
    PLAN_NOT_PLANNED: TONE_NEUTRAL,
    PLAN_PARTNER_RETURNED: TONE_DANGER,
    PLAN_PARTNER_AWAITING: TONE_WARNING,
    PLAN_PARTNER_SCHEDULED: TONE_PURPLE,
    PLAN_STAFF_PLANNED: TONE_INFO,
}

#: Whether the work happened, using the Planning badges' vocabulary
#: (``apps.planning.school_planning_badges``) so a school reads the same here
#: as on Planning.
EXEC_NONE = "none"
EXEC_SCHEDULED = "scheduled"
EXEC_RETURNED = "returned"
EXEC_DELIVERED = "delivered"
EXEC_VERIFIED = "verified"

EXEC_LABELS = {
    EXEC_NONE: "No activity",
    EXEC_SCHEDULED: "Not yet delivered",
    EXEC_RETURNED: "Returned",
    EXEC_DELIVERED: "Delivered",
    EXEC_VERIFIED: "Verified",
}
EXEC_TONES = {
    EXEC_NONE: TONE_NEUTRAL,
    EXEC_SCHEDULED: TONE_WARNING,
    EXEC_RETURNED: TONE_DANGER,
    EXEC_DELIVERED: TONE_INFO,
    EXEC_VERIFIED: TONE_SUCCESS,
}

#: The SSA verdict, in words, keyed by the engine's classification.
IMPACT_LABELS = {
    "improved": ("Improved", TONE_SUCCESS),
    "maintained_strong": ("Maintained strong", TONE_SUCCESS),
    "no_change": ("No change", TONE_NEUTRAL),
    "declined": ("Declined", TONE_DANGER),
    "not_yet_measurable": ("Window not open", TONE_INFO),
}

#: The filter the page offers over the school rows.
STAGE_FILTERS = (
    ("", "All schools"),
    (PLAN_NOT_PLANNED, "Not planned"),
    (PLAN_PARTNER_AWAITING, "Awaiting partner schedule"),
    (PLAN_PARTNER_RETURNED, "Returned by partner"),
    (PLAN_PARTNER_SCHEDULED, "Scheduled by partner"),
    (PLAN_STAFF_PLANNED, "Planned by coordinator or staff"),
    (EXEC_DELIVERED, "Delivered, awaiting verification"),
    (EXEC_VERIFIED, "Delivered and verified"),
)


@dataclass
class InterventionReading:
    """A focus intervention at one school: where it started, where it is."""

    code: str
    label: str
    abbreviation: str
    baseline: float | None = None
    latest: float | None = None
    latest_on: date | None = None

    @property
    def change(self) -> float | None:
        if self.baseline is None or self.latest is None:
            return None
        return round(self.latest - self.baseline, 2)

    @property
    def direction(self) -> str:
        """ "up", "down" or "flat" — a movement, not a verdict."""
        change = self.change
        if change is None:
            return ""
        return "up" if change > 0 else ("down" if change < 0 else "flat")


@dataclass
class ProjectSchoolRow:
    """One enrolled school, as the person watching the project may see it."""

    assignment_id: str
    project_id: str
    school_pk: str
    school_code: str
    school_name: str
    district: str
    added_by: str
    enrolled_on: date | None

    plan_stage: str = PLAN_NOT_PLANNED
    partner_name: str = ""
    planned_by: str = ""
    #: Staff-planned work is the coordinator's unless somebody else's name is
    #: on it; the row says which rather than crediting the coordinator.
    planned_by_coordinator: bool = False
    next_date: date | None = None

    planned: int = 0
    delivered: int = 0
    verified: int = 0
    execution: str = EXEC_NONE
    last_delivered_on: date | None = None

    focus: list[InterventionReading] = field(default_factory=list)
    impact_label: str = ""
    impact_tone: str = TONE_NEUTRAL

    #: Filled in for the coordinator only; empty means no control is drawn.
    schedule_url: str = ""
    partner_url: str = ""

    @property
    def plan_label(self) -> str:
        if self.plan_stage == PLAN_STAFF_PLANNED and not self.planned_by_coordinator:
            return "Staff planned"
        return PLAN_LABELS[self.plan_stage]

    @property
    def is_overdue(self) -> bool:
        """The next planned date has passed and nothing was delivered."""
        return bool(
            self.next_date
            and self.next_date < date.today()
            and self.execution in (EXEC_SCHEDULED, EXEC_NONE)
        )

    @property
    def plan_tone(self) -> str:
        return PLAN_TONES[self.plan_stage]

    @property
    def execution_label(self) -> str:
        return EXEC_LABELS[self.execution]

    @property
    def execution_tone(self) -> str:
        return EXEC_TONES[self.execution]

    @property
    def is_planned(self) -> bool:
        """Somebody holds dated or datable work here. A school the partner
        handed back is not planned: it is waiting on the coordinator."""
        return self.plan_stage not in (PLAN_NOT_PLANNED, PLAN_PARTNER_RETURNED)

    @property
    def has_delivery(self) -> bool:
        return self.execution in (EXEC_DELIVERED, EXEC_VERIFIED)

    def matches(self, stage: str) -> bool:
        """Whether this row belongs under one of the page's stage filters."""
        if not stage:
            return True
        if stage in EXEC_LABELS:
            return self.execution == stage
        return self.plan_stage == stage


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
    #: The enrolled schools this reader may see, one row each, narrowed by
    #: the page's stage filter.
    school_rows: list[ProjectSchoolRow] = field(default_factory=list)
    #: The same schools before the stage filter. The project's own figures
    #: are counted from these, so filtering the rows never changes what the
    #: project did.
    all_school_rows: list[ProjectSchoolRow] = field(default_factory=list)
    accepts_new_work: bool = True

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

    @property
    def schools_planned(self) -> int:
        return sum(1 for row in self.all_school_rows if row.is_planned)

    @property
    def schools_awaiting_partner(self) -> int:
        return sum(
            1 for row in self.all_school_rows if row.plan_stage == PLAN_PARTNER_AWAITING
        )

    @property
    def schools_delivered(self) -> int:
        return sum(1 for row in self.all_school_rows if row.has_delivery)


@dataclass
class ProjectMonitoring:
    rows: list[ProjectMonitoringRow] = field(default_factory=list)
    whole_project: bool = False
    #: Whether this reader is the coordinator, who may act from the page.
    controls: bool = False
    #: Said on the page, so a reader knows which question the numbers answer.
    lens_note: str = ""
    #: The fiscal years the activity figures read, for the page to say.
    plan_period_label: str = ""

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

    @property
    def schools_planned(self) -> int:
        return sum(row.schools_planned for row in self.rows)

    @property
    def schools_awaiting_partner(self) -> int:
        return sum(row.schools_awaiting_partner for row in self.rows)

    @property
    def schools_delivered(self) -> int:
        return sum(row.schools_delivered for row in self.rows)


def _visible_assignments(principal, project_ids):
    """The enrolments this reader may see, by the owner's rule."""
    from apps.core.scoping import owner_ids
    from apps.projects.models import ProjectSchoolAssignment

    rows = (
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .select_related("school", "school__district", "project")
        .order_by("school__name")
    )
    if sees_whole_project(principal) or controls_project_work(principal):
        return rows
    mine = [value for value in owner_ids(principal) if value]
    if not mine:
        return rows.none()
    return rows.filter(assigned_by__in=mine)


def _projects_for(principal):
    """Every live project a watcher may read.

    Not ``_scoped_projects`` for a watcher: that answers "whose project is
    this to run", which is the coordinator's question — and so it is exactly
    the coordinator's scope here. Watching is a different one — a Programme
    Lead watches any project they put a school into, and IA watches all of
    them — and the enrolment lens is what bounds what they actually see.
    """
    from apps.projects.models import LIVE_PROJECT_STATUSES, Project

    live = [status.value for status in LIVE_PROJECT_STATUSES]
    projects = Project.objects.filter(deleted_at__isnull=True, status__in=live)
    if sees_whole_project(principal):
        return projects.order_by("name")
    if controls_project_work(principal):
        from apps.projects.planning_service import _scoped_projects

        return _scoped_projects(principal).filter(status__in=live).order_by("name")

    from apps.core.scoping import owner_ids

    mine = [value for value in owner_ids(principal) if value]
    if not mine:
        return projects.none()
    return (
        projects.filter(school_assignments__assigned_by__in=mine)
        .distinct()
        .order_by("name")
    )


def _lens_note(*, whole: bool, controls: bool) -> str:
    if controls:
        return (
            "Every school in the projects you coordinate. Schedule the work or "
            "assign it to a partner from a school's row, or from Project Planning."
        )
    if whole:
        return "Every school in every live project."
    return (
        "Only the schools you added to a project. Schools other officers added "
        "are theirs to watch."
    )


def project_monitoring(
    principal, *, fy: str | None = None, project_id: str = "", stage: str = ""
) -> ProjectMonitoring:
    """What the coordinator and their partners have done, for this reader.

    ``stage`` narrows each project's school rows to one of STAGE_FILTERS; the
    project figures stay whole, so a filter never changes what a project did.
    """
    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.planning.fy_policy import horizon_label, planning_horizon
    from apps.projects.ssa_impact import project_impact

    fy = str(fy or get_operational_fy())
    # The operational year reads forward, as Cluster and Core School Oversight
    # do: in September the coordinator schedules October, which is the next
    # fiscal year, and a school scheduled then is not "Not planned yet".
    fys = planning_horizon(fy)
    whole = sees_whole_project(principal)
    controls = controls_project_work(principal)
    result = ProjectMonitoring(
        whole_project=whole or controls,
        controls=controls,
        lens_note=_lens_note(whole=whole, controls=controls),
        plan_period_label=horizon_label(fys),
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
    reads_whole = whole or controls
    totals = _activity_totals(project_ids, school_ids, fys=fys, whole=reads_whole)
    coordinators = _coordinator_names(projects)
    partners = _partner_names(project_ids)
    intervention_labels = dict(SsaIntervention.choices)
    school_rows = _school_rows(
        projects,
        assignments,
        fys=fys,
        controls=controls,
        intervention_labels=intervention_labels,
    )

    for project in projects:
        mine = by_project.get(project.id, [])
        if not reads_whole and not mine:
            # A project this reader has contributed nothing to in view. It is
            # not theirs to watch, and an empty row would read as a project
            # that has done nothing.
            continue
        counts = totals.get(project.id, {})
        primary, supporting = project.intervention_plan()
        everyone = school_rows.get(project.id, [])
        rows = [row for row in everyone if row.matches(stage)]
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
                assignments=None if reads_whole else mine,
            ),
            school_rows=rows,
            all_school_rows=everyone,
            accepts_new_work=project.accepts_new_work,
        )
        result.rows.append(row)
    return result


def _activity_totals(project_ids, school_ids, *, fys, whole: bool) -> dict:
    """Scheduled and delivered counts per project, in two queries.

    A watcher's counts are bounded by the schools they may see, so a CCEO's
    "12 trainings" is twelve trainings at their own schools — never the
    project's total relabelled as theirs.
    """
    from django.db.models import Count, Q

    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.projects.models import ProjectSchoolAssignment

    live = _live_project_activities(project_ids, fys)
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


def _live_project_activities(project_ids, fys):
    """The project-stamped work that is somebody's plan, in these years.

    Cancelled, rejected, deferred, never-planned and not-yet-approved rows are
    nobody's plan, on this page as on every funding and planning surface.
    """
    from apps.activities.models import Activity
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

    return Activity.objects.filter(
        project_id__in=project_ids, fy__in=tuple(fys), deleted_at__isnull=True
    ).exclude(status__in=(*NON_FUNDABLE_ACTIVITY_STATUSES, "not_planned"))


def _school_rows(
    projects, assignments, *, fys, controls: bool, intervention_labels
) -> dict[str, list[ProjectSchoolRow]]:
    """One row per visible enrolment, grouped by project.

    A fixed number of queries whatever the number of schools: the activities,
    the partner assignments, the names and the SSA readings are each read once
    for every enrolment on the page.
    """
    from urllib.parse import urlencode

    from apps.partners.models import PartnerAssignment
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        NEEDS_REPLANNING_STATUSES,
        VERIFIED_STATUSES,
    )

    if not assignments:
        return {}
    project_by_id = {project.id: project for project in projects}
    project_ids = list(project_by_id)
    school_ids = {assignment.school_id for assignment in assignments}
    today = date.today()

    activities: dict[tuple, list] = {}
    for activity in (
        _live_project_activities(project_ids, fys)
        .filter(school_id__in=school_ids)
        .only(
            "id",
            "project_id",
            "school_id",
            "status",
            "delivery_type",
            "assigned_partner_id",
            "responsible_staff_id",
            "planned_date",
            "actual_delivery_date",
        )
        .order_by("planned_date")
    ):
        activities.setdefault((activity.project_id, activity.school_id), []).append(
            activity
        )

    # Handovers the partner has not scheduled, and the ones handed back to
    # staff and not yet resolved. A scheduled handover is represented by the
    # activity it became, so it is not read twice.
    handovers: dict[tuple, list] = {}
    for handover in (
        PartnerAssignment.objects.filter(
            project_id__in=project_ids,
            school_id__in=school_ids,
            status__in=(
                *PartnerAssignment.UNSCHEDULED_STATUSES,
                PartnerAssignment.STATUS_RETURNED_TO_STAFF,
            ),
        )
        .select_related("partner")
        .order_by("created_at")
    ):
        if (
            handover.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF
            and handover.resolved_at is not None
        ):
            continue
        handovers.setdefault((handover.project_id, handover.school_id), []).append(
            handover
        )

    partner_ids = {
        activity.assigned_partner_id
        for rows in activities.values()
        for activity in rows
        if activity.assigned_partner_id
    }
    names = _people_names(
        {a.assigned_by for a in assignments if a.assigned_by}
        | {
            activity.responsible_staff_id
            for rows in activities.values()
            for activity in rows
            if activity.responsible_staff_id
        }
    )
    partner_names = _partner_lookup(partner_ids)
    readings = _focus_readings(projects, school_ids)
    coordinator_ids = _coordinator_ids(projects)

    out: dict[str, list[ProjectSchoolRow]] = {}
    for assignment in assignments:
        project = project_by_id[assignment.project_id]
        school = assignment.school
        key = (project.id, school.id)
        work = activities.get(key, [])
        open_handovers = handovers.get(key, [])
        enrolled_on = assignment.start_date or (
            assignment.created_at.date() if assignment.created_at else None
        )
        row = ProjectSchoolRow(
            assignment_id=assignment.id,
            project_id=project.id,
            school_pk=school.id,
            school_code=school.school_id or school.id,
            school_name=school.name,
            district=getattr(school.district, "name", "") or "",
            added_by=names.get(assignment.assigned_by, "") or "—",
            enrolled_on=enrolled_on,
        )

        # Execution first: it decides which of the plan's facts still matter.
        upcoming = [
            a
            for a in work
            if a.status
            not in AWAITING_VERIFICATION_STATUSES
            | VERIFIED_STATUSES
            | NEEDS_REPLANNING_STATUSES
        ]
        delivered = [a for a in work if a.status in AWAITING_VERIFICATION_STATUSES]
        verified = [a for a in work if a.status in VERIFIED_STATUSES]
        returned = [a for a in work if a.status in NEEDS_REPLANNING_STATUSES]
        row.planned = len(work)
        row.delivered = len(delivered) + len(verified)
        row.verified = len(verified)
        if verified:
            row.execution = EXEC_VERIFIED
        elif delivered:
            row.execution = EXEC_DELIVERED
        elif returned:
            row.execution = EXEC_RETURNED
        elif upcoming:
            row.execution = EXEC_SCHEDULED
        done_dates = [
            a.actual_delivery_date or a.planned_date
            for a in delivered + verified
            if a.actual_delivery_date or a.planned_date
        ]
        row.last_delivered_on = max(done_dates) if done_dates else None

        # Who has the work. The next thing to happen at the school decides
        # it; with nothing ahead, the most recent thing that did.
        dated = [a for a in upcoming if a.planned_date and a.planned_date >= today]
        ahead = (dated or upcoming or [None])[0]
        latest = ahead or (work[-1] if work else None)
        row.next_date = ahead.planned_date if ahead else None
        if latest is not None:
            if latest.delivery_type == "partner" or latest.assigned_partner_id:
                # Handed to the partner as an activity but not yet dated by
                # them is still the partner's to schedule (My Plan reads it
                # the same way: "Pending Partner Scheduling").
                row.plan_stage = (
                    PLAN_PARTNER_AWAITING
                    if latest.status == "assigned_to_partner"
                    or (latest is ahead and not latest.planned_date)
                    else PLAN_PARTNER_SCHEDULED
                )
                row.partner_name = partner_names.get(latest.assigned_partner_id, "")
            else:
                row.plan_stage = PLAN_STAFF_PLANNED
                row.planned_by = names.get(latest.responsible_staff_id, "")
                row.planned_by_coordinator = str(
                    latest.responsible_staff_id or ""
                ) in coordinator_ids.get(project.id, set())
        awaiting = [
            h
            for h in open_handovers
            if h.status in PartnerAssignment.UNSCHEDULED_STATUSES
        ]
        handed_back = [
            h
            for h in open_handovers
            if h.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF
        ]
        if ahead is None and awaiting:
            # With the partner and not yet dated: the one state a coordinator
            # has to chase, so it wins over any history at the school.
            row.plan_stage = PLAN_PARTNER_AWAITING
            row.partner_name = getattr(awaiting[-1].partner, "name", "") or ""
            row.next_date = awaiting[-1].scheduled_date
        elif ahead is None and handed_back:
            row.plan_stage = PLAN_PARTNER_RETURNED
            row.partner_name = getattr(handed_back[-1].partner, "name", "") or ""

        _attach_ssa(row, assignment, project, readings, intervention_labels)

        if controls and project.accepts_new_work:
            # The two doors that stamp the project on the work. The generic
            # partner drawer files a school-support handover with no project
            # (planning_views.assign_partner_action_view), which would leave
            # this row reading "Not planned" after the coordinator acted.
            query = urlencode({"school_id": school.id, "project_id": project.id})
            row.schedule_url = f"/planning/schedule-modal?{query}"
            row.partner_url = f"/projects/planning/bulk-partner?{urlencode({'assignments': assignment.id})}"
        out.setdefault(project.id, []).append(row)
    return out


def _attach_ssa(row, assignment, project, readings, intervention_labels) -> None:
    """The school's focus interventions, and the engine's verdict on them.

    The verdict is the enrolment's own (``impact_classification``, written by
    ``ssa_impact.refresh_follow_up``) — this page never calls a movement an
    improvement by itself. The readings beside it are the plain facts: the
    confirmed score the school entered with and the latest confirmed score
    since, per focus intervention.
    """
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS

    primary, supporting = project.intervention_plan()
    matched = assignment.matched_intervention or primary
    codes = list(dict.fromkeys([c for c in [matched, primary, *supporting] if c]))
    school_readings = readings.get(assignment.school_id, {})
    entered = row.enrolled_on
    for code in codes:
        history = school_readings.get(code, [])
        before = [r for r in history if entered is None or r[0] <= entered]
        baseline = before[-1] if before else None
        baseline_score = baseline[1] if baseline else None
        if code == matched and assignment.baseline_score is not None:
            # The snapshot taken at enrolment is the project's baseline and is
            # never recomputed (ProjectSchoolAssignment.baseline_score).
            baseline_score = assignment.baseline_score
        since = [r for r in history if baseline is None or r[0] > baseline[0]]
        latest = since[-1] if since else None
        row.focus.append(
            InterventionReading(
                code=code,
                label=intervention_labels.get(code, code.replace("_", " ").title()),
                abbreviation=INTERVENTION_ABBREVIATIONS.get(code, ""),
                baseline=baseline_score,
                latest=latest[1] if latest else None,
                latest_on=latest[0] if latest else None,
            )
        )

    verdict = IMPACT_LABELS.get(assignment.impact_classification or "")
    if verdict:
        row.impact_label, row.impact_tone = verdict
    elif not codes:
        row.impact_label, row.impact_tone = "No focus set", TONE_NEUTRAL
    elif assignment.baseline_score is None and not any(
        reading.baseline is not None for reading in row.focus
    ):
        row.impact_label, row.impact_tone = "No baseline", TONE_WARNING
    elif row.verified == 0:
        row.impact_label, row.impact_tone = "Awaiting delivery", TONE_NEUTRAL
    else:
        row.impact_label, row.impact_tone = "Awaiting follow-up", TONE_INFO


def _focus_readings(projects, school_ids) -> dict[str, dict[str, list]]:
    """Confirmed scores per school and focus intervention, oldest first.

    One query for the page. Only IA-confirmed assessments count, and a score
    outside the scale is not evidence — the same rules as
    ``ssa_impact._readings``.
    """
    from apps.projects.ssa_impact import CONFIRMED, _valid
    from apps.ssa.models import SsaScore

    codes = {
        code
        for project in projects
        for code in project.target_intervention_list()
        if code
    }
    if not codes or not school_ids:
        return {}
    out: dict[str, dict[str, list]] = {}
    for school_id, code, score, assessed in (
        SsaScore.objects.filter(
            ssa_record__school_id__in=school_ids,
            ssa_record__verification_status=CONFIRMED,
            ssa_record__deleted_at__isnull=True,
            intervention__in=codes,
        )
        .order_by("ssa_record__date_of_ssa")
        .values_list(
            "ssa_record__school_id", "intervention", "score", "ssa_record__date_of_ssa"
        )
    ):
        if assessed is None or not _valid(score):
            continue
        day = assessed.date() if hasattr(assessed, "date") else assessed
        out.setdefault(school_id, {}).setdefault(code, []).append(
            (day, round(float(score), 2))
        )
    return out


def _people_names(ids) -> dict[str, str]:
    """Display names for staff ids in either id space, in one query."""
    from django.db.models import Q

    from apps.accounts.models import StaffProfile, User

    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    names: dict[str, str] = {}
    for profile in StaffProfile.objects.filter(
        Q(id__in=wanted) | Q(user_id__in=wanted)
    ).select_related("user"):
        label = getattr(profile.user, "name", "") or getattr(profile.user, "email", "")
        for key in (profile.id, profile.user_id):
            if key:
                names[key] = label
    for user_id, name, email in User.objects.filter(
        id__in=wanted - set(names)
    ).values_list("id", "name", "email"):
        names[user_id] = name or email
    return names


def _coordinator_ids(projects) -> dict[str, set[str]]:
    """Each project's coordinator, in both id spaces, in one query."""
    from apps.accounts.models import StaffProfile

    managers = {p.manager_staff_id for p in projects if p.manager_staff_id}
    if not managers:
        return {}
    users = dict(
        StaffProfile.objects.filter(id__in=managers).values_list("id", "user_id")
    )
    return {
        project.id: {
            str(i)
            for i in (project.manager_staff_id, users.get(project.manager_staff_id))
            if i
        }
        for project in projects
        if project.manager_staff_id
    }


def _partner_lookup(partner_ids) -> dict[str, str]:
    from apps.partners.models import Partner

    ids = {p for p in partner_ids if p}
    if not ids:
        return {}
    return dict(Partner.objects.filter(id__in=ids).values_list("id", "name"))


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
