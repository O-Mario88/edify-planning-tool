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

And later the same day, on the table itself:

  "build the table similar to the one of partner oversight ... Schools
  assigned to project cannot be withdrawn by the staff but the project
  coordinator can withdraw from the partner they assigned to and reassign to
  another partner. Users want to see the schools they have assigned to the
  project so make sure the tables for each of the project they have assigned
  schools to is available to them. They have read only access, Only Project
  coordinator can edit plan and do everything."

So each school row reads Partner Monitoring's columns — School ID, School
Name, Staff Name, Training, Purpose of Assignment, SSA Intervention, Status,
Activity date, Actions — and a school nobody has planned yet is Awaiting
Project Coordinator Action.

The rules:

* **Read only, except for the coordinator.** This module computes; it never
  writes. Scheduling a project activity and handing one to a partner stay the
  coordinator's, through the same drawers Project Planning opens; so do taking
  a school's work back from its partner, reassigning it, and deciding what
  happens to work a partner handed back (owner, 2026-09-24) — the page draws
  those controls for the Project Coordinator alone and the services refuse
  everyone else (``apps.projects.authority``). Everyone else reads, and asks
  the coordinator for work they need.
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
    "STATUS_LABELS",
    "WHOLE_PROJECT_ROLES",
    "ProjectMonitoringRow",
    "ProjectMonitoring",
    "enrolled_schools",
    "ProjectSchoolRow",
    "ProjectWorkLine",
    "controls_project_work",
    "find_school_row",
    "project_monitoring",
    "sees_whole_project",
    "watched_projects",
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

#: The page's other filters over the school rows (owner, 2026-10-05: "add all
#: other relevant filters like district"). Each reads one column of the table
#: and offers the values the reader's own rows hold, so no choice comes up
#: empty: ``(query key, label, the "all" choice, row attribute)``.
ROW_FILTERS = (
    ("district", "District", "All districts", "district"),
    ("partner", "Partner", "All partners", "partner_name"),
    ("training", "Training", "All trainings", "training_name"),
    ("purpose", "Purpose", "All purposes", "purpose_label"),
    ("activity", "Activity status", "All activity statuses", "activity_state_label"),
)


#: The table's Status column (owner, 2026-09-24), read like Partner
#: Monitoring's: the school waits on the Project Coordinator until they plan
#: it or hand it to a partner; a partner handover waits on the partner's date
#: and reads Scheduled, on that date, once the partner picks it.
STATUS_AWAITING_COORDINATOR = "awaiting_coordinator"
STATUS_AWAITING_PARTNER = "awaiting_partner"
STATUS_PARTNER_RETURNED = "partner_returned"
STATUS_SCHEDULED = "scheduled"
STATUS_IN_PROGRESS = "in_progress"
STATUS_AWAITING_VERIFICATION = "awaiting_verification"
STATUS_COMPLETED = "completed"
STATUS_RETURNED = "returned"

STATUS_LABELS = {
    STATUS_AWAITING_COORDINATOR: "Awaiting Project Coordinator Action",
    STATUS_AWAITING_PARTNER: "Awaiting Partner Schedule",
    STATUS_PARTNER_RETURNED: "Returned by Partner",
    STATUS_SCHEDULED: "Scheduled",
    STATUS_IN_PROGRESS: "In Progress",
    STATUS_AWAITING_VERIFICATION: "Awaiting Verification",
    STATUS_COMPLETED: "Completed",
    STATUS_RETURNED: "Returned",
}

#: Partner Monitoring's chip tones: blue while the work waits on somebody
#: else, amber while it is scheduled or under way, red when it came back,
#: green only once IA has verified it.
STATUS_TONES = {
    STATUS_AWAITING_COORDINATOR: TONE_INFO,
    STATUS_AWAITING_PARTNER: TONE_INFO,
    STATUS_PARTNER_RETURNED: TONE_DANGER,
    STATUS_SCHEDULED: TONE_WARNING,
    STATUS_IN_PROGRESS: TONE_WARNING,
    STATUS_AWAITING_VERIFICATION: TONE_INFO,
    STATUS_COMPLETED: TONE_SUCCESS,
    STATUS_RETURNED: TONE_DANGER,
}


#: The table's Activity Status column (owner, 2026-10-05: "Activity Status
#: (Scheduled, Completed, Canceled, rescheduled)"): where the row's own
#: activity stands, in one of four words. Work with no day on it yet — a
#: school waiting on the coordinator, a handover its partner has not dated —
#: has no activity status.
ACTIVITY_SCHEDULED = "scheduled"
ACTIVITY_RESCHEDULED = "rescheduled"
ACTIVITY_COMPLETED = "completed"
ACTIVITY_CANCELLED = "cancelled"

