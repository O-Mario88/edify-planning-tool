"""Partner oversight — the Program Lead's lens on partner-delivered work.

The responsibility model this serves, stated once:

    a CCEO assigns the support item, because they know the school;
    the partner controls scheduling and execution once they accept;
    the Program Lead owns team-level monitoring and can act only by asking;
    the CCEO keeps school-context visibility and the evidence handoff.

Like `oversight_service`, this owns no table and writes nothing. It reads
PartnerAssignment, the Activity a partner created when scheduling, the cost
lines that activity carries, and the workflow state around it.

Two rules give the page its integrity:

**One item per assignment.** The assignment is the item for its whole life. It
starts unscheduled and carries no cost; when the partner schedules, the same
item is *enriched* by the activity rather than joined by a second row. There is
no state that produces two rows for one handover.

**Cost exists only after scheduling.** Not zero, not "pending" — absent. An
unscheduled handover has no activity, so no cost lines, so nothing to show. The
Yet-to-Schedule list therefore has no cost column at all: printing "UGX 0"
against work whose price nobody has agreed invites someone to plan around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q
from django.urls import reverse

from apps.core.activity_types import VISIT_TYPES, TRAINING_TYPES, CLUSTER_MEETING_TYPES
from apps.planning.school_planning_badges import PLANNED_STATUSES

# Where an assignment is in its life. The partner's scheduling decision is the
# hinge: everything before it is a handover, everything after is delivery.
STAGE_AWAITING_SCHEDULE = "awaiting_schedule"
STAGE_SCHEDULED = "scheduled"
STAGE_RETURNED = "returned"

# Delivery states, read from the activity the partner created.
_IN_PROGRESS_STATUSES = ("in_progress", "completion_started")
# Partner evidence goes DIRECTLY to IA (§10, 2026-08-20) — there is no
# CCEO/PL review stage. Legacy rows may still sit in the two retired
# statuses; they read as "with the partner to submit".
_EVIDENCE_REVIEW_STATUSES = ("evidence_uploaded", "submitted_to_pl", "returned_by_pl")
_AWAITING_IA_STATUSES = ("awaiting_ia_verification", "salesforce_id_required")
_COMPLETE_STATUSES = ("ia_verified", "accountant_confirmed", "completed", "closed")
_NOT_STARTED_STATUSES = (
    "planned",
    "scheduled",
    "partner_scheduled",
    "assigned_to_partner",
)
_RETURNED_TO_PARTNER_STATUSES = ("returned", "returned_by_pl", "returned_by_ia")
_PAID_STATUSES = ("paid", "closed", "netsuite_accountability")
_PAYMENT_PROCESSING_STATUSES = (
    "pl_approval_required",
    "pl_approved",
    "accountant_cleared",
    "disbursed",
)

#: Every relation one handover's row reads, joined in the query that loads it,
#: so the Schools-assigned table's Training, Purpose and SSA Intervention cost
#: no query per row. The list query, the school section and the one-handover
#: rebuild all read the same set, so a row and its drawer cannot disagree.
ASSIGNMENT_RELATIONS: tuple[str, ...] = (
    "school",
    "school__district",
    "cluster",
    "partner",
    "project",
    "catalogue_item",
    "training_course",
    "source_activity__training_course",
    "scheduled_activity__training_course",
)

#: What the SSA Intervention column says for work that collects the SSA itself
#: and so moves no single intervention — the words the Assign to partner
#: drawer already shows for SSA Support.
DATA_GATHERING_LABEL = "Data Gathering"
_DATA_GATHERING_TYPES = frozenset(
    {"school_visit_ssa_collection", "baseline_ssa_visit", "partner_ssa_collection"}
)

#: The Partner Monitoring filter menu, in the owner's order.
MONITORING_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All Assigned Schools"),
    ("awaiting_schedule", "Awaiting Schedule"),
    ("scheduled", "Scheduled"),
    ("in_progress", "In Progress"),
    ("evidence_submitted", "Evidence Submitted"),
    ("returned_by_ia", "Returned by IA"),
    ("ia_verified", "IA Verified"),
    ("awaiting_payment", "Awaiting Payment"),
    ("paid", "Paid"),
    ("overdue", "Overdue"),
    ("returned", "Returned to Staff"),
)


@dataclass
class PartnerOversightItem:
    """One school handed to a partner, at whatever point it has reached."""

    stage: str
    partner_assignment_id: str
    partner_activity_id: str | None = None

    # Who and where
    school_id: str | None = None
    # The operational school code (School.school_id) — what tables display,
    # distinct from the CUID primary key `school_id` above carries.
    school_code: str = ""
    school_name: str = ""
    school_type: str = ""
    district: str = ""
    cluster_id: str | None = None
    cluster_name: str = ""
    project_id: str | None = None
    partner_id: str | None = None
    partner_name: str = ""
    responsible_cceo_id: str | None = None
    responsible_cceo_name: str = ""
    supervising_pl_id: str | None = None
    supervising_pl_name: str = ""

    # What was asked for
    activity_type: str = ""
    support_slot: str = ""
    target_intervention: str = ""
    source_ssa_id: str | None = None
    # The Schools-assigned table's columns (owner, 2026-09-24), in words: the
    # training the handover delivers or follows up, why the school was handed
    # over, and the SSA intervention the work targets. Read from the handover,
    # then from the activity the Partner's scheduling created.
    training_name: str = ""
    purpose_label: str = ""
    intervention_label: str = ""
    # The Special Project this handover belongs to, if any. Project work is
    # the project's coordinator's to withdraw or reassign (owner, 2026-09-24),
    # so the page names it and draws those controls for nobody else.
    project_name: str = ""
    project_locked: bool = False

    # When
    assignment_date: date | None = None
    schedule_by_date: date | None = None
    scheduled_date: date | None = None
    month: int | None = None
    quarter: str = ""
    financial_year: str = ""

    # State — assignment and activity kept apart rather than merged into one
    # label, because "Scheduled / Evidence Required" is two facts and a single
    # badge would have to lose one of them.
    assignment_status: str = ""
    activity_status: str = ""
    evidence_status: str = ""
    salesforce_status: str = ""
    # The Salesforce ID and Evidence columns (owner, 2026-09-26), set by
    # apps.activities.completion_columns.annotate where the tables show them.
    salesforce_id: str = ""
    evidence_label: str = ""
    salesforce_ok: bool = False
    evidence_ok: bool = False
    # Complete only with both columns green; a done status over a missing
    # half reads completion_gap instead, and never shows_complete.
    is_complete: bool = False
    completion_gap: str = ""
    shows_complete: bool = False
    ia_status: str = ""
    payment_status: str = ""
    # When the partner's completion entered the Impact Assessment queue. The
    # model keeps this apart from updated_at so the SLA is reproducible.
    submitted_to_ia_at: date | None = None
    return_reason_category: str = ""
    return_reason: str = ""

    # Money — present only once the partner has scheduled.
    planned_cost: int | None = None
    cost_catalogue_id: str | None = None
    cost_catalogue_version: int | None = None

    # Partner Monitoring (owner, 2026-09-23). The school's portfolio owner is
    # kept apart from the managing CCEO above: a Partner supporting a school
    # does not own it, and the owner stays visible on every row.
    staff_owner_id: str | None = None
    staff_owner_name: str = ""
    school_cluster_name: str = ""
    field_officer: str = ""
    reschedule_count: int = 0
    last_updated: object = None
    resolution: str = ""
    resolution_label: str = ""
    # The staff member named as the Partner activity's monitor — the one person
    # besides IA who may record its Salesforce entry (owner, 2026-09-12).
    monitor_id: str | None = None
    can_enter_salesforce: bool = False

    risks: list[dict] = field(default_factory=list)
    next_action_owner: str = ""
    next_action: str = ""
    # The label of the withdrawal action this record's state permits, or "" if
    # none does. Carried on the item so the row, the drawer and the service all
    # name the same decision — a row offering "Withdraw" over work that is
    # actually going to be suspended is a promise the service will break.
    withdrawal_kind: str = ""
    withdrawal_label: str = ""

    @property
    def is_scheduled(self) -> bool:
        return self.stage == STAGE_SCHEDULED

    @property
    def is_returned(self) -> bool:
        return self.stage == STAGE_RETURNED

    @property
    def has_cost(self) -> bool:
        """Cost is a property of scheduled work, and absent otherwise."""
        return self.planned_cost is not None

    @property
    def at_risk(self) -> bool:
        return bool(self.risks)

    # ── Monitoring columns, each one fact ──────────────────────────────────
    @property
    def schedule_status(self) -> str:
        if self.stage == STAGE_RETURNED:
            return "Returned to Staff"
        if self.stage == STAGE_AWAITING_SCHEDULE:
            return "Awaiting Schedule"
        return "Rescheduled" if self.reschedule_count else "Scheduled"

    @property
    def execution_status(self) -> str:
        if not self.is_scheduled:
            return "—"
        if self.activity_status in _NOT_STARTED_STATUSES:
            return "Not Started"
        if self.activity_status in (
            *_IN_PROGRESS_STATUSES,
            *_RETURNED_TO_PARTNER_STATUSES,
            # Uploaded but not yet submitted: still the Partner's to finish.
            "evidence_uploaded",
            "evidence_accepted",
        ):
            return "In Progress"
        return "Evidence Submitted"

    @property
    def ia_status_label(self) -> str:
        if self.activity_status in _RETURNED_TO_PARTNER_STATUSES or (
            self.ia_status == "returned"
        ):
            return "Returned"
        if self.ia_status == "confirmed" or self.activity_status in (
            "ia_verified",
            "accountant_confirmed",
        ):
            return "Verified"
        if self.execution_status == "Evidence Submitted":
            return "Pending"
        return "—"

    @property
    def salesforce_label(self) -> str:
        if not self.is_scheduled or self.execution_status != "Evidence Submitted":
            return "—"
        return "Confirmed" if self.salesforce_status == "recorded" else "Pending"

    @property
    def payment_label(self) -> str:
        if self.ia_status_label != "Verified":
            return "Not Eligible"
        if self.payment_status in _PAID_STATUSES:
            return "Paid"
        if self.payment_status in _PAYMENT_PROCESSING_STATUSES:
            return "Processing"
        return "Awaiting Payment"

    @property
    def is_overdue(self) -> bool:
        today = date.today()
        if self.stage == STAGE_AWAITING_SCHEDULE:
            return bool(self.schedule_by_date and self.schedule_by_date < today)
        return bool(
            self.is_scheduled
            and self.scheduled_date
            and self.scheduled_date < today
            and self.execution_status == "Not Started"
        )

    @property
    def awaits_staff_decision(self) -> bool:
        return self.stage == STAGE_RETURNED and not self.resolution

    def matches(self, status: str) -> bool:
        """Whether this row belongs under one Partner Monitoring filter."""
        if status in ("", "all"):
            return True
        return {
            "awaiting_schedule": self.stage == STAGE_AWAITING_SCHEDULE,
            "scheduled": self.is_scheduled and self.execution_status == "Not Started",
            "in_progress": self.execution_status == "In Progress"
            and self.ia_status_label != "Returned",
            "evidence_submitted": self.execution_status == "Evidence Submitted"
            and self.ia_status_label == "Pending",
            "returned_by_ia": self.ia_status_label == "Returned",
            "ia_verified": self.ia_status_label == "Verified",
            "awaiting_payment": self.payment_label == "Awaiting Payment",
            "paid": self.payment_label == "Paid",
            "overdue": self.is_overdue,
            "returned": self.stage == STAGE_RETURNED,
        }.get(status, False)

    @property
    def delivery_phase(self) -> str:
        """Which of the page's columns this belongs under."""
        if self.stage == STAGE_RETURNED:
            return "returned"
        if self.stage == STAGE_AWAITING_SCHEDULE:
            return "awaiting_schedule"
        if self.activity_status in _COMPLETE_STATUSES:
            return "completed"
        if self.activity_status in _AWAITING_IA_STATUSES:
            return "verification"
        if self.activity_status in _EVIDENCE_REVIEW_STATUSES:
            return "verification"
        if self.activity_status in _IN_PROGRESS_STATUSES:
            return "in_progress"
        return "scheduled"

    @property
    def status_label(self) -> str:
        """The Status column, in words: Awaiting Schedule until the Partner
        dates the work, Scheduled once they have (owner, 2026-09-24), then
        where delivery stands. A hand-back nobody has decided on says so."""
        if self.awaits_staff_decision:
            return self.schedule_status
        return self.delivery_phase.replace("_", " ").title()

    @property
    def status_tone(self) -> str:
        """Red when staff must act, blue while the work waits on the Partner's
        date or on IA, amber while it is scheduled or under way, green only
        once IA has verified it — the Planning badges' rule."""
        if self.awaits_staff_decision:
            return "danger"
        phase = self.delivery_phase
        if phase in ("awaiting_schedule", "verification"):
            return "info"
        if phase == "completed":
            return "success" if self.ia_status_label == "Verified" else "info"
        return "warning"

    @property
    def activity_date(self) -> date | None:
        """The Activity date column: the day the Partner scheduled, and none
        before they have — a schedule-by date is a deadline, not a visit."""
        if self.stage != STAGE_SCHEDULED:
            return None
        return self.scheduled_date


