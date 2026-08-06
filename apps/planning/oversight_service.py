"""Planning oversight — one read model over the canonical planning ecosystem.

This is a *read* service. It owns no table, writes nothing, and adds no second
activity, work plan, budget or partner-planning system. Every value it reports
is lifted from the canonical records:

    Planning source → PartnerAssignment (where applicable) → Activity
    → ActivityScheduleCostLine → My Plan → Monthly Work Plan → Fund Request
    → Budget → Execution → Evidence → IA → Finance → Closure

Two rules give the pages their integrity, and both are structural rather than
enforced by convention:

**One item per piece of work.** A partner assignment and the activity it became
are the same work at two moments of its life. Once the partner has scheduled,
the *activity* is the item and the assignment becomes history attached to it;
before then the *assignment* is the item and it carries no cost. There is no
state in which both are emitted, so no count and no shilling can be doubled —
see `_partner_assignment_items`.

**Every summary is a fold over the items it summarises.** `summarize()` and the
grouping helpers take the list of items and reduce it. They never re-query. A
summary can therefore not disagree with the rows underneath it, because it is
made of them: the alternative — an aggregate query beside a detail query — is
exactly how two numbers on one page drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q, Sum

from apps.core.activity_types import COMPLETED_WORK_STATUSES

# Work that is live: planned, scheduled, in flight or finished. Cancelled,
# rejected, deferred and never-planned rows are not part of a plan under
# review, so they are outside every count and every total on these pages.
LIVE_ACTIVITY_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "returned_by_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "returned",
    "returned_by_ia",
    "rescheduled",
    "closed",
)

# The assignment states that mean the partner has not scheduled yet. Both
# unscheduled spellings are live in production data; PartnerAssignment owns the
# canonical tuple, and this module reads it rather than restating it.
_RETURNED_ASSIGNMENT_STATUS = "returned_to_staff"


# ── Executor and ownership vocabulary ────────────────────────────────────────
EXECUTOR_STAFF = "staff"
EXECUTOR_PARTNER = "partner"

# What the item is, in the lifecycle described in the module docstring.
STAGE_STAFF_SCHEDULED = "staff_scheduled"
STAGE_PARTNER_AWAITING_SCHEDULE = "partner_awaiting_schedule"
STAGE_PARTNER_SCHEDULED = "partner_scheduled"


@dataclass
class PlanningOversightItem:
    """One piece of planned work, at whatever point of its life it has reached.

    Deliberately a service-layer result and not a model: persisting it would be
    a copy of planning data, and a copy is a second source of truth that starts
    agreeing with the first and stops.
    """

    # Identity
    stage: str
    activity_id: str | None = None
    partner_assignment_id: str | None = None

    # Context
    school_id: str | None = None
    school_name: str = ""
    cluster_id: str | None = None
    cluster_name: str = ""
    project_id: str | None = None
    non_school_context: str = ""
    activity_type: str = ""
    target_intervention: str = ""
    operational_rationale: str = ""

    # Ownership and attribution — four different people, never collapsed.
    planned_by_id: str | None = None
    planned_by_name: str = ""
    planned_by_role: str = ""
    operational_owner_id: str | None = None
    operational_owner_name: str = ""
    executor_type: str = EXECUTOR_STAFF
    executor_id: str | None = None
    executor_name: str = ""
    managing_staff_id: str | None = None
    managing_staff_name: str = ""
    supervising_pl_id: str | None = None
    supervising_pl_name: str = ""
    partner_id: str | None = None
    partner_name: str = ""

    # Dates and period
    planned_date: date | None = None
    assigned_date: date | None = None
    schedule_by_date: date | None = None
    fy: str = ""
    month: int | None = None
    quarter: str = ""

    # Workflow state
    activity_status: str = ""
    assignment_status: str = ""
    evidence_status: str = ""
    salesforce_status: str = ""
    ia_status: str = ""
    finance_status: str = ""

    # Money — always from ActivityScheduleCostLine, never recomputed here.
    planned_cost: int = 0
    cost_missing: bool = False
    reschedule_count: int = 0

    # Derived
    risks: list[dict] = field(default_factory=list)
    next_action_owner_id: str | None = None
    next_action_owner_name: str = ""

    @property
    def is_partner_work(self) -> bool:
        return self.executor_type == EXECUTOR_PARTNER

    @property
    def is_awaiting_partner_schedule(self) -> bool:
        return self.stage == STAGE_PARTNER_AWAITING_SCHEDULE

    @property
    def is_completed(self) -> bool:
        return self.activity_status in COMPLETED_WORK_STATUSES

    @property
    def at_risk(self) -> bool:
        return bool(self.risks)

    @property
    def context_label(self) -> str:
        return (
            self.school_name
            or self.cluster_name
            or self.non_school_context
            or "No context"
        )


# ── Scope ────────────────────────────────────────────────────────────────────
@dataclass
class OversightScope:
    """Who this principal may see, resolved once and reused by every query."""

    kind: str  # "pl" | "country"
    # Both id spaces, because Activity.responsible_staff_id holds a StaffProfile
    # id or a User id depending on which path wrote it (see scoping.owner_ids).
    own_ids: set[str] = field(default_factory=set)
    supervised_ids: set[str] = field(default_factory=set)

    @property
    def team_ids(self) -> set[str]:
        return self.own_ids | self.supervised_ids

    @property
    def is_country(self) -> bool:
        return self.kind == "country"


def _both_id_spaces(staff_ids) -> set[str]:
    """Expand StaffProfile ids to also cover the User ids they belong to.

    `Activity.responsible_staff_id` may hold either, so a scope built from one
    space silently disowns most of a person's work — the same trap
    `pl_review._reviewer_staff_ids` exists to avoid.
    """
    from apps.accounts.models import StaffProfile

    ids = {i for i in staff_ids if i}
    if not ids:
        return ids
    user_ids = StaffProfile.objects.filter(id__in=ids).values_list("user_id", flat=True)
    staff_for_users = StaffProfile.objects.filter(user_id__in=ids).values_list(
        "id", flat=True
    )
    return ids | {u for u in user_ids if u} | {s for s in staff_for_users if s}


def resolve_oversight_scope(principal) -> OversightScope:
    """The oversight lens for this principal.

    A Country Director (and Admin) reads the country. A Program Lead reads
    their own work plus the work of the staff they supervise. Nobody else has
    an oversight lens here — the pages are gated on the role as well, so this
    is the second of two gates rather than the only one.
    """
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import owner_ids, resolve_user_scope

    role = getattr(principal, "active_role", "") or ""

    # Before resolving the team, not after: a country lens does not need a
    # supervisee list, and building one cost two queries on every load of the
    # largest page in the product.
    if role in (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value) or getattr(
        principal, "is_superuser", False
    ):
        return OversightScope(kind="country")

    scope = resolve_user_scope(principal)
    own = _both_id_spaces(set(owner_ids(principal)))
    supervised = _both_id_spaces(set(scope.supervised_staff_ids or []))
    # A person does not supervise themselves; keeping the sets disjoint is what
    # lets "my work" and "my team's work" stay separate totals rather than one
    # personal-performance number.
    supervised -= own
    return OversightScope(kind="pl", own_ids=own, supervised_ids=supervised)


# ── Building the items ───────────────────────────────────────────────────────
def build_items(
    principal,
    *,
    fy: str,
    month: int | None = None,
    quarter: str | None = None,
    staff_id: str | None = None,
    program_lead_id: str | None = None,
    filters: dict | None = None,
) -> list[PlanningOversightItem]:
    """Every oversight item this principal may see for the period.

    One bulk query per source, then one pass to build. No per-row queries: the
    cost of a country page is a fixed handful of statements whatever the number
    of activities, which is the difference between a page and a timeout.
    """
    scope = resolve_oversight_scope(principal)
    if scope.kind == "pl" and not scope.team_ids:
        return []

    activities = _activities_in_scope(scope, fy=fy, month=month, quarter=quarter)
    assignments = _unscheduled_assignments_in_scope(scope, fy=fy)

    directory = _StaffDirectory(activities, assignments)
    costs = _cost_by_activity([a.id for a in activities])
    partner_names = _partner_names([a.assigned_partner_id for a in activities])

    items = [_activity_item(a, directory, costs, partner_names) for a in activities]
    items += [_assignment_item(pa, directory) for pa in assignments]

    if staff_id:
        wanted = _both_id_spaces({staff_id})
        items = [
            i
            for i in items
            if (i.operational_owner_id in wanted or i.managing_staff_id in wanted)
        ]
    if program_lead_id:
        wanted = _both_id_spaces({program_lead_id})
        items = [i for i in items if i.supervising_pl_id in wanted]

    items = apply_filters(items, filters)

    # Risks last, over the finished list: the detector reads the items
    # rather than the database, so a country page stays a fixed query cost.
    from apps.planning import risk_service

    risk_service.annotate(items)

    items.sort(key=lambda i: (i.planned_date or date.max, i.context_label))
    return items


def build_item_by_reference(
    *, activity_id: str | None = None, assignment_id: str | None = None
) -> PlanningOversightItem | None:
    """One item, rebuilt from its record, with its current risks attached.

    Used by the action-resolution sweep, which has no signed-in user and must
    answer "is this condition still true?" from the same detector the page
    used to raise it. Two definitions of a risk would eventually disagree, and
    the disagreement shows up as actions that never close.
    """
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning import risk_service

    if activity_id:
        activity = (
            Activity.objects.filter(id=activity_id, deleted_at__isnull=True)
            .select_related("school", "cluster")
            .first()
        )
        if activity is None:
            return None
        directory = _StaffDirectory([activity], [])
        costs = _cost_by_activity([activity.id])
        names = _partner_names([activity.assigned_partner_id])
        item = _activity_item(activity, directory, costs, names)
    elif assignment_id:
        assignment = (
            PartnerAssignment.objects.filter(id=assignment_id)
            .select_related("school", "cluster", "partner")
            .first()
        )
        if assignment is None:
            return None
        # A scheduled assignment is no longer an awaiting-schedule item, so the
        # condition that raised the action has cleared by definition.
        if assignment.status not in (
            *PartnerAssignment.UNSCHEDULED_STATUSES,
            _RETURNED_ASSIGNMENT_STATUS,
        ):
            return None
        directory = _StaffDirectory([], [assignment])
        item = _assignment_item(assignment, directory)
    else:
        return None

    risk_service.annotate([item])
    return item


def _activities_in_scope(scope: OversightScope, *, fy, month, quarter):
    from apps.activities.models import Activity

    qs = (
        Activity.objects.filter(
            deleted_at__isnull=True, status__in=LIVE_ACTIVITY_STATUSES
        )
        .select_related("school", "cluster")
        .only(
            "id",
            "activity_type",
            "status",
            "evidence_status",
            "ia_verification_status",
            "payment_status",
            "salesforce_activity_id",
            "planned_date",
            "fy",
            "quarter",
            "planned_month",
            "responsible_staff_id",
            "monitored_by_staff_id",
            "assigned_partner_id",
            "delivery_type",
            "school_id",
            "cluster_id",
            "project_id",
            "focus_intervention",
            "purpose_intervention",
            "support_rationale",
            "activity_purpose_text",
            "cost_missing",
            "reschedule_count",
            "venue",
            "school__name",
            "cluster__name",
        )
    )
    if fy:
        qs = qs.filter(fy=fy)
    if month:
        qs = qs.filter(planned_month=month)
    if quarter:
        qs = qs.filter(quarter=quarter)

    if not scope.is_country:
        ids = scope.team_ids
        qs = qs.filter(
            Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids)
        )
    return list(qs)


def _unscheduled_assignments_in_scope(scope: OversightScope, *, fy):
    """Partner assignments the partner has not scheduled yet.

    Scheduled ones are deliberately absent: they are represented by the
    activity they became, which `_activities_in_scope` already returned. This
    is the single place the no-double-count rule lives.
    """
    from apps.partners.models import PartnerAssignment

    qs = (
        PartnerAssignment.objects.filter(
            status__in=(
                *PartnerAssignment.UNSCHEDULED_STATUSES,
                _RETURNED_ASSIGNMENT_STATUS,
            )
        )
        .select_related("school", "cluster", "partner")
        .only(
            "id",
            "status",
            "school_id",
            "cluster_id",
            "project_id",
            "partner_id",
            "assigning_staff_id",
            "monitoring_staff_id",
            "expected_activity_type",
            "focus_intervention",
            "purpose_of_visit",
            "purpose",
            "notes",
            "scheduled_date",
            "created_at",
            "school__name",
            "cluster__name",
            "partner__name",
        )
    )
    if not scope.is_country:
        ids = scope.team_ids
        qs = qs.filter(Q(monitoring_staff_id__in=ids) | Q(assigning_staff_id__in=ids))
    rows = list(qs)

    # The assignment has no fiscal year column; its period comes from the date
    # it was handed over, which is what oversight tracks it by until the
    # partner picks a delivery date.
    if fy:
        from apps.core.fy import get_operational_fy

        rows = [r for r in rows if get_operational_fy(r.created_at.date()) == fy]
    return rows


def _cost_by_activity(activity_ids) -> dict[str, int]:
    """Planned cost per activity, from the canonical cost lines, in one query.

    Summed from ActivityScheduleCostLine rather than read from
    Activity.est_cost_cents so the page and the budget cannot disagree: the
    lines are what the fund request, the monthly budget and the annual budget
    are built from.
    """
    from apps.activities.models import ActivityScheduleCostLine

    if not activity_ids:
        return {}
    rows = (
        ActivityScheduleCostLine.objects.filter(activity_id__in=activity_ids)
        .values("activity_id")
        .annotate(total=Sum("amount"))
    )
    return {r["activity_id"]: int(r["total"] or 0) for r in rows}


def _partner_names(partner_ids) -> dict[str, str]:
    """Partner names for activity rows, in one query rather than one per row."""
    from apps.partners.models import Partner

    ids = {p for p in partner_ids if p}
    if not ids:
        return {}
    return dict(Partner.objects.filter(id__in=ids).values_list("id", "name"))


class _StaffDirectory:
    """Names and supervisors for every person referenced, in three queries.

    Built up-front from the ids actually present, because the alternative — a
    lookup per row — is the N+1 that makes a country page unusable.
    """

    def __init__(self, activities, assignments):
        ids: set[str] = set()
        for a in activities:
            ids.update({a.responsible_staff_id, a.monitored_by_staff_id})
        for pa in assignments:
            ids.update({pa.monitoring_staff_id, pa.assigning_staff_id})
        ids.discard(None)
        ids.discard("")

        self._names: dict[str, str] = {}
        self._roles: dict[str, str] = {}
        self._supervisor_of: dict[str, str] = {}
        self._staff_for: dict[str, str] = {}

        if not ids:
            return

        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

        profiles = StaffProfile.objects.filter(
            Q(id__in=ids) | Q(user_id__in=ids)
        ).select_related("user")
        staff_ids = set()
        for p in profiles:
            name = getattr(p.user, "name", "") or getattr(p.user, "email", "")
            role = getattr(p.user, "active_role", "") or ""
            staff_ids.add(p.id)
            for key in (p.id, p.user_id):
                if key:
                    self._names[key] = name
                    self._roles[key] = role
                    self._staff_for[key] = p.id

        links = StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=staff_ids
        ).select_related("supervisor__user")
        for link in links:
            supervisor_user = getattr(link.supervisor, "user", None)
            supervisor_name = (
                getattr(supervisor_user, "name", "")
                or getattr(supervisor_user, "email", "")
                or ""
            )
            self._supervisor_of[link.supervisee_id] = link.supervisor_id
            if link.supervisor_id:
                self._names.setdefault(link.supervisor_id, supervisor_name)
                if supervisor_user is not None:
                    self._names.setdefault(supervisor_user.id, supervisor_name)

    def name(self, staff_id) -> str:
        return self._names.get(staff_id, "") if staff_id else ""

    def role(self, staff_id) -> str:
        return self._roles.get(staff_id, "") if staff_id else ""

    def supervisor_of(self, staff_id) -> tuple[str | None, str]:
        if not staff_id:
            return None, ""
        canonical = self._staff_for.get(staff_id, staff_id)
        supervisor_id = self._supervisor_of.get(canonical)
        return supervisor_id, self._names.get(
            supervisor_id, ""
        ) if supervisor_id else ""


def _activity_item(
    activity, directory: _StaffDirectory, costs, partner_names
) -> PlanningOversightItem:
    is_partner = bool(activity.assigned_partner_id)

    # The internal owner. For partner work the partner executes but a member of
    # staff remains answerable for it, and that person is the monitor — not the
    # partner, and not whoever happened to hand it over.
    owner_id = (
        activity.monitored_by_staff_id
        if is_partner
        else (activity.responsible_staff_id or activity.monitored_by_staff_id)
    )
    supervising_pl_id, supervising_pl_name = directory.supervisor_of(owner_id)

    item = PlanningOversightItem(
        stage=STAGE_PARTNER_SCHEDULED if is_partner else STAGE_STAFF_SCHEDULED,
        activity_id=activity.id,
        school_id=activity.school_id,
        school_name=getattr(activity.school, "name", "") or "",
        cluster_id=activity.cluster_id,
        cluster_name=getattr(activity.cluster, "name", "") or "",
        project_id=activity.project_id,
        non_school_context=activity.venue or "",
        activity_type=activity.activity_type,
        target_intervention=(
            activity.focus_intervention or activity.purpose_intervention or ""
        ),
        operational_rationale=(
            activity.support_rationale or activity.activity_purpose_text or ""
        ),
        planned_by_id=activity.responsible_staff_id or activity.monitored_by_staff_id,
        planned_by_name=directory.name(
            activity.responsible_staff_id or activity.monitored_by_staff_id
        ),
        planned_by_role=directory.role(
            activity.responsible_staff_id or activity.monitored_by_staff_id
        ),
        operational_owner_id=owner_id,
        operational_owner_name=directory.name(owner_id),
        executor_type=EXECUTOR_PARTNER if is_partner else EXECUTOR_STAFF,
        executor_id=activity.assigned_partner_id or owner_id,
        managing_staff_id=activity.monitored_by_staff_id if is_partner else None,
        managing_staff_name=(
            directory.name(activity.monitored_by_staff_id) if is_partner else ""
        ),
        supervising_pl_id=supervising_pl_id,
        supervising_pl_name=supervising_pl_name,
        partner_id=activity.assigned_partner_id,
        partner_name=partner_names.get(activity.assigned_partner_id, ""),
        planned_date=activity.planned_date,
        fy=activity.fy or "",
        month=activity.planned_month,
        quarter=activity.quarter or "",
        activity_status=activity.status,
        evidence_status=activity.evidence_status or "",
        salesforce_status="recorded" if activity.salesforce_activity_id else "missing",
        ia_status=activity.ia_verification_status or "",
        finance_status=activity.payment_status or "",
        planned_cost=int(costs.get(activity.id, 0)),
        cost_missing=bool(activity.cost_missing),
        reschedule_count=int(activity.reschedule_count or 0),
    )
    item.executor_name = (
        item.partner_name if is_partner else item.operational_owner_name
    )
    return item


def _assignment_item(assignment, directory: _StaffDirectory) -> PlanningOversightItem:
    """A partner assignment the partner has not scheduled.

    `planned_cost` is zero and that is the point: nothing has been scheduled,
    so no cost line exists, so the plan carries no money for it yet. Reporting
    an expected cost here would put unapproved, unpriced money into a budget.
    """
    owner_id = assignment.monitoring_staff_id or assignment.assigning_staff_id
    supervising_pl_id, supervising_pl_name = directory.supervisor_of(owner_id)

    return PlanningOversightItem(
        stage=STAGE_PARTNER_AWAITING_SCHEDULE,
        partner_assignment_id=assignment.id,
        school_id=assignment.school_id,
        school_name=getattr(assignment.school, "name", "") or "",
        cluster_id=assignment.cluster_id,
        cluster_name=getattr(assignment.cluster, "name", "") or "",
        project_id=assignment.project_id,
        activity_type=assignment.expected_activity_type or "",
        target_intervention=assignment.focus_intervention or "",
        operational_rationale=(
            assignment.purpose_of_visit or assignment.purpose or assignment.notes or ""
        ),
        planned_by_id=assignment.assigning_staff_id,
        planned_by_name=directory.name(assignment.assigning_staff_id),
        planned_by_role=directory.role(assignment.assigning_staff_id),
        operational_owner_id=owner_id,
        operational_owner_name=directory.name(owner_id),
        executor_type=EXECUTOR_PARTNER,
        executor_id=assignment.partner_id,
        executor_name=getattr(assignment.partner, "name", "") or "",
        managing_staff_id=owner_id,
        managing_staff_name=directory.name(owner_id),
        supervising_pl_id=supervising_pl_id,
        supervising_pl_name=supervising_pl_name,
        partner_id=assignment.partner_id,
        partner_name=getattr(assignment.partner, "name", "") or "",
        assigned_date=assignment.created_at.date() if assignment.created_at else None,
        schedule_by_date=assignment.scheduled_date,
        assignment_status=assignment.status,
        planned_cost=0,
        next_action_owner_id=assignment.partner_id,
        next_action_owner_name=getattr(assignment.partner, "name", "") or "",
    )


# ── Advanced filters ─────────────────────────────────────────────────────────
# Applied to the built items rather than pushed into SQL. That is deliberate:
# executor type, risk and cost state are properties of the assembled item, some
# of them spanning two source tables, and expressing them as query predicates
# would mean two definitions of each — one for the list and one for the filter.
FILTER_KEYS = (
    "activity_type",
    "executor_type",
    "partner_id",
    "district_id",
    "status",
    "risk",
    "context",
)


def apply_filters(items, filters: dict | None):
    """Narrow the items by the advanced filter drawer's selections."""
    if not filters:
        return items

    def keep(item) -> bool:
        if (want := filters.get("activity_type")) and item.activity_type != want:
            return False
        if (want := filters.get("executor_type")) and item.executor_type != want:
            return False
        if (want := filters.get("partner_id")) and item.partner_id != want:
            return False
        if want := filters.get("status"):
            current = (
                item.assignment_status
                if item.is_awaiting_partner_schedule
                else item.activity_status
            )
            if current != want:
                return False
        if want := filters.get("risk"):
            keys = {r["key"] for r in item.risks}
            if want == "any" and not keys:
                return False
            if want != "any" and want not in keys:
                return False
        if want := filters.get("context"):
            if want == "school" and not item.school_id:
                return False
            if want == "cluster" and not item.cluster_id:
                return False
            if want == "project" and not item.project_id:
                return False
            if want == "non_school" and (item.school_id or item.cluster_id):
                return False
        return True

    return [item for item in items if keep(item)]