ACTIVITY_STATE_LABELS = {
    ACTIVITY_SCHEDULED: "Scheduled",
    ACTIVITY_RESCHEDULED: "Rescheduled",
    ACTIVITY_COMPLETED: "Completed",
    ACTIVITY_CANCELLED: "Cancelled",
}
ACTIVITY_STATE_TONES = {
    ACTIVITY_SCHEDULED: TONE_WARNING,
    ACTIVITY_RESCHEDULED: TONE_WARNING,
    ACTIVITY_COMPLETED: TONE_SUCCESS,
    ACTIVITY_CANCELLED: TONE_DANGER,
}
#: An activity is priced when it is scheduled, so the Activity Cost column
#: reads a cost only for work that has its day (owner, 2026-10-05: "Only
#: fetch if scheduled"). Cancelled work, and work nobody has dated, has none.
COSTED_ACTIVITY_STATES = frozenset(
    {ACTIVITY_SCHEDULED, ACTIVITY_RESCHEDULED, ACTIVITY_COMPLETED}
)

#: The SSA Intervention of a project no SSA intervention measures (Alumni).
GENERAL = "General"


@dataclass
class ProjectWorkLine:
    """One piece of project work at a school — a dated activity, or a partner
    handover the partner has not scheduled or handed back — in the table's
    words. Every value is read from the Activity or PartnerAssignment row."""

    kind: str
    id: str
    training_name: str = ""
    purpose_label: str = ""
    intervention_label: str = ""
    #: The SSA intervention the work names, as its code, for the scores.
    intervention_code: str = ""
    status_key: str = STATUS_SCHEDULED
    #: One of ACTIVITY_STATE_LABELS, or nothing while the work has no day.
    activity_state: str = ""
    #: The activities whose cost lines are this work's cost: itself, and the
    #: other half of an in-school Training / School Visit pair.
    cost_activity_ids: tuple = ()
    delivered_by: str = ""
    by_partner: bool = False
    activity_date: date | None = None
    #: The PartnerAssignment behind partner work, for the coordinator's doors.
    handover_id: str = ""
    #: Filled in for the Project Coordinator only.
    withdraw_label: str = ""
    withdraw_url: str = ""
    resolve_url: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status_key]

    @property
    def status_tone(self) -> str:
        return STATUS_TONES[self.status_key]


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
    project_name: str = ""

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
    #: Whether a partner may be handed work here at all: a closed school
    #: takes no new work, and a Champion school is delivered by staff unless
    #: project hand-overs go past that rule (`partners.handover_policy`).
    #: A school a partner may not take has no tick box.
    takes_partner_work: bool = True

    #: The table's columns (owner, 2026-09-24): Training, Purpose of
    #: Assignment, SSA Intervention, Status and Activity date, read from the
    #: one piece of work that says where the school stands — the next thing
    #: planned, else a handover still with its partner, else one handed back,
    #: else the latest work done. With none of those the school is waiting on
    #: the Project Coordinator.
    training_name: str = ""
    purpose_label: str = ""
    intervention_label: str = ""
    status_key: str = STATUS_AWAITING_COORDINATOR
    activity_date: date | None = None
    #: The scores beside the SSA Intervention (owner, 2026-10-05: "Previous
    #: SSA Score, Current SSA Score, SSA Improvement"): the school's confirmed
    #: score in that intervention when it joined the project, and its latest
    #: confirmed score since. Empty for General, and until an SSA says.
    intervention_code: str = ""
    previous_score: float | None = None
    current_score: float | None = None
    #: The row's own activity in four words (ACTIVITY_STATE_LABELS), and its
    #: planned cost in UGX once it is scheduled.
    activity_state: str = ""
    activity_cost: int | None = None
    cost_activity_ids: tuple = ()
    #: Every piece of project work at the school, for the row's details and
    #: its View drawer: nothing the Status sums up is hidden.
    work: list[ProjectWorkLine] = field(default_factory=list)
    #: The read-only View drawer, for every reader.
    detail_url: str = ""
    #: The coordinator's doors on the row's own partner work.
    withdraw_label: str = ""
    withdraw_url: str = ""
    #: Taking the school out of the project (brief, 2026-09-29), drawn for
    #: the staff member who added it and the project's coordinator. With
    #: work begun the control stays, greyed, with the reason.
    leave_url: str = ""
    leave_block: str = ""
    resolve_url: str = ""

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status_key]

    @property
    def status_tone(self) -> str:
        return STATUS_TONES[self.status_key]

    @property
    def awaiting_date(self) -> bool:
        """A partner holds the work and has not picked its day yet."""
        return self.status_key == STATUS_AWAITING_PARTNER

    @property
    def plan_label(self) -> str:
        if self.plan_stage == PLAN_STAFF_PLANNED and not self.planned_by_coordinator:
            return "Staff planned"
        return PLAN_LABELS[self.plan_stage]

    @property
    def planning_stage(self) -> str:
        """The Planning Stage column (owner, 2026-10-05: "Awaiting {Partner
        Name}"): work a Partner holds names the Partner it waits on."""
        if self.partner_name and self.plan_stage == PLAN_PARTNER_AWAITING:
            return f"Awaiting {self.partner_name}"
        if self.partner_name and self.plan_stage == PLAN_PARTNER_RETURNED:
            return f"Returned by {self.partner_name}"
        return self.plan_label

    @property
    def planned_by_name(self) -> str:
        """The Planned By column: the Partner once the Partner has scheduled
        the work, the staff member who planned it otherwise. Nobody has
        planned work that is still waiting on its Partner or the coordinator."""
        if self.plan_stage == PLAN_PARTNER_SCHEDULED:
            return self.partner_name
        if self.plan_stage == PLAN_STAFF_PLANNED:
            return self.planned_by
        return ""

    @property
    def ssa_improvement(self) -> float | None:
        """Current SSA score less the previous one; nothing until both exist."""
        if self.previous_score is None or self.current_score is None:
            return None
        return round(self.current_score - self.previous_score, 2)

    @property
    def ssa_improvement_tone(self) -> str:
        """Green for a score that rose, red for one that fell, neutral for
        no change (owner, 2026-10-05)."""
        change = self.ssa_improvement
        if not change:
            return TONE_NEUTRAL
        return TONE_SUCCESS if change > 0 else TONE_DANGER

    @property
    def execution_summary(self) -> str:
        if not self.planned:
            return self.execution_label
        return f"{self.execution_label} · {self.delivered}/{self.planned} done"

    @property
    def activity_state_label(self) -> str:
        return ACTIVITY_STATE_LABELS.get(self.activity_state, "")

    @property
    def activity_state_tone(self) -> str:
        return ACTIVITY_STATE_TONES.get(self.activity_state, TONE_NEUTRAL)

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

    @property
    def can_tick(self) -> bool:
        """Whether the coordinator may tick this school for a bulk hand-over
        to a partner: the row offers Assign, and a partner may take it."""
        return bool(self.partner_url) and self.takes_partner_work

    def matches(self, stage: str, picks: dict | None = None) -> bool:
        """Whether this row belongs under the page's filters: one of the
        stage filters, and every column value picked (ROW_FILTERS)."""
        for key, _label, _all, attribute in ROW_FILTERS:
            wanted = (picks or {}).get(key)
            if wanted and getattr(self, attribute) != wanted:
                return False
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
    #: School allocations (apps.projects.capacity): the whole project's for a
    #: whole-project reader, this reader's own otherwise. None when the
    #: project is not capacity-managed.
    capacity: dict | None = None
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

    @property
    def selectable(self) -> bool:
        """Whether the table carries tick boxes: some school in it may be
        handed to a partner by this reader."""
        return any(row.can_tick for row in self.school_rows)


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
    #: This reader's own school allocations, one per project (My Projects).
    allocations: list = field(default_factory=list)

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
            "Every school in the projects you coordinate. Schedule the work, "
            "assign it to a partner, or withdraw it from a partner and reassign "
            "it, from a school's row — or from Project Planning."
        )
    if whole:
        return "Every school in every live project."
    return (
        "Only the schools you added to a project. Schools other officers added "
        "are theirs to watch."
    )