def choice_label(value: str, choices) -> str:
    """A stored code as its choice label, or plainly spaced when unknown."""
    if not value:
        return ""
    try:
        return choices(value).label
    except ValueError:
        return str(value).replace("_", " ").title()


def _course_name(course) -> str:
    if course is None:
        return ""
    return (
        getattr(course, "display_name", "") or getattr(course, "source_name", "") or ""
    )


def activity_day(activity) -> date | None:
    """The day an activity is dated, read the way My Plan reads it: the
    planned date, falling back to the scheduled timestamp an older row carries
    on its own."""
    if activity is None:
        return None
    if activity.planned_date:
        return activity.planned_date
    moment = activity.scheduled_date
    if not moment:
        return None
    from django.utils import timezone

    if timezone.is_naive(moment):
        return moment.date()
    return timezone.localtime(moment).date()


def describe_work(
    *,
    purpose_code: str = "",
    activity_type: str = "",
    course=None,
    catalogue_item=None,
    source_activity=None,
    activity=None,
    focus: str = "",
) -> tuple[str, str, str]:
    """(Training, Purpose of Assignment, SSA Intervention) for one piece of
    Partner or project work, every word read from the records behind it.

    Training is the course a training delivers — the handover's own course,
    else the scheduled activity's, else the approved catalogue item a training
    handover names — or, for a Training Follow Up, the training it follows up.
    Other work names no training. Purpose is the handover's stated reason,
    else the activity's, else its activity type. The intervention is the
    work's focus; work that collects the SSA itself reads Data Gathering.
    """
    from apps.core.enums import ActivityType, SsaIntervention
    from apps.partners.purposes import visit_purpose_label

    purpose_code = purpose_code or (
        getattr(activity, "purpose_type", "") if activity is not None else ""
    )
    activity_type = activity_type or (
        getattr(activity, "activity_type", "") if activity is not None else ""
    )
    is_training = (
        purpose_code == "in_school_training" or activity_type in TRAINING_TYPES
    )

    training = _course_name(course)
    if not training and activity is not None:
        training = _course_name(getattr(activity, "training_course", None))
    if not training and is_training:
        training = _course_name(catalogue_item)
        if not training and activity is not None:
            training = getattr(activity, "activity_name_snapshot", "") or ""
    if not training and purpose_code == "training_follow_up" and source_activity:
        training = (
            _course_name(getattr(source_activity, "training_course", None))
            or getattr(source_activity, "activity_name_snapshot", "")
            or choice_label(source_activity.activity_type, ActivityType)
        )

    purpose = visit_purpose_label(purpose_code, "") if purpose_code else ""
    if not purpose:
        purpose = choice_label(activity_type, ActivityType)

    code = focus or (
        (activity.focus_intervention or activity.purpose_intervention or "")
        if activity is not None
        else ""
    )
    intervention = choice_label(code, SsaIntervention)
    if not intervention and (
        purpose_code == "ssa_support" or activity_type in _DATA_GATHERING_TYPES
    ):
        intervention = DATA_GATHERING_LABEL
    return training, purpose, intervention