def read_filters(request) -> dict:
    """The advanced filters present on this request, ignoring blanks."""
    return {
        key: value
        for key in FILTER_KEYS
        if (value := (request.GET.get(key) or "").strip())
    }


# ── Export ───────────────────────────────────────────────────────────────────
EXPORT_COLUMNS = (
    ("Financial year", lambda i: i.fy),
    ("Planned date", lambda i: i.planned_date.isoformat() if i.planned_date else ""),
    ("Activity type", lambda i: i.activity_type),
    ("Context", lambda i: i.context_label),
    ("Planning stage", lambda i: i.stage),
    ("Planned by", lambda i: i.planned_by_name),
    ("Operational owner", lambda i: i.operational_owner_name),
    ("Executor type", lambda i: i.executor_type),
    ("Executor", lambda i: i.executor_name),
    ("Managing staff", lambda i: i.managing_staff_name),
    ("Supervising PL", lambda i: i.supervising_pl_name),
    ("Partner", lambda i: i.partner_name),
    ("Intervention", lambda i: i.target_intervention),
    ("Planned cost (UGX)", lambda i: i.planned_cost),
    ("Activity status", lambda i: i.activity_status),
    ("Assignment status", lambda i: i.assignment_status),
    ("Evidence", lambda i: i.evidence_status),
    ("Salesforce", lambda i: i.salesforce_status),
    ("IA", lambda i: i.ia_status),
    ("Finance", lambda i: i.finance_status),
    ("Risks", lambda i: "; ".join(r["key"] for r in i.risks)),
    ("Next action owner", lambda i: i.next_action_owner_name),
)