def project_monitoring(
    principal,
    *,
    fy: str | None = None,
    project_id: str = "",
    stage: str = "",
    picks: dict | None = None,
) -> ProjectMonitoring:
    """What the coordinator and their partners have done, for this reader.

    ``stage`` narrows each project's school rows to one of STAGE_FILTERS and
    ``picks`` to the column values chosen (ROW_FILTERS); the project figures
    stay whole, so a filter never changes what a project did.
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

    from apps.projects import capacity as project_capacity

    own_staff = getattr(principal, "staff_profile_id", None)
    result.allocations = project_capacity.allocations_for_staff(own_staff)

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

    # Who may take a school out of a project from here: the coordinator (and
    # Admin) any school in view; a CCEO or Programme Lead the schools they
    # added, which are the only ones they see. IA and the Country Director
    # watch. One pair of queries decides every row (capacity.withdrawal_blocks).
    may_withdraw = controls or (
        getattr(principal, "active_role", "") == "Admin" or not whole
    )
    blocks = (
        project_capacity.withdrawal_blocks(
            (assignment.project_id, assignment.school_id) for assignment in assignments
        )
        if may_withdraw
        else {}
    )
    allocations = project_capacity.allocations_by_project(project_ids)

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
        if may_withdraw:
            for school_row in everyone:
                block = blocks.get((project.id, school_row.school_pk))
                school_row.leave_url = (
                    f"/projects/capacity/withdraw?enrolment={school_row.assignment_id}"
                )
                school_row.leave_block = block.message if block else ""
        project_allocations = allocations.get(project.id, [])
        capacity_line = None
        if project_allocations:
            if reads_whole:
                capacity_line = project_capacity.project_summary(
                    project, project_allocations
                )
            else:
                own = next(
                    (a for a in project_allocations if a.staff_id == own_staff), None
                )
                if own is not None:
                    capacity_line = {
                        "capacity": own.maximum,
                        "assigned": own.assigned,
                        "remaining": own.remaining,
                        "own": True,
                    }
        rows = [row for row in everyone if row.matches(stage, picks)]
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
            capacity=capacity_line,
            all_school_rows=everyone,
            accepts_new_work=project.accepts_new_work,
        )
        result.rows.append(row)
    return result


def row_picks(query) -> dict[str, str]:
    """The column values a request asks the school rows to be narrowed to."""
    return {
        key: value
        for key, _label, _all, _attribute in ROW_FILTERS
        if (value := (query.get(key) or "").strip())
    }


def row_filter_options(result: ProjectMonitoring, picks: dict | None = None) -> list:
    """Each of ROW_FILTERS with the values this reader's schools hold, across
    every project in view, so a filter keeps its choices from tab to tab. A
    value asked for that no school holds stays listed: the table is then
    empty and the filter says why."""
    picks = picks or {}
    rows = [row for entry in result.rows for row in entry.all_school_rows]
    out = []
    for key, label, all_label, attribute in ROW_FILTERS:
        values = {getattr(row, attribute) for row in rows}
        values.add(picks.get(key, ""))
        out.append(
            {
                "key": key,
                "label": label,
                "selected": picks.get(key, ""),
                "options": [
                    ("", all_label),
                    *((v, v) for v in sorted(filter(None, values), key=str.casefold)),
                ],
            }
        )
    return out


def watched_projects(principal) -> list:
    """The live projects this reader may watch, by name."""
    return list(_projects_for(principal))


def enrolled_schools(principal, *, fy: str | None = None) -> list[tuple]:
    """Every enrolment this reader may see, as ``(project, coordinator, row)``.

    The consolidated Project Schools table (owner, 2026-10-02: "all the
    project assigned schools fetched direct from the project coordinators")
    lists the page's own school rows — the same lens, the same reading of who
    holds the work and where it stands — without the project figures the page
    draws above them.
    """
    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.planning.fy_policy import planning_horizon

    projects = list(_projects_for(principal))
    if not projects:
        return []
    assignments = list(_visible_assignments(principal, [p.id for p in projects]))
    rows = _school_rows(
        projects,
        assignments,
        fys=planning_horizon(str(fy or get_operational_fy())),
        controls=False,
        intervention_labels=dict(SsaIntervention.choices),
    )
    coordinators = _coordinator_names(projects)
    return [
        (project, coordinators.get(project.id, "Not assigned"), row)
        for project in projects
        for row in rows.get(project.id, [])
    ]


def find_school_row(principal, enrolment_id: str, *, fy: str | None = None):
    """One enrolment as this reader's lens builds it: ``(project, row)``, or
    ``(None, None)`` when the reader may not see it.

    The View drawer asks for a school by its enrolment id. Rebuilding it
    through ``project_monitoring`` — the same lens as the page — means an id
    belonging to another officer's enrolment resolves to nothing rather than
    to a school the page would not have shown.
    """
    from apps.projects.models import ProjectSchoolAssignment

    project_id = (
        ProjectSchoolAssignment.objects.filter(id=enrolment_id)
        .values_list("project_id", flat=True)
        .first()
    )
    if not project_id:
        return None, None
    result = project_monitoring(principal, fy=fy, project_id=project_id)
    for project_row in result.rows:
        for row in project_row.all_school_rows:
            if row.assignment_id == enrolment_id:
                return project_row, row
    return None, None


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
    from apps.partners.handover_policy import past_school_rules
    from apps.planning.visit_gate import OUTREACH_ONLY_SCHOOL_TYPES

    if not assignments:
        return {}
    # Every row here is a project's, so its hand-over goes past the Champion
    # rule while the owner's lift holds (2026-10-05).
    champions_too = past_school_rules(project_id="any")
    project_by_id = {project.id: project for project in projects}
    project_ids = list(project_by_id)
    school_ids = {assignment.school_id for assignment in assignments}
    today = date.today()

    activities: dict[tuple, list] = {}
    for activity in (
        _live_project_activities(project_ids, fys)
        .filter(school_id__in=school_ids)
        .select_related("training_course")
        .only(
            "id",
            "project_id",
            "school_id",
            "status",
            "delivery_type",
            "assigned_partner_id",
            "responsible_staff_id",
            "planned_date",
            "scheduled_date",
            "actual_delivery_date",
            # The table's Training, Purpose and SSA Intervention columns, and
            # what a withdrawal would be — read here so no row queries again.
            "activity_type",
            "purpose_type",
            "focus_intervention",
            "purpose_intervention",
            "activity_name_snapshot",
            "evidence_status",
            "payment_status",
            # The Activity Status and Activity Cost columns.
            "reschedule_count",
            "paired_school_visit",
            "training_course",
            "training_course__display_name",
            "training_course__source_name",
        )
        .order_by("planned_date")
    ):
        activities.setdefault((activity.project_id, activity.school_id), []).append(
            activity
        )
    called_off = _cancelled_activities(project_ids, school_ids, fys)

    # Every project handover at these schools, in one query: the ones the
    # partner has not scheduled and the ones handed back to staff and not yet
    # resolved are rows of their own; a scheduled one is represented by the
    # activity it became, and is kept only to name that activity's handover.
    handovers: dict[tuple, list] = {}
    by_activity: dict[str, object] = {}
    for handover in (
        PartnerAssignment.objects.filter(
            project_id__in=project_ids, school_id__in=school_ids
        )
        .select_related(
            "partner",
            "training_course",
            "catalogue_item",
            "source_activity__training_course",
        )
        .order_by("created_at")
    ):
        if handover.scheduled_activity_id:
            by_activity[handover.scheduled_activity_id] = handover
        if handover.status not in (
            *PartnerAssignment.UNSCHEDULED_STATUSES,
            PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        ):
            continue
        if (
            handover.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF
            and handover.resolved_at is not None
        ):
            # Decided — by staff, or by the withdrawal that took it back.
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
    # The scores of every intervention a row may name: the projects' targets,
    # and whatever the work at a school or its enrolment names besides.
    named = {
        code
        for rows in (*activities.values(), *called_off.values())
        for activity in rows
        for code in (activity.focus_intervention, activity.purpose_intervention)
    }
    named.update(h.focus_intervention for rows in handovers.values() for h in rows)
    named.update(h.focus_intervention for h in by_activity.values())
    for assignment in assignments:
        named.update((assignment.matched_intervention, assignment.support_area))
    readings = _focus_readings(projects, school_ids, also=named)
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
            project_name=project.name,
            detail_url=(
                f"/projects/monitoring/school?{urlencode({'enrolment': assignment.id})}"
            ),
            takes_partner_work=not school.is_closed
            and (champions_too or school.school_type not in OUTREACH_ONLY_SCHOOL_TYPES),
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
        _attach_work(
            row,
            assignment,
            project,
            work=work,
            ahead=ahead,
            awaiting=awaiting,
            handed_back=handed_back,
            called_off=called_off.get(key, []),
            by_activity=by_activity,
            partner_names=partner_names,
            names=names,
            controls=controls,
        )
        _attach_scores(
            row, assignment, readings.get(school.id, {}), intervention_labels
        )

        if controls and project.accepts_new_work:
            # The two doors that stamp the project on the work. The generic
            # partner drawer files a school-support handover with no project
            # (planning_views.assign_partner_action_view), which would leave
            # this row reading "Not planned" after the coordinator acted.
            query = urlencode({"school_id": school.id, "project_id": project.id})
            row.schedule_url = f"/planning/schedule-modal?{query}"
            row.partner_url = f"/projects/planning/bulk-partner?{urlencode({'assignments': assignment.id})}"
        out.setdefault(project.id, []).append(row)
    _attach_costs([row for rows in out.values() for row in rows])
    return out


def _cancelled_activities(project_ids, school_ids, fys) -> dict[tuple, list]:
    """Project work that was called off, by (project, school), oldest first.

    Cancelled work is nobody's plan and stays out of every count on the page
    (``_live_project_activities``). It is read for one thing: a school whose
    work was cancelled and not planned again says so in its Activity Status,
    rather than reading as a school nothing was ever planned for.
    """
    from apps.activities.models import Activity

    out: dict[tuple, list] = {}
    for activity in (
        Activity.objects.filter(
            project_id__in=project_ids,
            school_id__in=school_ids,
            fy__in=tuple(fys),
            deleted_at__isnull=True,
            status="cancelled",
        )
        .select_related("training_course")
        .only(
            "id",
            "project_id",
            "school_id",
            "status",
            "planned_date",
            "activity_type",
            "purpose_type",
            "focus_intervention",
            "purpose_intervention",
            "activity_name_snapshot",
            "training_course",
            "training_course__display_name",
            "training_course__source_name",
        )
        .order_by("planned_date", "updated_at")
    ):
        out.setdefault((activity.project_id, activity.school_id), []).append(activity)
    return out


def _attach_costs(rows) -> None:
    """Each row's Activity Cost, in one query for the page.

    Read from the activity's cost lines, which scheduling writes and the fund
    request and the budget are built from, so the table cannot disagree with
    them. An activity with no line has no recorded cost, which is not a cost
    of nothing.
    """
    from apps.planning.oversight_service import _cost_by_activity

    wanted = {
        activity_id
        for row in rows
        if row.activity_state in COSTED_ACTIVITY_STATES
        for activity_id in row.cost_activity_ids
    }
    if not wanted:
        return
    costs = _cost_by_activity(sorted(wanted))
    for row in rows:
        if row.activity_state not in COSTED_ACTIVITY_STATES:
            continue
        priced = [costs[i] for i in row.cost_activity_ids if i in costs]
        row.activity_cost = sum(priced) if priced else None


def _activity_status_key(activity, *, by_partner: bool) -> str:
    """Where one project activity stands, in the table's Status words."""
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        NEEDS_REPLANNING_STATUSES,
        VERIFIED_STATUSES,
    )

    status = activity.status or ""
    if status in VERIFIED_STATUSES:
        return STATUS_COMPLETED
    if status in AWAITING_VERIFICATION_STATUSES:
        return STATUS_AWAITING_VERIFICATION
    if status in NEEDS_REPLANNING_STATUSES:
        return STATUS_RETURNED
    if by_partner and (status == "assigned_to_partner" or not activity.planned_date):
        # With the partner and not dated by them yet (My Plan: "Pending
        # Partner Scheduling"). It reads Scheduled once they pick the day.
        return STATUS_AWAITING_PARTNER
    if status in ("in_progress", "completion_started"):
        return STATUS_IN_PROGRESS
    return STATUS_SCHEDULED