def _assignment_team_q(scope):
    """Which handovers a team lens reads, as one filter (None for the country).

    The page's list and the handover drawer both ask this, so every row the
    page shows opens (Program Lead walk, 2026-09-14: the drawer checked the
    responsible officer and the supervising lead only, and returned 404 for
    handovers at team schools monitored by someone else).
    """
    if scope.get("region_ids") is not None:
        return Q(school__region_id__in=scope["region_ids"]) | Q(
            cluster__region_id__in=scope["region_ids"]
        )
    if scope["is_country"]:
        return None
    ids = scope["staff_ids"]
    # School ownership is the third arm, and it is not redundant.
    # `monitoring_staff_id` is nullable — every assignment written before
    # that column existed has none, and falls back to the *assigner*. So a
    # partner handed off by a PL to a CCEO's school resolves to the PL on
    # those older rows, and the CCEO who owns the school would open this
    # page to a blank list. Owning the school is the durable claim: it does
    # not depend on who clicked Handoff or on when the row was written.
    return (
        Q(monitoring_staff_id__in=ids)
        | Q(assigning_staff_id__in=ids)
        | Q(school__account_owner_id__in=ids)
        | Q(cluster__responsible_staff_id__in=ids)
    )


def assignment_in_scope(principal, assignment_id: str) -> bool:
    """Whether this principal's lens reads the handover, by the list's rule."""
    from apps.partners.models import PartnerAssignment

    scope = _resolve_scope(principal)
    if scope["kind"] == "team" and not scope["staff_ids"]:
        return False
    qs = PartnerAssignment.objects.filter(id=assignment_id)
    team_q = _assignment_team_q(scope)
    if team_q is not None:
        qs = qs.filter(team_q)
    return qs.exists()


def build_items(
    principal,
    *,
    fy: str,
    month: int | None = None,
    quarter: str | None = None,
    date_start: date | None = None,
    date_end: date | None = None,
    partner_id=None,
    program_lead_id=None,
    fys: tuple[str, ...] | None = None,
):
    """Every partner handover this principal may oversee, for the period.

    One bulk query per source. The partner group expansion on the page reuses
    this list rather than re-querying, so a group's numbers and its rows are
    the same rows.

    ``fys``, when given, reads those fiscal years instead of ``fy`` alone — a
    planning horizon (``fy_policy.planning_horizon``). A handover made in
    September that the Partner dates into October belongs to the next fiscal
    year; read for the page year alone it left the list the moment it was
    scheduled, instead of reading Scheduled on its date (owner, 2026-09-24).
    """
    from apps.partners.models import PartnerAssignment

    scope = _resolve_scope(principal)
    if scope["kind"] == "team" and not scope["staff_ids"]:
        return []

    qs = PartnerAssignment.objects.select_related(*ASSIGNMENT_RELATIONS)
    if _has_soft_delete():
        qs = qs.filter(deleted_at__isnull=True)
    team_q = _assignment_team_q(scope)
    if team_q is not None:
        qs = qs.filter(team_q)
    if partner_id:
        qs = qs.filter(partner_id=partner_id)

    years = {str(year) for year in fys} if fys else ({str(fy)} if fy else set())
    assignments = list(qs)
    if years:
        from apps.core.fy import get_operational_fy

        assignments = [
            a for a in assignments if _assignment_fy(a, get_operational_fy) in years
        ]

    activity_ids = [
        a.scheduled_activity_id for a in assignments if a.scheduled_activity_id
    ]
    costs = _cost_by_activity(activity_ids)
    directory = _staff_directory(assignments)

    items = [_item_for(a, costs, directory) for a in assignments]
    items += _unassigned_partner_activities(
        scope, fys=years, partner_id=partner_id, already=set(activity_ids)
    )
    if month:
        items = [
            i
            for i in items
            if (i.scheduled_date.month if i.scheduled_date else None) == month
            or (
                not i.scheduled_date
                and i.assignment_date
                and i.assignment_date.month == month
            )
        ]
    if quarter:
        from apps.core.fy import get_quarter_for_date

        items = [
            i
            for i in items
            if i.quarter == quarter
            or (
                not i.quarter
                and (i.scheduled_date or i.assignment_date)
                and get_quarter_for_date(i.scheduled_date or i.assignment_date)
                == quarter
            )
        ]
    if date_start:
        items = [
            i
            for i in items
            if (i.scheduled_date or i.assignment_date)
            and (i.scheduled_date or i.assignment_date) >= date_start
        ]
    if date_end:
        items = [
            i
            for i in items
            if (i.scheduled_date or i.assignment_date)
            and (i.scheduled_date or i.assignment_date) < date_end
        ]
    if program_lead_id:
        from apps.planning.oversight_service import _both_id_spaces

        wanted = _both_id_spaces({program_lead_id})
        items = [
            i
            for i in items
            if (
                not i.supervising_pl_id
                if program_lead_id == "unassigned"
                else i.supervising_pl_id in wanted
            )
        ]

    _attach_school_clusters(items)

    from apps.planning import partner_risk_service

    partner_risk_service.annotate(items)
    items.sort(key=lambda i: (i.partner_name, i.school_name))
    return items


def _attach_school_clusters(items) -> None:
    """Each row's own school cluster, in two queries for the whole list.

    ``cluster_name`` is the cluster an assignment was made against, which a
    school-level handover does not have; the monitoring table's District /
    Cluster column is the school's own membership.
    """
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    school_ids = {i.school_id for i in items if i.school_id}
    if not school_ids:
        return
    cluster_of = dict(
        School.objects.filter(id__in=school_ids)
        .exclude(cluster_id__isnull=True)
        .values_list("id", "cluster_id")
    )
    names = dict(
        Cluster.objects.filter(id__in=set(cluster_of.values())).values_list(
            "id", "name"
        )
    )
    for item in items:
        item.school_cluster_name = (
            names.get(cluster_of.get(item.school_id), "") or item.cluster_name
        )


def monitoring_summary(items) -> dict:
    """The one-line summary above a Partner's table, from the same rows.

    Every figure is a count of rows the table's own filters return, so the
    summary and the table reconcile by construction.
    """
    items = list(items)
    return {
        "assigned": len(items),
        "scheduled": sum(1 for i in items if i.is_scheduled),
        "awaiting_schedule": sum(1 for i in items if i.matches("awaiting_schedule")),
        "under_ia_review": sum(1 for i in items if i.matches("evidence_submitted")),
        "returned": sum(1 for i in items if i.awaits_staff_decision),
        "overdue": sum(1 for i in items if i.is_overdue),
    }


def filter_counts(items) -> dict:
    items = list(items)
    return {
        key: sum(1 for i in items if i.matches(key)) for key, _ in MONITORING_FILTERS
    }