def export_rows(items):
    """Header row then one row per item, in the order the page shows them.

    Built from the same items the page rendered, so an export cannot contain a
    row the viewer could not see or a total the page did not show. No evidence
    files or free-text notes are included — an export is a plan, not a record
    store.
    """
    yield [label for label, _ in EXPORT_COLUMNS]
    for item in items:
        yield [getter(item) for _, getter in EXPORT_COLUMNS]


# ── Folds ────────────────────────────────────────────────────────────────────
def summarize(items) -> dict:
    """Every headline number, folded from the items shown underneath them.

    Nothing here re-queries. A KPI that disagrees with the table below it is
    not possible while this stays a fold, which is the whole reason it is one.
    """
    items = list(items)
    staff_scheduled = [i for i in items if i.stage == STAGE_STAFF_SCHEDULED]
    partner_awaiting = [i for i in items if i.is_awaiting_partner_schedule]
    partner_scheduled = [i for i in items if i.stage == STAGE_PARTNER_SCHEDULED]
    scheduled = staff_scheduled + partner_scheduled

    # Execution progress counts only work whose date has arrived. Future work
    # is not late, and counting it as unfinished would report every team as
    # behind on the first day of a period.
    today = date.today()
    due = [i for i in scheduled if i.planned_date and i.planned_date <= today]
    completed_due = [i for i in due if i.is_completed]

    return {
        "total_planned": len(items),
        "staff_scheduled": len(staff_scheduled),
        "partner_awaiting_schedule": len(partner_awaiting),
        "partner_scheduled": len(partner_scheduled),
        "scheduled_total": len(scheduled),
        "at_risk": len([i for i in items if i.at_risk]),
        "needs_attention": len([i for i in items if i.at_risk]),
        "planned_budget": sum(i.planned_cost for i in items),
        "completed": len([i for i in items if i.is_completed]),
        "due_count": len(due),
        "execution_progress": (
            round(len(completed_due) * 100 / len(due)) if due else None
        ),
        "cost_missing": len([i for i in scheduled if i.cost_missing]),
    }