def _activity_state(activity, status_key: str, day) -> str:
    """The Activity Status of one live activity: Completed once it has been
    carried out, Scheduled while it has a day ahead of it — Rescheduled if
    that day has been moved. Work its Partner has not dated, and work sent
    back to be planned again, is in none of the four."""
    if status_key in (STATUS_AWAITING_VERIFICATION, STATUS_COMPLETED):
        return ACTIVITY_COMPLETED
    if status_key == STATUS_IN_PROGRESS:
        return ACTIVITY_SCHEDULED
    if status_key != STATUS_SCHEDULED or day is None:
        return ""
    moved = activity.status == "rescheduled" or (activity.reschedule_count or 0) > 0
    return ACTIVITY_RESCHEDULED if moved else ACTIVITY_SCHEDULED


def _pair_ids(activity, work) -> tuple:
    """The activities whose cost lines are this activity's cost.

    An in-school Training and its School Visit are one day's work with one
    cost, carried by the visit (apps.activities.pair_costing). One row speaks
    for the school, so whichever half it shows reads the cost of both.
    """
    ids = [activity.id]
    if activity.paired_school_visit_id:
        ids.append(activity.paired_school_visit_id)
    ids.extend(
        other.id for other in work if other.paired_school_visit_id == activity.id
    )
    return tuple(dict.fromkeys(ids))