def _unassigned_partner_activities(
    scope, *, fys, partner_id, already: set
) -> list[PartnerOversightItem]:
    """Partner-delivered activities that no PartnerAssignment points at.

    This page was built from PartnerAssignment alone, which was right while it
    sat beside the Partners directory: the directory read Activity as well, so
    between them every piece of partner work was visible somewhere. Merging the
    two made that split a hole — `activity_services.create` stamps
    `assigned_partner_id` straight onto an Activity without writing an
    assignment row, so that work would have disappeared from the only remaining
    partner page.

    They arrive as scheduled-stage items with no assignment id. That is honest
    rather than tidy: there is no handover record to open, and inventing one
    would put a withdrawal control on a row the withdrawal service cannot act
    on.
    """
    from apps.activities.models import Activity

    qs = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
        )
        .exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .exclude(status__in=("cancelled", "rejected", "deferred"))
        .select_related("school", "school__district", "cluster", "training_course")
    )
    if fys:
        qs = qs.filter(fy__in=tuple(fys))
    if partner_id:
        qs = qs.filter(assigned_partner_id=partner_id)
    if already:
        qs = qs.exclude(id__in=already)
    if scope.get("region_ids") is not None:
        qs = qs.filter(
            Q(school__region_id__in=scope["region_ids"])
            | Q(cluster__region_id__in=scope["region_ids"])
        )
    elif not scope["is_country"]:
        ids = scope["staff_ids"]
        qs = qs.filter(
            Q(monitored_by_staff_id__in=ids)
            | Q(responsible_staff_id__in=ids)
            | Q(school__account_owner_id__in=ids)
            | Q(cluster__responsible_staff_id__in=ids)
        )

    activities = list(qs)
    if not activities:
        return []

    from apps.partners.models import Partner

    names = dict(
        Partner.all_objects.filter(
            id__in={a.assigned_partner_id for a in activities}
        ).values_list("id", "name")
    )
    costs = _cost_by_activity([a.id for a in activities])
    # Activity.project_id is a plain column, so the names come in one query.
    from apps.projects.models import Project

    project_names = dict(
        Project.objects.filter(
            id__in={a.project_id for a in activities if a.project_id}
        ).values_list("id", "name")
    )
    owner_names = _owner_names(
        {getattr(a.school, "account_owner_id", None) for a in activities}
    )

    from types import SimpleNamespace

    directory = _staff_directory(
        [
            SimpleNamespace(
                monitoring_staff_id=a.monitored_by_staff_id,
                assigning_staff_id=a.responsible_staff_id,
                school=a.school,
                cluster=a.cluster,
            )
            for a in activities
        ]
    )
    items = []
    for activity in activities:
        owner = (
            activity.monitored_by_staff_id
            or activity.responsible_staff_id
            or getattr(activity.school, "account_owner_id", None)
            or getattr(activity.cluster, "responsible_staff_id", None)
        )
        canonical = directory["canonical"].get(owner, owner)
        pl_id, pl_name = directory["supervisor"].get(canonical, (None, ""))
        entry = costs.get(activity.id)
        cost, catalogue_id, catalogue_version = entry if entry else (0, None, None)
        training, purpose, intervention = describe_work(activity=activity)
        item = PartnerOversightItem(
            stage=STAGE_SCHEDULED
            if (activity.planned_date or activity.scheduled_date)
            else STAGE_AWAITING_SCHEDULE,
            partner_assignment_id="",
            partner_activity_id=activity.id,
            school_id=activity.school_id,
            school_code=getattr(activity.school, "school_id", "") or "",
            school_name=getattr(activity.school, "name", "") or "",
            school_type=getattr(activity.school, "school_type", "") or "",
            district=getattr(getattr(activity.school, "district", None), "name", "")
            or "",
            cluster_id=activity.cluster_id,
            cluster_name=getattr(activity.cluster, "name", "") or "",
            partner_id=activity.assigned_partner_id,
            partner_name=names.get(activity.assigned_partner_id, ""),
            responsible_cceo_id=canonical,
            responsible_cceo_name=directory["names"].get(owner, ""),
            supervising_pl_id=pl_id,
            supervising_pl_name=pl_name,
            activity_type=activity.activity_type or "",
            target_intervention=activity.focus_intervention or "",
            training_name=training,
            purpose_label=purpose,
            intervention_label=intervention,
            project_id=activity.project_id,
            project_name=project_names.get(activity.project_id, ""),
            scheduled_date=activity_day(activity),
            month=activity.planned_month,
            quarter=activity.quarter or "",
            financial_year=activity.fy or "",
            activity_status=activity.status,
            evidence_status=activity.evidence_status or "",
            ia_status=activity.ia_verification_status or "",
            payment_status=activity.payment_status or "",
            salesforce_status=(
                "recorded" if activity.salesforce_activity_id else "missing"
            ),
            planned_cost=cost,
            cost_catalogue_id=catalogue_id,
            cost_catalogue_version=catalogue_version,
            staff_owner_id=getattr(activity.school, "account_owner_id", None),
            staff_owner_name=owner_names.get(
                getattr(activity.school, "account_owner_id", None) or "", ""
            )
            or getattr(activity.school, "account_owner_name_raw", "")
            or "",
            field_officer=activity.delivery_contact_name or "",
            monitor_id=activity.monitored_by_staff_id,
            reschedule_count=activity.reschedule_count or 0,
            last_updated=activity.updated_at,
        )
        _set_next_action(item)
        items.append(item)
    return items


def _owner_names(ids) -> dict:
    """Display names for school owners, in both id spaces, one query."""
    from apps.accounts.models import StaffProfile

    ids = {i for i in ids if i}
    if not ids:
        return {}
    names = {}
    for sp in StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).select_related("user"):
        label = getattr(sp.user, "name", "") or getattr(sp.user, "email", "")
        for key in (sp.id, sp.user_id):
            if key:
                names[key] = label
    return names


def _has_soft_delete() -> bool:
    from apps.partners.models import PartnerAssignment

    return any(f.name == "deleted_at" for f in PartnerAssignment._meta.get_fields())


def _assignment_fy(assignment, get_operational_fy) -> str:
    """The period an assignment belongs to.

    Once scheduled that is the delivery date's FY, because the work — and its
    cost — lands there. Before scheduling it is the handover date's, because
    that is the only date the record has.
    """
    if assignment.scheduled_activity_id and assignment.scheduled_activity:
        return assignment.scheduled_activity.fy or ""
    reference = assignment.scheduled_date or (
        assignment.created_at.date() if assignment.created_at else None
    )
    return get_operational_fy(reference) if reference else ""


def _resolve_scope(principal) -> dict:
    from apps.core.permissions import has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.core.scoping import owner_ids, resolve_user_scope

    role = getattr(principal, "active_role", "") or ""
    # A Regional Programme Lead reads the partner work of their regions,
    # whoever monitors it.
    if role == EdifyRole.REGIONAL_PROGRAM_LEAD.value:
        scope = resolve_user_scope(principal)
        return {
            "kind": "region",
            "is_country": True,
            "staff_ids": set(),
            "region_ids": scope.region_ids,
        }
    # Country lens for the roles whose remit genuinely is the whole country —
    # the Country Director, the RVP, Admin, and Impact Assessment and the
    # Accountant, whose queues already are country-wide (IA verifies every
    # submission, the Accountant pays every partner), so a team-shaped scope
    # would resolve to the empty set and hand them a blank page, which reads as
    # "no partner work is stuck" rather than "you were shown nothing". Named by
    # the permission that grants exactly that set, not by a role list.
    if has_permission(
        principal, Permission.PARTNER_MONITORING_COUNTRY.value
    ) or getattr(principal, "is_superuser", False):
        return {"kind": "country", "is_country": True, "staff_ids": set()}

    from apps.planning.oversight_service import _both_id_spaces

    scope = resolve_user_scope(principal)
    own = _both_id_spaces(set(owner_ids(principal)))
    supervised = (
        _both_id_spaces(set(scope.supervised_staff_ids or []))
        if role != EdifyRole.CCEO.value
        else set()
    )
    return {
        "kind": "team",
        "is_country": False,
        "staff_ids": own | supervised,
        "own_ids": own,
    }