def group_by_owner(items) -> list[dict]:
    """Items folded per operational owner — the PL page's default lens."""
    return _group(
        items, key=lambda i: (i.operational_owner_id, i.operational_owner_name)
    )


def group_by_program_lead(items) -> list[dict]:
    """Items folded per supervising Program Lead — the CD page's default lens."""
    return _group(items, key=lambda i: (i.supervising_pl_id, i.supervising_pl_name))


def _group(items, *, key) -> list[dict]:
    buckets: dict[tuple, list] = {}
    for item in items:
        buckets.setdefault(key(item), []).append(item)

    groups = []
    for (group_id, group_name), group_items in buckets.items():
        groups.append(
            {
                "id": group_id,
                "name": group_name or "Unassigned",
                "items": group_items,
                "summary": summarize(group_items),
            }
        )
    groups.sort(key=lambda g: (g["name"] == "Unassigned", g["name"]))
    return groups


def split_own_and_team(items, scope: OversightScope) -> dict:
    """The PL's own work kept apart from the team's.

    Combining them would turn a supervision page into a personal-performance
    number, which is the opposite of what it is for: a Program Lead is not
    credited with a CCEO's visit, and a CCEO's visit is not the PL's execution.
    """
    own, cceo, partner = [], [], []
    for item in items:
        if item.is_partner_work:
            partner.append(item)
        elif item.operational_owner_id in scope.own_ids:
            own.append(item)
        else:
            cceo.append(item)
    return {
        "own": own,
        "cceo": cceo,
        "partner": partner,
        "own_summary": summarize(own),
        "cceo_summary": summarize(cceo),
        "partner_summary": summarize(partner),
    }