def _activity_line(
    activity, handover, *, partner_names, names, work=()
) -> ProjectWorkLine:
    from apps.planning.partner_oversight_service import activity_day, describe_work

    by_partner = activity.delivery_type == "partner" or bool(
        activity.assigned_partner_id
    )
    status_key = _activity_status_key(activity, by_partner=by_partner)
    if handover is not None:
        # The handover says why the school was handed over and which course;
        # the activity the partner created says when.
        training, purpose, intervention = describe_work(
            purpose_code=handover.purpose_of_visit or "",
            activity_type=activity.activity_type or "",
            course=handover.training_course,
            catalogue_item=handover.catalogue_item,
            source_activity=handover.source_activity,
            activity=activity,
            focus=handover.focus_intervention or "",
        )
    else:
        training, purpose, intervention = describe_work(activity=activity)
    if status_key == STATUS_AWAITING_PARTNER:
        day = None
    elif status_key in (
        STATUS_AWAITING_VERIFICATION,
        STATUS_COMPLETED,
        STATUS_RETURNED,
    ):
        day = activity.actual_delivery_date or activity_day(activity)
    else:
        day = activity_day(activity)
    return ProjectWorkLine(
        kind="activity",
        id=activity.id,
        training_name=training,
        purpose_label=purpose,
        intervention_label=intervention,
        intervention_code=(
            getattr(handover, "focus_intervention", "")
            or activity.focus_intervention
            or activity.purpose_intervention
            or ""
        ),
        status_key=status_key,
        activity_state=_activity_state(activity, status_key, day),
        cost_activity_ids=_pair_ids(activity, work),
        delivered_by=(
            partner_names.get(activity.assigned_partner_id, "")
            if by_partner
            else names.get(activity.responsible_staff_id, "")
        ),
        by_partner=by_partner,
        activity_date=day,
        handover_id=getattr(handover, "id", "") or "",
    )