def _cost_by_activity(activity_ids) -> dict:
    """Total and catalogue provenance per activity, in one pass.

    One query rather than an aggregate plus a lookup: the totals and the rate
    card they were priced against come off the same rows, so reading them twice
    was a second round trip for data already in hand.
    """
    from apps.activities.models import ActivityScheduleCostLine

    if not activity_ids:
        return {}

    totals: dict[str, int] = {}
    provenance: dict[str, tuple] = {}
    for row in ActivityScheduleCostLine.objects.filter(
        activity_id__in=activity_ids
    ).values("activity_id", "amount", "catalogue_id", "catalogue_version"):
        aid = row["activity_id"]
        totals[aid] = totals.get(aid, 0) + int(row["amount"] or 0)
        provenance.setdefault(aid, (row["catalogue_id"], row["catalogue_version"]))

    return {
        aid: (total, *provenance.get(aid, (None, None)))
        for aid, total in totals.items()
    }


def _staff_directory(assignments) -> dict:
    """Names and supervisors for the CCEOs on these assignments, in two queries."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    ids = {a.monitoring_staff_id for a in assignments} | {
        a.assigning_staff_id for a in assignments
    }
    ids.update(getattr(a.school, "account_owner_id", None) for a in assignments)
    ids.update(getattr(a.cluster, "responsible_staff_id", None) for a in assignments)
    ids.discard(None)
    ids.discard("")
    if not ids:
        return {"names": {}, "supervisor": {}, "canonical": {}}

    from apps.core.rbac import EdifyRole

    names, canonical = {}, {}
    profiles = StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).select_related("user")
    supervisor = {}
    for p in profiles:
        label = getattr(p.user, "name", "") or getattr(p.user, "email", "")
        role = getattr(p.user, "active_role", "") or ""
        for key in (p.id, p.user_id):
            if key:
                names[key] = label
                canonical[key] = p.id
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            supervisor[p.id] = (p.id, label)
            if p.user_id:
                supervisor[p.user_id] = (p.id, label)

    links = StaffSupervisorAssignment.objects.filter(
        supervisee_id__in={p.id for p in profiles},
        supervisor__user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    ).select_related("supervisor__user")
    for link in links:
        user = getattr(link.supervisor, "user", None)
        if link.supervisee_id not in supervisor:
            supervisor[link.supervisee_id] = (
                link.supervisor_id,
                getattr(user, "name", "") or getattr(user, "email", "") or "",
            )
    return {"names": names, "supervisor": supervisor, "canonical": canonical}


def _item_for(assignment, costs, directory) -> PartnerOversightItem:
    from apps.partners.models import PartnerAssignment

    activity = assignment.scheduled_activity
    cceo_id = (
        assignment.monitoring_staff_id
        or assignment.assigning_staff_id
        or getattr(assignment.school, "account_owner_id", None)
        or getattr(assignment.cluster, "responsible_staff_id", None)
    )
    canonical_cceo = directory["canonical"].get(cceo_id, cceo_id)
    pl_id, pl_name = directory["supervisor"].get(canonical_cceo, (None, ""))

    if assignment.status == "returned_to_staff":
        stage = STAGE_RETURNED
    elif activity is not None:
        stage = STAGE_SCHEDULED
    elif assignment.status in PartnerAssignment.UNSCHEDULED_STATUSES:
        stage = STAGE_AWAITING_SCHEDULE
    else:
        # Marked scheduled but with no activity recorded — a legacy row. It is
        # not delivery anybody can show, so it stays in the handover list where
        # somebody will notice it, rather than appearing as scheduled with no
        # date and no cost.
        stage = STAGE_AWAITING_SCHEDULE

    cost, catalogue_id, catalogue_version = (None, None, None)
    if activity is not None:
        entry = costs.get(activity.id)
        cost, catalogue_id, catalogue_version = entry if entry else (0, None, None)

    training, purpose, intervention = describe_work(
        purpose_code=assignment.purpose_of_visit or "",
        activity_type=(
            getattr(activity, "activity_type", "")
            or assignment.expected_activity_type
            or ""
        ),
        course=assignment.training_course,
        catalogue_item=assignment.catalogue_item,
        source_activity=assignment.source_activity,
        activity=activity,
        focus=assignment.focus_intervention or "",
    )

    item = PartnerOversightItem(
        stage=stage,
        partner_assignment_id=assignment.id,
        partner_activity_id=getattr(activity, "id", None),
        school_id=assignment.school_id,
        school_code=getattr(assignment.school, "school_id", "") or "",
        school_name=getattr(assignment.school, "name", "") or "",
        school_type=getattr(assignment.school, "school_type", "") or "",
        district=getattr(getattr(assignment.school, "district", None), "name", "")
        or "",
        cluster_id=assignment.cluster_id,
        cluster_name=getattr(assignment.cluster, "name", "") or "",
        project_id=assignment.project_id,
        partner_id=assignment.partner_id,
        partner_name=getattr(assignment.partner, "name", "") or "",
        responsible_cceo_id=canonical_cceo,
        responsible_cceo_name=directory["names"].get(cceo_id, ""),
        supervising_pl_id=pl_id,
        supervising_pl_name=pl_name,
        activity_type=(
            getattr(activity, "activity_type", "")
            or assignment.expected_activity_type
            or ""
        ),
        support_slot=assignment.support_type or "",
        target_intervention=assignment.focus_intervention or "",
        source_ssa_id=assignment.source_ssa_id,
        training_name=training,
        purpose_label=purpose,
        intervention_label=intervention,
        project_name=getattr(assignment.project, "name", "") or "",
        assignment_date=assignment.created_at.date() if assignment.created_at else None,
        schedule_by_date=assignment.scheduled_date,
        assignment_status=assignment.status,
        return_reason_category=assignment.return_reason_category or "",
        return_reason=assignment.return_reason or "",
        resolution=getattr(assignment, "resolution", "") or "",
        resolution_label=(
            assignment.get_resolution_display()
            if getattr(assignment, "resolution", "")
            else ""
        ),
        staff_owner_id=getattr(assignment.school, "account_owner_id", None),
        staff_owner_name=directory["names"].get(
            getattr(assignment.school, "account_owner_id", None) or "", ""
        )
        or getattr(assignment.school, "account_owner_name_raw", "")
        or "",
        last_updated=assignment.updated_at,
        planned_cost=cost,
        cost_catalogue_id=catalogue_id,
        cost_catalogue_version=catalogue_version,
    )

    if activity is not None:
        # The day the Partner scheduled — the Activity date column once they
        # have (owner, 2026-09-24). An older row dated only by its timestamp
        # reads that day, as it does on My Plan.
        item.scheduled_date = activity_day(activity)
        item.month = activity.planned_month
        item.quarter = activity.quarter or ""
        item.financial_year = activity.fy or ""
        item.activity_status = activity.status
        item.evidence_status = activity.evidence_status or ""
        item.salesforce_status = (
            "recorded" if activity.salesforce_activity_id else "missing"
        )
        item.ia_status = activity.ia_verification_status or ""
        item.payment_status = activity.payment_status or ""
        item.submitted_to_ia_at = (
            activity.submitted_to_ia_at.date() if activity.submitted_to_ia_at else None
        )
        item.field_officer = activity.delivery_contact_name or ""
        item.monitor_id = activity.monitored_by_staff_id
        item.reschedule_count = activity.reschedule_count or 0
        if activity.updated_at and (
            item.last_updated is None or activity.updated_at > item.last_updated
        ):
            item.last_updated = activity.updated_at

    _set_next_action(item)
    _set_withdrawal_action(item)
    return item


def _set_withdrawal_action(item) -> None:
    """Which controlled workflow this record's state permits, in words.

    Asks the same resolver the service uses rather than re-deriving it here.
    Two implementations of "what can be done to this" is how a page comes to
    offer a control the service refuses.
    """
    from apps.partners.withdrawal_models import WithdrawalKind
    from apps.partners.withdrawal_service import resolve_kind

    # A lightweight stand-in: the resolver reads only status fields, and
    # building it from the item avoids re-fetching the assignment row the
    # oversight query already loaded.
    # None when the partner has not scheduled — `resolve_kind` reads "no
    # activity" as "still a plain handover", and handing it an empty stand-in
    # instead made every unscheduled assignment look unwithdrawable.
    activity = _ActivityView(item) if item.partner_activity_id else None
    kind = resolve_kind(_AssignmentView(item), activity)
    item.withdrawal_kind = kind
    item.withdrawal_label = (
        "" if kind == WithdrawalKind.BLOCKED else WithdrawalKind(kind).label
    )


class _AssignmentView:
    """Just enough of an assignment for `resolve_kind` to read."""

    def __init__(self, item):
        self.status = item.assignment_status
        self.scheduled_activity = (
            _ActivityView(item) if item.partner_activity_id else None
        )


class _ActivityView:
    """Just enough of an activity for `resolve_kind` to read."""

    def __init__(self, item):
        self.status = item.activity_status
        self.evidence_status = item.evidence_status
        self.payment_status = item.payment_status


def _set_next_action(item) -> None:
    """One authoritative next action, never several competing ones.

    Read straight down the canonical workflow: whoever the record is waiting on
    is the owner, and there is exactly one of them at any moment.
    """
    if item.stage == STAGE_RETURNED:
        item.next_action_owner, item.next_action = (
            item.responsible_cceo_name or "CCEO",
            "Review the return and decide what happens next",
        )
    elif item.stage == STAGE_AWAITING_SCHEDULE:
        item.next_action_owner, item.next_action = (
            item.partner_name or "Partner",
            "Schedule the assignment",
        )
    elif item.activity_status in _COMPLETE_STATUSES:
        if item.payment_status in ("", "none", "pending"):
            item.next_action_owner, item.next_action = ("Accountant", "Pay the partner")
        else:
            item.next_action_owner, item.next_action = ("System", "Close the activity")
    elif item.activity_status in _AWAITING_IA_STATUSES:
        if item.salesforce_status == "missing":
            item.next_action_owner, item.next_action = (
                item.responsible_cceo_name or "CCEO",
                "Enter the Salesforce Activity ID",
            )
        else:
            item.next_action_owner, item.next_action = (
                "Impact Assessment",
                "Verify the submission",
            )
    elif item.activity_status in _EVIDENCE_REVIEW_STATUSES:
        # Evidence exists but the partner has not pressed Submit — direct
        # IA handoff means nobody reviews it before IA (§10).
        item.next_action_owner, item.next_action = (
            item.partner_name or "Partner",
            "Submit the evidence to IA",
        )
    elif item.evidence_status in ("", "none"):
        item.next_action_owner, item.next_action = (
            item.partner_name or "Partner",
            "Execute and upload evidence",
        )
    else:
        item.next_action_owner, item.next_action = (
            item.partner_name or "Partner",
            "Continue delivery",
        )


def build_items_for_school(school_id: str):
    """Every partner handover at one school, newest first.

    The School Profile's Partner Support section. Scoped by the school rather
    than by the reader on purpose: whoever may open the school profile may see
    what is happening at that school, and a CCEO's own handovers disappearing
    from their school's page would be the exact loss of context this section
    exists to prevent.
    """
    from apps.partners.models import PartnerAssignment

    assignments = list(
        PartnerAssignment.objects.select_related(*ASSIGNMENT_RELATIONS).filter(
            school_id=school_id
        )
    )
    if not assignments:
        return []

    costs = _cost_by_activity(
        [a.scheduled_activity_id for a in assignments if a.scheduled_activity_id]
    )
    directory = _staff_directory(assignments)
    items = [_item_for(a, costs, directory) for a in assignments]

    from apps.planning import partner_risk_service

    partner_risk_service.annotate(items)
    items.sort(
        key=lambda i: i.scheduled_date or i.assignment_date or date.min, reverse=True
    )
    return items


def build_item_by_assignment(assignment_id: str):
    """One handover, rebuilt exactly as the page builds it — or None.

    Unscoped on purpose: the callers that need scope (the send path, the
    drawer) apply their own lens to the result, and the action sweep needs to
    re-ask the detector about a record whose supervisor may since have changed.
    Building it the same way is the point — a drawer and a row cannot disagree
    about what a record says if there is one function that reads it.
    """
    from apps.partners.models import PartnerAssignment

    assignment = (
        PartnerAssignment.objects.select_related(*ASSIGNMENT_RELATIONS)
        .filter(id=assignment_id)
        .first()
    )
    if assignment is None:
        return None

    activity_ids = (
        [assignment.scheduled_activity_id] if assignment.scheduled_activity_id else []
    )
    item = _item_for(
        assignment, _cost_by_activity(activity_ids), _staff_directory([assignment])
    )

    from apps.planning import partner_risk_service

    partner_risk_service.annotate([item])
    return item


# ── Folds ────────────────────────────────────────────────────────────────────
def summarize(items) -> dict:
    """Headline numbers, folded from the same items the page lists."""
    items = list(items)
    awaiting = [i for i in items if i.stage == STAGE_AWAITING_SCHEDULE]
    scheduled = [i for i in items if i.is_scheduled]
    returned = [i for i in items if i.is_returned]

    by_phase = {}
    for item in items:
        by_phase.setdefault(item.delivery_phase, []).append(item)

    return {
        "scheduled_visits": len(
            {
                i.partner_activity_id
                for i in scheduled
                if i.activity_type in VISIT_TYPES
                and i.activity_status in PLANNED_STATUSES
            }
        ),
        "scheduled_trainings": len(
            {
                i.partner_activity_id
                for i in scheduled
                if i.activity_type in TRAINING_TYPES
                and i.activity_status in PLANNED_STATUSES
            }
        ),
        "scheduled_meetings": len(
            {
                i.partner_activity_id
                for i in scheduled
                if i.activity_type in CLUSTER_MEETING_TYPES
                and i.activity_status in PLANNED_STATUSES
            }
        ),
        "overdue": sum(
            any(
                risk["key"] in {"partner_schedule_overdue", "partner_delivery_overdue"}
                for risk in i.risks
            )
            for i in items
        ),
        "active_partners": len({i.partner_id for i in items if i.partner_id}),
        "schools_assigned": len({i.school_id for i in items if i.school_id}),
        "awaiting_schedule": len(awaiting),
        "scheduled": len(scheduled),
        "returned": len(returned),
        "in_progress": len(by_phase.get("in_progress", [])),
        "verification": len(by_phase.get("verification", [])),
        "completed": len(by_phase.get("completed", [])),
        # Only scheduled work carries money, so this sums exactly those items.
        "scheduled_budget": sum(i.planned_cost or 0 for i in scheduled),
        # Verified-and-unpaid, and the verification is asked for directly.
        # `_COMPLETE_STATUSES` answers "is delivery over", not "did IA sign
        # it off": `completed` has no IA gate at all and `closed` can be
        # written past ClosureEligibilityService's checklist, so both reach
        # this fold with ia_verification_status still `pending`. Folding on
        # the phase tuple alone therefore offered the Accountant unverified
        # work under a heading that promises IA verified it (INTG-05).
        "payment_pending": len(
            [
                i
                for i in scheduled
                if i.payment_status in ("", "none", "pending")
                and i.activity_status in _COMPLETE_STATUSES
                and i.ia_status == "confirmed"
            ]
        ),
        "at_risk": len([i for i in items if i.at_risk]),
    }


EXPORT_HEADER = (
    "Partner",
    "School",
    "District",
    "Cluster",
    "Managing CCEO",
    "Program Lead",
    "Support Type",
    "Focus Intervention",
    "Stage",
    "Assigned On",
    "Scheduled For",
    "Activity Status",
    "Evidence",
    "Salesforce",
    "Payment",
    "Planned Cost (UGX)",
    "Next Action Owner",
    "Next Action",
    "Risks",
)


def export_rows(items):
    """The header, then one row per item — the same items the page lists.

    Unscheduled work leaves the cost cell EMPTY rather than writing 0. A
    spreadsheet sums a column without asking what the zeros meant, and a
    budget built that way would be understated by exactly the work nobody has
    priced yet.
    """
    yield EXPORT_HEADER
    for item in items:
        yield (
            item.partner_name,
            item.school_name,
            item.district,
            item.cluster_name,
            item.responsible_cceo_name,
            item.supervising_pl_name,
            item.support_slot,
            item.target_intervention,
            item.stage,
            item.assignment_date.isoformat() if item.assignment_date else "",
            item.scheduled_date.isoformat() if item.scheduled_date else "",
            item.activity_status,
            item.evidence_status,
            item.salesforce_status,
            item.payment_status,
            item.planned_cost if item.has_cost else "",
            item.next_action_owner,
            item.next_action,
            "; ".join(r["reason"] for r in item.risks),
        )


def _attach_partner_identity(groups: list[dict]) -> None:
    """Fill each group's contact fields from one Partner query.

    `ssa_intervention_label` is a property rather than a column, so the rows
    have to be model instances — `.values()` would return the raw code and the
    page would show `government_requirements` where it used to show a label.
    """
    from apps.partners.models import Partner

    ids = [g["id"] for g in groups if g.get("id")]
    if not ids:
        return
    by_id = {p.id: p for p in Partner.all_objects.filter(id__in=ids)}
    for group in groups:
        partner = by_id.get(group.get("id"))
        if partner is None:
            continue
        # Historical work remains visible after an organisation is archived,
        # but its live profile deliberately rejects archived records.
        if partner.deleted_at is None:
            group["profile_url"] = reverse(
                "frontend:partner_detail", kwargs={"partner_id": partner.id}
            )
        group["contact_person"] = partner.contact_person or ""
        group["phone"] = partner.phone or ""
        group["region_name"] = partner.region_label
        group["intervention_label"] = partner.ssa_intervention_label or ""


def partner_contacts(items) -> list[dict]:
    """Who to call at each partner whose work is on the page.

    The grouped page carried this on each partner's header; the table layout
    keeps it as one list, because staff now reach partners only from here.
    """
    names: dict[str, str] = {}
    for item in items:
        if item.partner_id and item.partner_id not in names:
            names[item.partner_id] = item.partner_name or ""
    contacts = [
        {"id": partner_id, "name": name}
        for partner_id, name in sorted(names.items(), key=lambda kv: kv[1].lower())
    ]
    _attach_partner_identity(contacts)
    return contacts


def group_by_partner(items) -> list[dict]:
    """The page's primary organisation: one group per partner."""
    buckets: dict[tuple, list] = {}
    for item in items:
        buckets.setdefault((item.partner_id, item.partner_name), []).append(item)

    groups = []
    for (partner_id, partner_name), group_items in buckets.items():
        phases: dict[str, list] = {}
        for item in group_items:
            phases.setdefault(item.delivery_phase, []).append(item)
        groups.append(
            {
                "id": partner_id,
                "profile_url": "",
                "name": partner_name or "Unnamed partner",
                "items": group_items,
                "summary": summarize(group_items),
                "phases": phases,
                # The page's two lists, split here rather than filtered in the
                # template: a table that pages has to page over the rows it
                # actually shows, and an `{% if %}` inside the loop would give
                # it a page of ten containing three.
                "awaiting": phases.get("awaiting_schedule", []),
                "delivering": [i for i in group_items if i.is_scheduled],
            }
        )
    # Who to call, in one query for the whole page. Carried over when the
    # Partners directory merged into Partner Oversight: the directory was the
    # only place a supervisor could find a partner's contact person, and losing
    # it would have made the merge a net removal rather than a consolidation.
    _attach_partner_identity(groups)

    groups.sort(key=lambda g: g["name"])
    # Two independently paged tables per partner — the handover list and the
    # delivery list. Positional keys, so paging one partner's work does not
    # move another's and the URL names nobody.
    for index, group in enumerate(groups, start=1):
        group["awaiting_page_param"] = f"a{index}_page"
        group["scheduled_page_param"] = f"s{index}_page"
    return groups


# ── Withdrawal queues ────────────────────────────────────────────────────────
def withdrawal_requests(principal) -> list[dict]:
    """Requests waiting on this Program Lead's decision.

    Scoped by the supervisor recorded on the request rather than by re-deriving
    the team, because supervision can change between the ask and the answer and
    the request should stay with whoever it was addressed to.
    """
    from apps.partners.withdrawal_models import (
        PartnerAssignmentWithdrawal,
        WithdrawalState,
    )

    scope = _resolve_scope(principal)
    qs = PartnerAssignmentWithdrawal.objects.filter(
        state=WithdrawalState.REQUESTED
    ).select_related("school", "partner", "assignment")

    if scope.get("region_ids") is not None:
        # A withdrawal names its school but not its cluster; a cluster's
        # handover reaches the region through the assignment it withdraws.
        qs = qs.filter(
            Q(school__region_id__in=scope["region_ids"])
            | Q(assignment__cluster__region_id__in=scope["region_ids"])
        )
    elif not scope["is_country"]:
        ids = scope["staff_ids"]
        if not ids:
            return []
        qs = qs.filter(supervising_pl_id__in=ids)

    return [
        {
            "id": w.id,
            "school": getattr(w.school, "name", "") or "",
            "partner": getattr(w.partner, "name", "") or "",
            "kind_label": w.get_kind_display(),
            "reason": w.get_reason_category_display(),
            "explanation": w.partner_facing_reason,
            "internal_note": w.internal_note,
            "disposition": w.get_disposition_display(),
            "attribution": w.get_attribution_display(),
            "counts_against_partner": w.counts_against_partner,
            "planned_cost": w.original_planned_cost,
            "financially_locked": w.financial_state_at_withdrawal == "locked",
            "requested_at": w.requested_at,
            "assignment_id": w.assignment_id,
        }
        for w in qs.order_by("requested_at")[:100]
    ]