def _handover_line(handover, status_key: str) -> ProjectWorkLine:
    from apps.planning.partner_oversight_service import describe_work

    training, purpose, intervention = describe_work(
        purpose_code=handover.purpose_of_visit or "",
        activity_type=handover.expected_activity_type or "",
        course=handover.training_course,
        catalogue_item=handover.catalogue_item,
        source_activity=handover.source_activity,
        focus=handover.focus_intervention or "",
    )
    return ProjectWorkLine(
        kind="handover",
        id=handover.id,
        training_name=training,
        purpose_label=purpose,
        intervention_label=intervention,
        intervention_code=handover.focus_intervention or "",
        status_key=status_key,
        delivered_by=getattr(handover.partner, "name", "") or "",
        by_partner=True,
        handover_id=handover.id,
    )


def _attach_doors(line: ProjectWorkLine, handover, activity=None) -> None:
    """The Project Coordinator's doors on one piece of partner work.

    Withdraw (or reassign) while the withdrawal service would act on it —
    its own ``resolve_kind`` names the action, so the button says what the
    service will do — and Resolve on a hand-back nobody has decided yet. The
    routes check the coordinator again, and the services a third time.
    """
    from urllib.parse import urlencode

    from apps.partners.models import PartnerAssignment
    from apps.partners.withdrawal_models import WithdrawalKind
    from apps.partners.withdrawal_service import resolve_kind

    if handover is None:
        return
    query = urlencode({"handover": handover.id})
    if handover.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
        # Work handed back waits on the coordinator until a decision is
        # recorded (a withdrawal records its own when it is made).
        if handover.resolved_at is None:
            line.resolve_url = f"/projects/monitoring/resolve?{query}"
        return
    if handover.scheduled_activity_id and activity is None:
        # Its activity lies outside the years this page reads; the partner's
        # own record decides, not a guess from here.
        return
    kind = resolve_kind(handover, activity)
    if kind == WithdrawalKind.BLOCKED:
        return
    line.withdraw_label = WithdrawalKind(kind).label
    line.withdraw_url = f"/projects/monitoring/withdraw?{query}"