def withdrawal_history(assignment_id: str) -> list[dict]:
    """Every withdrawal decision this assignment has been through.

    A list rather than one record: an assignment can be suspended, resumed and
    later recalled, and collapsing that to "the latest" loses the pattern a
    performance review is actually looking at.
    """
    from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal

    return [
        {
            "id": w.id,
            "kind_label": w.get_kind_display(),
            "state_label": w.get_state_display(),
            "reason": w.get_reason_category_display(),
            "explanation": w.partner_facing_reason,
            "attribution": w.get_attribution_display(),
            "counts_against_partner": w.counts_against_partner,
            "requested_at": w.requested_at,
            "effective_at": w.effective_at,
            "replacement_assignment_id": w.replacement_assignment_id,
            "original_planned_cost": w.original_planned_cost,
        }
        for w in PartnerAssignmentWithdrawal.objects.filter(
            assignment_id=assignment_id
        ).order_by("requested_at")
    ]


def filter_workspace(items, *, member="", activity_type="", status=""):
    """Shared table/export filters; items have already passed access scoping."""
    return [
        item
        for item in items
        if (
            not member
            or member == "all"
            or (item.responsible_cceo_id or "unassigned") == member
        )
        and (not activity_type or item.activity_type == activity_type)
        and (not status or item.delivery_phase == status)
    ]


def order_for_monitoring(items: list) -> list:
    """Partner Monitoring's order, in place, with the Salesforce ID and
    Evidence columns set (apps.activities.completion_columns).

    Waiting-on-staff first: a hand-back nobody has decided on is the one row
    somebody here has to act on. Then, as every planned activities table
    reads (owner, 2026-09-26), open work by its activity date, oldest first —
    so overdue work leads — undated last among it, and work the Partner has
    completed (evidence and Salesforce ID in) at the bottom. School name
    orders rows that share a date.
    """
    from apps.activities.completion_columns import annotate, sort_completed_last

    annotate(items, id_attr="partner_activity_id")
    items.sort(key=lambda i: i.school_name or "")
    sort_completed_last(items, date_attr="scheduled_date")
    items.sort(key=lambda i: not i.awaits_staff_decision)
    return items


def workspace_tables(items):
    """The Partner's three tables. The schools table carries the owner's
    columns (2026-09-24): School ID, School Name, Staff Name, Training,
    Purpose of Assignment, SSA Intervention, Status, Activity date, Actions."""
    items = list(items)
    return [
        {
            "page_param": "partner_schools_page",
            "title": "Schools assigned",
            "items": [i for i in items if i.partner_assignment_id and i.school_id],
            "kind": "assignment",
            "columns": "school",
        },
        {
            "page_param": "partner_clusters_page",
            "title": "Cluster work assigned",
            "items": [i for i in items if i.partner_assignment_id and i.cluster_id],
            "kind": "assignment",
        },
        {
            "page_param": "partner_activities_page",
            "title": "Partner activities",
            "items": [i for i in items if i.partner_activity_id],
            "kind": "activity",
        },
    ]


# ── Trainings the Partner facilitates (owner, 2026-09-26) ───────────────────
#
# "All trainings assigned to partners should be under Partner Oversight as
# well, and the cost is the training fee." A partner-facilitated group
# training is the officer's work (apps.activities.facilitation): the officer
# completes it with the attendance and the Salesforce ID, and the Programme
# Lead confirms it or returns it. It reads here, under the Partner that
# facilitates it, in its own table: Cluster Name, District, Training Name,
# SSA Intervention, Training Date, Salesforce ID, Evidence, Status, Cost (the
# facilitation fee) and the action.


@dataclass
class FacilitatedTraining:
    activity_id: str
    activity_type: str
    activity_status: str
    partner_id: str
    partner_name: str = ""
    cluster_name: str = ""
    district: str = ""
    training_name: str = ""
    intervention_label: str = ""
    target_intervention: str = ""
    training_date: date | None = None
    fee: int = 0
    responsible_cceo_id: str | None = None
    responsible_cceo_name: str = ""
    supervising_pl_id: str | None = None
    supervising_pl_name: str = ""
    # completion_columns.annotate sets these.
    salesforce_id: str = ""
    evidence_label: str = ""
    salesforce_ok: bool = False
    evidence_ok: bool = False
    is_complete: bool = False
    completion_gap: str = ""
    shows_complete: bool = False
    # The view sets this: may the reader confirm or return it?
    can_review: bool = False

    @property
    def awaits_review(self) -> bool:
        """Completed by the officer and waiting on their Programme Lead."""
        return self.activity_status == "submitted_to_pl"

    @property
    def with_ia(self) -> bool:
        return self.activity_status == "awaiting_ia_verification"

    @property
    def is_returned(self) -> bool:
        from apps.activities.services import RETURNED_STATUSES

        return self.activity_status in RETURNED_STATUSES

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone

        return bool(
            not self.is_complete
            and not self.completion_gap
            and not self.is_returned
            and self.training_date
            and self.training_date < timezone.localdate()
        )

    @property
    def status_label(self) -> str:
        """Upcoming until the officer completes it; Completed once the
        attendance and the Salesforce ID are in; Verified once confirmed.
        Returned, Overdue, or what a done status is missing, when so."""
        if self.is_returned:
            return "Returned"
        if self.shows_complete:
            return "Verified"
        if self.is_complete:
            return "Completed"
        if self.completion_gap:
            return self.completion_gap
        return "Overdue" if self.is_overdue else "Upcoming"

    @property
    def delivery_phase(self) -> str:
        """The page's status filter keys (PartnerOversightItem.delivery_phase)."""
        from apps.core.activity_types import COMPLETED_WORK_STATUSES

        if self.is_returned:
            return "returned"
        if self.activity_status in COMPLETED_WORK_STATUSES:
            return "completed"
        if self.awaits_review or self.with_ia:
            return "verification"
        if self.activity_status in ("in_progress", "completion_started"):
            return "in_progress"
        return "scheduled"

    @property
    def status_tone(self) -> str:
        return {
            "Returned": "danger",
            "Overdue": "danger",
            "Verified": "success",
            "Completed": "info",
            "Upcoming": "neutral",
        }.get(self.status_label, "warning")


def facilitated_trainings(principal, *, fys=None) -> list[FacilitatedTraining]:
    """The partner-facilitated group trainings this principal may oversee,
    under the same scope as the rest of Partner Monitoring (_resolve_scope):
    the country, a region, or a Programme Lead's team and their own. Open
    work first by training date, completed work at the bottom
    (completion_columns)."""
    from types import SimpleNamespace

    from apps.activities.completion_columns import annotate, sort_completed_last
    from apps.activities.facilitation import facilitation_fees
    from apps.activities.models import Activity
    from apps.partners.models import Partner

    scope = _resolve_scope(principal)
    if scope["kind"] == "team" and not scope["staff_ids"]:
        return []
    qs = (
        Activity.objects.filter(
            deleted_at__isnull=True, facilitating_partner_id__isnull=False
        )
        .exclude(facilitating_partner_id="")
        .exclude(status__in=("cancelled", "rejected", "deferred"))
        .select_related("cluster", "cluster__district", "training_course")
    )
    if fys:
        qs = qs.filter(fy__in=tuple(str(fy) for fy in fys))
    if scope.get("region_ids") is not None:
        qs = qs.filter(cluster__region_id__in=scope["region_ids"])
    elif not scope["is_country"]:
        ids = scope["staff_ids"]
        qs = qs.filter(
            Q(responsible_staff_id__in=ids) | Q(cluster__responsible_staff_id__in=ids)
        )
    activities = list(qs)
    if not activities:
        return []

    names = dict(
        Partner.all_objects.filter(
            id__in={a.facilitating_partner_id for a in activities}
        ).values_list("id", "name")
    )
    fees = facilitation_fees([a.id for a in activities])
    directory = _staff_directory(
        [
            SimpleNamespace(
                monitoring_staff_id=None,
                assigning_staff_id=a.responsible_staff_id,
                school=None,
                cluster=a.cluster,
            )
            for a in activities
        ]
    )
    rows = []
    for activity in activities:
        owner = activity.responsible_staff_id or getattr(
            activity.cluster, "responsible_staff_id", None
        )
        canonical = directory["canonical"].get(owner, owner)
        pl_id, pl_name = directory["supervisor"].get(canonical, (None, ""))
        training, _purpose, intervention = describe_work(activity=activity)
        rows.append(
            FacilitatedTraining(
                activity_id=activity.id,
                activity_type=activity.activity_type or "",
                activity_status=activity.status or "",
                partner_id=activity.facilitating_partner_id,
                partner_name=names.get(activity.facilitating_partner_id, ""),
                cluster_name=getattr(activity.cluster, "name", "") or "",
                district=getattr(
                    getattr(activity.cluster, "district", None), "name", ""
                )
                or "",
                training_name=training,
                intervention_label=intervention,
                target_intervention=activity.focus_intervention or "",
                training_date=activity_day(activity),
                fee=fees.get(activity.id, 0),
                responsible_cceo_id=canonical,
                responsible_cceo_name=directory["names"].get(owner, ""),
                supervising_pl_id=pl_id,
                supervising_pl_name=pl_name,
            )
        )
    annotate(rows)
    sort_completed_last(rows, date_attr="training_date")
    return rows


def filter_trainings(trainings, *, member="all", activity_type="", status=""):
    """The workspace's team-member, activity-type and status filters, as they
    narrow the Partner's own work (filter_workspace)."""
    return [
        t
        for t in trainings
        if (member in ("", "all") or (t.responsible_cceo_id or "unassigned") == member)
        and (not activity_type or t.activity_type == activity_type)
        and (not status or t.delivery_phase == status)
    ]