def _attach_work(
    row,
    assignment,
    project,
    *,
    work,
    ahead,
    awaiting,
    handed_back,
    by_activity,
    partner_names,
    names,
    controls: bool,
    called_off=(),
) -> None:
    """Fill the row's Training, Purpose of Assignment, SSA Intervention,
    Status, Activity date, Activity Status and whose cost it reads, and the
    list of every piece of work behind them.

    One piece of work speaks for the school: the next thing planned, else a
    handover still with its partner, else one handed back, else the latest
    work done. With none, the school is waiting on the Project Coordinator —
    and then Purpose and SSA Intervention say what the school was added for,
    or, where its work was cancelled and not planned again, what was called
    off.
    """
    measured = project.measured_by_ssa
    lines: dict[str, ProjectWorkLine] = {}
    for activity in work:
        handover = by_activity.get(activity.id)
        line = _activity_line(
            activity, handover, partner_names=partner_names, names=names, work=work
        )
        if controls:
            _attach_doors(line, handover, activity)
        lines[f"a:{activity.id}"] = line
    for handover in awaiting:
        line = _handover_line(handover, STATUS_AWAITING_PARTNER)
        if controls:
            _attach_doors(line, handover)
        lines[f"h:{handover.id}"] = line
    for handover in handed_back:
        line = _handover_line(handover, STATUS_PARTNER_RETURNED)
        if controls:
            _attach_doors(line, handover)
        lines[f"h:{handover.id}"] = line

    focus = None
    if ahead is not None:
        focus = lines[f"a:{ahead.id}"]
    elif awaiting:
        focus = lines[f"h:{awaiting[-1].id}"]
    elif handed_back:
        focus = lines[f"h:{handed_back[-1].id}"]
    elif work:
        last = max(
            work,
            key=lambda a: a.actual_delivery_date or a.planned_date or date.min,
        )
        focus = lines[f"a:{last.id}"]

    if not measured:
        # No SSA intervention measures this project (Alumni): its work is
        # General, whatever a record happens to name (owner, 2026-10-05).
        for line in lines.values():
            line.intervention_label, line.intervention_code = GENERAL, ""
    row.work = sorted(
        lines.values(),
        key=lambda line: (line.activity_date is None, line.activity_date or date.min),
    )
    enrolled_for = _enrolment_intervention(assignment, project)
    enrolled_code = _enrolment_code(assignment, project)
    if focus is None:
        row.status_key = STATUS_AWAITING_COORDINATOR
        row.purpose_label = assignment.participation_type or ""
        row.intervention_label = enrolled_for
        row.intervention_code = enrolled_code
        if called_off:
            # The school is the coordinator's to plan again; the row says
            # what was called off, and carries no date and no cost for it.
            from apps.planning.partner_oversight_service import describe_work

            last = called_off[-1]
            training, purpose, intervention = describe_work(activity=last)
            row.activity_state = ACTIVITY_CANCELLED
            row.training_name = training
            row.purpose_label = purpose or row.purpose_label
            if measured and intervention:
                row.intervention_label = intervention
                row.intervention_code = (
                    last.focus_intervention or last.purpose_intervention or ""
                )
        return
    row.training_name = focus.training_name
    row.purpose_label = focus.purpose_label
    if focus.intervention_label:
        row.intervention_label = focus.intervention_label
        row.intervention_code = focus.intervention_code
    else:
        row.intervention_label = enrolled_for
        row.intervention_code = enrolled_code
    row.status_key = focus.status_key
    row.activity_date = focus.activity_date
    row.activity_state = focus.activity_state
    row.cost_activity_ids = focus.cost_activity_ids
    row.withdraw_label = focus.withdraw_label
    row.withdraw_url = focus.withdraw_url
    row.resolve_url = focus.resolve_url


def _enrolment_intervention(assignment, project) -> str:
    """The intervention a school is in the project for: the need it was
    matched on, else the focus area chosen when it was added, else the
    project's primary target."""
    from apps.core.enums import SsaIntervention
    from apps.planning.partner_oversight_service import choice_label

    if not project.measured_by_ssa:
        # No SSA intervention measures this project (Alumni): it is General,
        # whatever need the school happened to show when it joined.
        return GENERAL
    return choice_label(_enrolment_code(assignment, project), SsaIntervention)


def _enrolment_code(assignment, project) -> str:
    """``_enrolment_intervention`` as a code; nothing for General."""
    if not project.measured_by_ssa:
        return ""
    primary, _supporting = project.intervention_plan()
    return assignment.matched_intervention or assignment.support_area or primary or ""


def _reading(
    code, assignment, *, entered, history, matched, labels
) -> InterventionReading:
    """One intervention at one school: the confirmed score it entered the
    project with, and the latest confirmed score since."""
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS

    before = [r for r in history if entered is None or r[0] <= entered]
    baseline = before[-1] if before else None
    baseline_score = baseline[1] if baseline else None
    if code == matched and assignment.baseline_score is not None:
        # The snapshot taken at enrolment is the project's baseline and is
        # never recomputed (ProjectSchoolAssignment.baseline_score).
        baseline_score = assignment.baseline_score
    since = [r for r in history if baseline is None or r[0] > baseline[0]]
    latest = since[-1] if since else None
    return InterventionReading(
        code=code,
        label=labels.get(code, code.replace("_", " ").title()),
        abbreviation=INTERVENTION_ABBREVIATIONS.get(code, ""),
        baseline=baseline_score,
        latest=latest[1] if latest else None,
        latest_on=latest[0] if latest else None,
    )


def _attach_scores(row, assignment, school_readings, intervention_labels) -> None:
    """Previous and Current SSA Score for the row's SSA Intervention.

    The same reading the row's focus interventions take (``_reading``): the
    school's confirmed score in that intervention when it joined the project,
    and its latest confirmed score since. A school with no confirmed SSA
    since it joined has no current score yet, and so no improvement — an
    empty cell, never a nought.
    """
    code = row.intervention_code
    if not code:
        return
    reading = next((r for r in row.focus if r.code == code), None) or _reading(
        code,
        assignment,
        entered=row.enrolled_on,
        history=school_readings.get(code, []),
        matched=assignment.matched_intervention,
        labels=intervention_labels,
    )
    row.previous_score = reading.baseline
    row.current_score = reading.latest


def _attach_ssa(row, assignment, project, readings, intervention_labels) -> None:
    """The school's focus interventions, and the engine's verdict on them.

    The verdict is the enrolment's own (``impact_classification``, written by
    ``ssa_impact.refresh_follow_up``) — this page never calls a movement an
    improvement by itself. The readings beside it are the plain facts: the
    confirmed score the school entered with and the latest confirmed score
    since, per focus intervention.
    """
    primary, supporting = project.intervention_plan()
    matched = assignment.matched_intervention or primary
    codes = list(dict.fromkeys([c for c in [matched, primary, *supporting] if c]))
    school_readings = readings.get(assignment.school_id, {})
    for code in codes:
        row.focus.append(
            _reading(
                code,
                assignment,
                entered=row.enrolled_on,
                history=school_readings.get(code, []),
                matched=matched,
                labels=intervention_labels,
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


def _focus_readings(projects, school_ids, *, also=()) -> dict[str, dict[str, list]]:
    """Confirmed scores per school and focus intervention, oldest first.

    One query for the page. Only IA-confirmed assessments count, and a score
    outside the scale is not evidence — the same rules as
    ``ssa_impact._readings``. ``also`` adds the interventions the work at a
    school names beyond its project's targets.
    """
    from apps.core.enums import SsaIntervention
    from apps.projects.ssa_impact import CONFIRMED, _valid
    from apps.ssa.models import SsaScore

    codes = {
        code
        for project in projects
        for code in project.target_intervention_list()
        if code
    }
    codes.update(code for code in also if code in SsaIntervention.values)
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
