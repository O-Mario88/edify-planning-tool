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

from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date

from django.db.models import F, Q, QuerySet, Sum

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.partners.purposes import visit_purpose_label

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
    school_code: str = ""
    school_name: str = ""
    school_type: str = ""
    district_id: str | None = None
    district_name: str = ""
    region_name: str = ""
    cluster_id: str | None = None
    cluster_name: str = ""
    project_id: str | None = None
    non_school_context: str = ""
    activity_type: str = ""
    target_intervention: str = ""
    operational_rationale: str = ""
    purpose_of_visit: str = ""

    # Training & Cluster specifics
    training_name: str = ""
    participants: int = 0
    delivery_type: str = ""
    cluster_planned_from: str = ""
    budget: int = 0
    is_in_school_training: bool = False

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
    # The moment the completion entered the Impact Assessment queue. Carried
    # rather than derived from updated_at, because the model keeps it distinct
    # for exactly this purpose: an SLA measured from a mutable timestamp resets
    # itself every time somebody opens the record.
    submitted_to_ia_at: date | None = None

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

    kind: str  # "pl" | "region" | "country"
    # Both id spaces, because Activity.responsible_staff_id holds a StaffProfile
    # id or a User id depending on which path wrote it (see scoping.owner_ids).
    own_ids: set[str] = field(default_factory=set)
    supervised_ids: set[str] = field(default_factory=set)
    # The regions a "region" scope is bounded to (the Regional Programme Lead).
    region_ids: tuple[str, ...] = ()

    @property
    def team_ids(self) -> set[str]:
        return self.own_ids | self.supervised_ids

    @property
    def is_country(self) -> bool:
        return self.kind == "country"

    @property
    def is_region(self) -> bool:
        return self.kind == "region"

    @property
    def groups_by_lead(self) -> bool:
        """Whether this lens reads many Programme Leads and is therefore
        organised in their tabs — the country lens, and the region lens."""
        return self.kind in ("country", "region")


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
    if role in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.PROGRAM_ACCOUNTANT.value,
        EdifyRole.ADMIN.value,
    ) or getattr(principal, "is_superuser", False):
        return OversightScope(kind="country")

    # The Regional Programme Lead reads their region's countries: every
    # Programme Lead in them and every CCEO those Leads supervise, in the same
    # Lead tabs the country lens uses (owner, 2026-09-12). The reach comes from
    # the geography an administrator assigns (apps.core.scoping
    # `_regional_reach`); with none assigned it is every country, and the page
    # says so.
    if role == EdifyRole.REGIONAL_PROGRAM_LEAD.value:
        from apps.core.scoping import resolve_user_scope as _resolve

        return OversightScope(
            kind="region", region_ids=tuple(_resolve(principal).region_ids or ())
        )

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
    date_start: date | None = None,
    date_end: date | None = None,
    staff_id: str | None = None,
    program_lead_id: str | None = None,
    filters: dict | None = None,
    fys: tuple[str, ...] | None = None,
    activity_types: tuple[str, ...] | None = None,
    cluster_work_only: bool = False,
    core_work_only: bool = False,
) -> list[PlanningOversightItem]:
    """Every oversight item this principal may see for the period.

    One bulk query per source, then one pass to build. No per-row queries: the
    cost of a country page is a fixed handful of statements whatever the number
    of activities, which is the difference between a page and a timeout.

    ``fys``, when given, reads those fiscal years instead of ``fy`` alone — a
    planning horizon (``fy_policy.planning_horizon``) in one query.

    ``activity_types`` and ``cluster_work_only`` narrow what is read, for a
    lens that shows only part of the plan: Cluster Oversight built every item
    in the country to keep its cluster sessions (2026-09-24 audit). Each item
    is built exactly as it would be in the full list.

    ``core_work_only`` keeps work at core schools and cluster trainings with
    no school — a superset of what Core School Oversight lists, which built
    every item in the country over two fiscal years to keep them (2026-09-24
    A+ audit).
    """
    scope = resolve_oversight_scope(principal)
    if scope.kind == "pl" and not scope.team_ids:
        return []

    years = tuple(str(y) for y in fys) if fys else ((fy,) if fy else ())
    activity_qs = _activity_queryset(
        scope,
        fy=years,
        month=month,
        quarter=quarter,
        date_start=date_start,
        date_end=date_end,
        activity_types=activity_types,
        cluster_work_only=cluster_work_only,
        core_work_only=core_work_only,
    )
    activities = _activity_records_of(activity_qs)
    assignments = _unscheduled_assignments_in_scope(
        scope,
        fy=years,
        month=month,
        quarter=quarter,
        date_start=date_start,
        date_end=date_end,
        activity_types=activity_types,
        cluster_work_only=cluster_work_only,
        core_work_only=core_work_only,
    )

    directory = _StaffDirectory(activities, assignments)
    # The cost totals read the same activities through the same filter as a
    # subquery, rather than binding every id just read as one literal array:
    # the planner estimates an `= ANY(array)` element by element, and for a
    # country's ~75,000 ids that was ~0.3 s of planning ahead of a few
    # milliseconds of execution (2026-09-24 A+ audit).
    costs = (
        _cost_by_activity(activity_qs.values_list("id", flat=True))
        if activities and activity_qs is not None
        else {}
    )
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


def _fy_tuple(fy) -> tuple[str, ...]:
    """One fiscal year or several, as the tuple the period filters compare."""
    if isinstance(fy, (list, tuple, set, frozenset)):
        return tuple(str(y) for y in fy)
    return (str(fy),)


#: The activity columns an oversight item is built from, read as plain values.
_ACTIVITY_COLUMNS = (
    "id",
    "activity_type",
    "status",
    "evidence_status",
    "ia_verification_status",
    "payment_status",
    # The IA queue clock, read by the risk detector.
    "submitted_to_ia_at",
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
    "training_course_id",
    "focus_intervention",
    "purpose_intervention",
    "support_rationale",
    "activity_purpose_text",
    "purpose_type",
    "activity_name_snapshot",
    "paired_school_visit_id",
    "participants_per_school",
    "expected_participants",
    "cost_missing",
    "reschedule_count",
    "venue",
)
_SCHOOL_COLUMNS = (
    "school__school_id",
    "school__name",
    "school__school_type",
    "school__district_id",
    "school__district__name",
    "school__region_id",
    "school__region__name",
)
_CLUSTER_COLUMNS = (
    "cluster__name",
    "cluster__district_id",
    "cluster__district__name",
    "cluster__district__region_id",
    "cluster__district__region__name",
)
_COURSE_COLUMNS = (
    "training_course__display_name",
    "training_course__source_name",
)


#: One activity row, with attribute access shaped like the model.
#:
#: An oversight page reads a fixed set of columns from every activity in its
#: scope. As model instances, each with six joined relations, that was
#: ~520,000 objects for the country at 50,000 schools, and most of an 11 s
#: request (2026-09-24 live-performance audit, R2). `_activity_item` reads the
#: same attributes off these as off a model, and `build_item_by_reference`
#: still passes it a real one. Named tuples rather than objects with a dict
#: each: one small object per row instead of two large ones, which is also
#: less for the garbage collector to walk on a 74,000-row page.
_ActivityRecord = namedtuple(
    "_ActivityRecord", (*_ACTIVITY_COLUMNS, "school", "cluster", "training_course")
)
_SchoolRecord = namedtuple(
    "_SchoolRecord",
    (
        "school_id",
        "name",
        "school_type",
        "district_id",
        "district",
        "region_id",
        "region",
    ),
)
_ClusterRecord = namedtuple("_ClusterRecord", ("name", "district_id", "district"))
_ClusterDistrictRecord = namedtuple(
    "_ClusterDistrictRecord", ("name", "region_id", "region")
)
_DistrictRecord = namedtuple("_DistrictRecord", ("name",))
_RegionRecord = namedtuple("_RegionRecord", ("name",))
_CourseRecord = namedtuple("_CourseRecord", ("display_name", "source_name"))


def _activity_records(rows) -> list[_ActivityRecord]:
    """One record per activity row; each school, cluster, district, region
    and course is one shared record however many activities point at it."""
    width = len(_ACTIVITY_COLUMNS)
    school_end = width + len(_SCHOOL_COLUMNS)
    cluster_end = school_end + len(_CLUSTER_COLUMNS)
    school_at = _ACTIVITY_COLUMNS.index("school_id")
    cluster_at = _ACTIVITY_COLUMNS.index("cluster_id")
    course_at = _ACTIVITY_COLUMNS.index("training_course_id")
    names: dict[tuple, tuple] = {}
    schools: dict[str, _SchoolRecord] = {}
    clusters: dict[str, _ClusterRecord] = {}
    courses: dict[str, _CourseRecord] = {}

    def named(kind, key, *fields):
        if key is None:
            return None
        found = names.get((kind, key))
        if found is None:
            found = names[(kind, key)] = kind(*fields)
        return found

    records = []
    for row in rows:
        school_id = row[school_at]
        school = None
        if school_id is not None:
            school = schools.get(school_id)
            if school is None:
                (
                    code,
                    school_name,
                    school_type,
                    district_id,
                    district_name,
                    region_id,
                    region_name,
                ) = row[width:school_end]
                school = schools[school_id] = _SchoolRecord(
                    code,
                    school_name,
                    school_type,
                    district_id,
                    named(_DistrictRecord, district_id, district_name),
                    region_id,
                    named(_RegionRecord, region_id, region_name),
                )

        cluster_id = row[cluster_at]
        cluster = None
        if cluster_id is not None:
            cluster = clusters.get(cluster_id)
            if cluster is None:
                (
                    cluster_name,
                    district_id,
                    district_name,
                    region_id,
                    region_name,
                ) = row[school_end:cluster_end]
                region = named(_RegionRecord, region_id, region_name)
                cluster = clusters[cluster_id] = _ClusterRecord(
                    cluster_name,
                    district_id,
                    named(
                        _ClusterDistrictRecord,
                        district_id,
                        district_name,
                        region_id,
                        region,
                    ),
                )

        course_id = row[course_at]
        course = None
        if course_id is not None:
            course = courses.get(course_id)
            if course is None:
                course = courses[course_id] = _CourseRecord(*row[cluster_end:])
        records.append(_ActivityRecord(*row[:width], school, cluster, course))
    return records


def _dated_between(start: date | None, end: date | None) -> Q:
    """Activities dated in [start, end), read the way My Plan reads a date.

    The planned date is the source of truth; an older scheduled row with no
    planned date falls back to its scheduled timestamp
    (``apps.my_plan.services._scheduled_in_range``). Reading the date alone
    here dropped those rows from a period on oversight while My Plan listed
    them.
    """
    planned = Q()
    scheduled = Q(planned_date__isnull=True)
    if start:
        planned &= Q(planned_date__gte=start)
        scheduled &= Q(scheduled_date__date__gte=start)
    if end:
        planned &= Q(planned_date__lt=end)
        scheduled &= Q(scheduled_date__date__lt=end)
    return planned | scheduled


def _in_month(month: int, fys: tuple[str, ...]) -> Q:
    """Activities in one calendar month of the given fiscal years.

    My Plan decides the month by the planned date, not by the convenience
    ``planned_month`` column, which older rows left empty — so a dated legacy
    visit sat in its month on My Plan and in no month on oversight. The date
    decides here too; ``planned_month`` still places an undated row, which
    oversight reports and My Plan's month slice does not, and showing more
    than My Plan is allowed where showing less is not.
    """
    match = Q(planned_date__isnull=True, scheduled_date__isnull=True) & Q(
        planned_month=month
    )
    for fy in fys:
        year = int(fy) - 1 if month >= 10 else int(fy)
        first = date(year, month, 1)
        after = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        match |= _dated_between(first, after)
    if not fys:
        match |= Q(planned_month=month)
    return match


def _activities_in_scope(
    scope: OversightScope,
    *,
    fy,
    month,
    quarter,
    date_start=None,
    date_end=None,
    activity_types=None,
    cluster_work_only=False,
):
    return _activity_records_of(
        _activity_queryset(
            scope,
            fy=fy,
            month=month,
            quarter=quarter,
            date_start=date_start,
            date_end=date_end,
            activity_types=activity_types,
            cluster_work_only=cluster_work_only,
        )
    )


def _activity_records_of(qs) -> list[_ActivityRecord]:
    """The records of `_activity_queryset`'s activities, in its order."""
    if qs is None:
        return []
    return _activity_records(
        qs.values_list(
            *_ACTIVITY_COLUMNS, *_SCHOOL_COLUMNS, *_CLUSTER_COLUMNS, *_COURSE_COLUMNS
        )
    )


def _activity_queryset(
    scope: OversightScope,
    *,
    fy,
    month,
    quarter,
    date_start=None,
    date_end=None,
    activity_types=None,
    cluster_work_only=False,
    core_work_only=False,
):
    """The activities this lens reads for the period, ordered; None for a
    region lens with no region to read."""
    from apps.activities.models import Activity

    qs = Activity.objects.filter(
        deleted_at__isnull=True, status__in=LIVE_ACTIVITY_STATUSES
    )
    if activity_types is not None:
        qs = qs.filter(activity_type__in=activity_types)
    if cluster_work_only:
        qs = qs.filter(cluster_id__isnull=False)
    if core_work_only:
        qs = qs.filter(
            Q(school__school_type="core")
            | Q(
                school_id__isnull=True,
                cluster_id__isnull=False,
                activity_type__in=TRAINING_TYPES,
            )
        )
    if fy:
        qs = qs.filter(fy__in=_fy_tuple(fy))
    if month:
        qs = qs.filter(_in_month(month, _fy_tuple(fy) if fy else ()))
    if quarter:
        qs = qs.filter(quarter=quarter)
    if date_start or date_end:
        qs = qs.filter(_dated_between(date_start, date_end))

    if scope.is_region and not scope.region_ids:
        return None
    scope_q = _activity_scope_q(scope)
    if scope_q is not None:
        qs = qs.filter(scope_q)
    # The model's own order, made total: build_items sorts by date and
    # context, and ties keep this order, so a tie never reshuffles between
    # two loads of the same page.
    return qs.order_by("-created_at", "id")


def _activity_scope_q(scope: OversightScope):
    """Which activities this lens reads, as one filter (None for the country).

    The page's list and the record drawer both ask this, so an item the page
    shows is an item its drawer opens (Program Lead walk, 2026-09-14: the drawer used
    to check the responsible officer only and returned 404 for team-school
    work owned by someone outside the team).
    """
    if scope.is_country:
        return None
    if scope.is_region:
        # Geography, not the reporting line: a region's oversight is every
        # activity delivered at a school in it, plus the cluster work whose
        # district sits in it. That covers partner-delivered work, which
        # carries no responsible staff member at all.
        return Q(school__region_id__in=scope.region_ids) | Q(
            cluster__district__region_id__in=scope.region_ids
        )
    ids = scope.team_ids
    # Ownership of the school and of the cluster are the third and fourth
    # arms, and they are what make partner work visible.
    #
    # A partner-delivered activity carries NO responsible staff member by
    # construction (_partner_schedule_from_assignment sets it to None), and
    # `monitored_by_staff_id` records whoever happened to be resolved at
    # handoff. So on the first two arms alone a school's own CCEO saw 6 of
    # the 233 partner activities running in their portfolio, and a Program
    # Lead — who supervises rather than owns — saw none of them at all.
    #
    # partner_oversight_service.build_items already reached this
    # conclusion for handovers: owning the school is the durable claim
    # because it does not depend on who clicked Handoff. The same holds
    # for the activity that handover became, and the cluster arm carries
    # the trainings, which have no school at all.
    return (
        Q(responsible_staff_id__in=ids)
        | Q(monitored_by_staff_id__in=ids)
        | Q(school__account_owner_id__in=ids)
        | Q(cluster__responsible_staff_id__in=ids)
    )


def _assignment_scope_q(scope: OversightScope):
    """Which unscheduled partner assignments this lens reads (None: country)."""
    if scope.is_country:
        return None
    if scope.is_region:
        return Q(school__region_id__in=scope.region_ids) | Q(
            cluster__district__region_id__in=scope.region_ids
        )
    ids = scope.team_ids
    return Q(monitoring_staff_id__in=ids) | Q(assigning_staff_id__in=ids)


def record_in_scope(
    scope: OversightScope,
    *,
    activity_id: str | None = None,
    assignment_id: str | None = None,
) -> bool:
    """Whether the lens reads this one record, by the list's own rule."""
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment

    if scope.is_region and not scope.region_ids:
        return False
    if activity_id:
        qs = Activity.objects.filter(id=activity_id, deleted_at__isnull=True)
        scope_q = _activity_scope_q(scope)
    elif assignment_id:
        qs = PartnerAssignment.objects.filter(id=assignment_id)
        scope_q = _assignment_scope_q(scope)
    else:
        return False
    if scope_q is not None:
        qs = qs.filter(scope_q)
    return qs.exists()


def _unscheduled_assignments_in_scope(
    scope: OversightScope,
    *,
    fy,
    month=None,
    quarter=None,
    date_start=None,
    date_end=None,
    activity_types=None,
    cluster_work_only=False,
    core_work_only=False,
):
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
        .select_related(
            "school",
            "school__district",
            "school__region",
            "cluster",
            "cluster__district",
            "cluster__district__region",
            "partner",
        )
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
            "school__school_id",
            "school__name",
            "school__school_type",
            "school__district_id",
            "school__district__name",
            "school__region_id",
            "school__region__name",
            "cluster__name",
            "cluster__district_id",
            "cluster__district__name",
            "cluster__district__region_id",
            "cluster__district__region__name",
            "partner__name",
        )
    )
    if activity_types is not None:
        qs = qs.filter(expected_activity_type__in=activity_types)
    if cluster_work_only:
        qs = qs.filter(cluster_id__isnull=False)
    if core_work_only:
        # An assignment item is never a cluster session (it has no activity),
        # so only its school decides.
        qs = qs.filter(school__school_type="core")
    if scope.is_region and not scope.region_ids:
        return []
    scope_q = _assignment_scope_q(scope)
    if scope_q is not None:
        qs = qs.filter(scope_q)
    rows = list(qs)

    # The assignment has no fiscal year column; its period comes from the date
    # it was handed over, which is what oversight tracks it by until the
    # partner picks a delivery date.
    if fy:
        from apps.core.fy import get_operational_fy

        years = _fy_tuple(fy)
        rows = [r for r in rows if get_operational_fy(r.created_at.date()) in years]
    if month:
        rows = [r for r in rows if r.created_at.date().month == month]
    if quarter:
        from apps.core.fy import get_quarter_for_date

        rows = [r for r in rows if get_quarter_for_date(r.created_at) == quarter]
    if date_start:
        rows = [r for r in rows if r.created_at.date() >= date_start]
    if date_end:
        rows = [r for r in rows if r.created_at.date() < date_end]
    return rows


def _cost_by_activity(activity_ids) -> dict[str, int]:
    """Planned cost per activity, from the canonical cost lines, in one query.

    Summed from ActivityScheduleCostLine rather than read from
    Activity.est_cost_cents so the page and the budget cannot disagree: the
    lines are what the fund request, the monthly budget and the annual budget
    are built from.
    """
    from apps.activities.models import ActivityScheduleCostLine

    if isinstance(activity_ids, QuerySet):
        # The activities as a subquery: the same ids without a literal array.
        # Never tested for truth, which would read every id in Python first.
        lines = ActivityScheduleCostLine.objects.filter(activity_id__in=activity_ids)
    else:
        if not activity_ids:
            return {}
        # One array parameter, not one bind parameter per activity.
        from apps.core.scoping import any_id

        lines = ActivityScheduleCostLine.objects.filter(
            any_id("activity_id", activity_ids)
        )
    rows = lines.values_list("activity_id").annotate(total=Sum("amount"))
    return {activity_id: int(total or 0) for activity_id, total in rows}


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
        self._leads: dict[str, tuple[str | None, str]] = {}

        if not ids:
            return

        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
        from apps.core.rbac import EdifyRole

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
            supervisee_id__in=staff_ids,
            supervisor__user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
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
        # A few hundred people own every row of a country page, so each one's
        # lead is worked out once rather than once per row.
        lead = self._leads.get(staff_id)
        if lead is None:
            lead = self._leads[staff_id] = self._lead_of(staff_id)
        return lead

    def _lead_of(self, staff_id) -> tuple[str | None, str]:
        if not staff_id:
            return None, ""
        canonical = self._staff_for.get(staff_id, staff_id)
        from apps.core.rbac import EdifyRole

        if (
            self._roles.get(canonical) == EdifyRole.COUNTRY_PROGRAM_LEAD.value
            or self._roles.get(staff_id) == EdifyRole.COUNTRY_PROGRAM_LEAD.value
        ):
            return canonical, self._names.get(canonical, "")
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
    # partner, and not whoever happened to hand it over. Rows that predate the
    # partner-handoff fix never had a monitor stamped; for those the school's
    # responsible CCEO is that person, so their partner-delivered plan items
    # stay on their oversight tab (and in their fund plan) instead of falling
    # off every member's tab.
    owner_id = (
        (activity.monitored_by_staff_id or activity.responsible_staff_id)
        if is_partner
        else (activity.responsible_staff_id or activity.monitored_by_staff_id)
    )
    supervising_pl_id, supervising_pl_name = directory.supervisor_of(owner_id)

    is_in_school = bool(
        activity.paired_school_visit_id
        or activity.activity_type == "in_school_training"
        or getattr(activity, "delivery_type", "") == "in-school"
    )
    raw_cost = int(costs.get(activity.id, 0))
    planned_cost = 0 if is_in_school else raw_cost
    budget = raw_cost
    cluster_planned_from = (
        "School Visit"
        if is_in_school
        else (getattr(activity.cluster, "name", "") or "—")
    )
    delivery_type_str = "in-school" if is_in_school else "group"
    participants_count = int(
        activity.participants_per_school or activity.expected_participants or 0
    )
    is_training = (
        activity.activity_type in TRAINING_TYPES
        or "training" in str(activity.activity_type or "").lower()
        or is_in_school
        or bool(getattr(activity, "training_course_id", None))
    )
    if is_training:
        training_name_str = (
            getattr(activity.training_course, "display_name", "")
            or getattr(activity.training_course, "source_name", "")
            or getattr(activity, "activity_name_snapshot", "")
            or activity.activity_type.replace("_", " ").title()
        )
    else:
        training_name_str = "—"
    purpose_label = (
        visit_purpose_label(activity.purpose_type, fallback="")
        if activity.purpose_type
        else ""
    )
    visit_purpose = (
        activity.activity_purpose_text
        or purpose_label
        or activity.support_rationale
        or activity.purpose_intervention
        or "—"
    )

    geo = _geography_of(activity.school if activity.school_id else None)
    if (
        not geo.get("district_name")
        and activity.cluster
        and getattr(activity.cluster, "district", None)
    ):
        geo["district_id"] = activity.cluster.district_id
        geo["district_name"] = getattr(activity.cluster.district, "name", "") or ""
        if getattr(activity.cluster.district, "region", None):
            geo["region_name"] = (
                getattr(activity.cluster.district.region, "name", "") or ""
            )

    item = PlanningOversightItem(
        stage=STAGE_PARTNER_SCHEDULED if is_partner else STAGE_STAFF_SCHEDULED,
        activity_id=activity.id,
        school_id=activity.school_id,
        school_code=getattr(activity.school, "school_id", "")
        or activity.school_id
        or "—",
        school_name=getattr(activity.school, "name", "") or "",
        school_type=getattr(activity.school, "school_type", "") or "",
        **geo,
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
        purpose_of_visit=visit_purpose,
        training_name=training_name_str,
        participants=participants_count,
        delivery_type=delivery_type_str,
        cluster_planned_from=cluster_planned_from,
        budget=budget,
        is_in_school_training=is_in_school,
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
        submitted_to_ia_at=(
            activity.submitted_to_ia_at.date() if activity.submitted_to_ia_at else None
        ),
        planned_cost=planned_cost,
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

    geo_assign = _geography_of(assignment.school if assignment.school_id else None)
    if (
        not geo_assign.get("district_name")
        and assignment.cluster
        and getattr(assignment.cluster, "district", None)
    ):
        geo_assign["district_id"] = assignment.cluster.district_id
        geo_assign["district_name"] = (
            getattr(assignment.cluster.district, "name", "") or ""
        )
        if getattr(assignment.cluster.district, "region", None):
            geo_assign["region_name"] = (
                getattr(assignment.cluster.district.region, "name", "") or ""
            )

    return PlanningOversightItem(
        stage=STAGE_PARTNER_AWAITING_SCHEDULE,
        partner_assignment_id=assignment.id,
        school_id=assignment.school_id,
        school_code=getattr(assignment.school, "school_id", "")
        or assignment.school_id
        or "—",
        school_name=getattr(assignment.school, "name", "") or "",
        school_type=getattr(assignment.school, "school_type", "") or "",
        **geo_assign,
        cluster_id=assignment.cluster_id,
        cluster_name=getattr(assignment.cluster, "name", "") or "",
        project_id=assignment.project_id,
        activity_type=assignment.expected_activity_type or "",
        target_intervention=assignment.focus_intervention or "",
        operational_rationale=(
            assignment.purpose_of_visit or assignment.purpose or assignment.notes or ""
        ),
        purpose_of_visit=(
            (
                visit_purpose_label(assignment.purpose_of_visit, fallback="")
                if assignment.purpose_of_visit
                else ""
            )
            or assignment.purpose_of_visit
            or assignment.purpose
            or assignment.notes
            or "—"
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


def _geography_of(school) -> dict:
    """District and region names for an item, read off the school's FKs.

    `district_id` was declared in FILTER_KEYS for a long time and read by
    nobody: the item carried no geography, so the country plan could only be
    grouped by Program Lead.
    """
    if school is None:
        return {}
    district = getattr(school, "district", None)
    region = getattr(school, "region", None)
    return {
        "district_id": getattr(school, "district_id", None),
        "district_name": getattr(district, "name", "") or "",
        "region_name": getattr(region, "name", "") or "",
    }


def apply_filters(items, filters: dict | None):
    """Narrow the items by the advanced filter drawer's selections."""
    if not filters:
        return items

    def keep(item) -> bool:
        if (want := filters.get("district_id")) and item.district_id != want:
            return False
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
    It is one pass: a country page folds 74,000 items per summary, and a list
    per count read each of them a dozen times (2026-09-24 audit).
    """
    # Execution progress counts only work whose date has arrived. Future work
    # is not late, and counting it as unfinished would report every team as
    # behind on the first day of a period.
    today = date.today()
    total = staff = awaiting = partner = at_risk = completed = budget = 0
    due = completed_due = cost_missing = awaiting_verification = unpaid = 0
    for i in items:
        total += 1
        budget += i.planned_cost
        is_completed = i.is_completed
        if is_completed:
            completed += 1
        if i.is_awaiting_partner_schedule:
            awaiting += 1
        if i.stage in (STAGE_STAFF_SCHEDULED, STAGE_PARTNER_SCHEDULED):
            if i.stage == STAGE_STAFF_SCHEDULED:
                staff += 1
            else:
                partner += 1
            if i.cost_missing:
                cost_missing += 1
            if i.planned_date and i.planned_date <= today:
                due += 1
                if is_completed:
                    completed_due += 1
        if i.at_risk:
            at_risk += 1
        # The tail of the chain. Folded from the same items, so these agree
        # with the rows like every other number here. They exist because a
        # plan that is 100% delivered and 0% verified is not a finished plan,
        # and a page that stops at "completed" says it is.
        if i.submitted_to_ia_at and i.ia_status == "pending":
            awaiting_verification += 1
        if i.ia_status == "confirmed" and (i.finance_status or "none") not in (
            "paid",
            "disbursed",
            "netsuite_accountability",
            "closed",
            "rejected",
        ):
            unpaid += 1

    return {
        "total_planned": total,
        "staff_scheduled": staff,
        "partner_awaiting_schedule": awaiting,
        "partner_scheduled": partner,
        "scheduled_total": staff + partner,
        "at_risk": at_risk,
        "needs_attention": at_risk,
        "planned_budget": budget,
        "completed": completed,
        "due_count": due,
        "execution_progress": round(completed_due * 100 / due) if due else None,
        "cost_missing": cost_missing,
        "awaiting_verification": awaiting_verification,
        "awaiting_payment": unpaid,
    }


#: The three kinds of planned work a Programme Lead reads separately (owner,
#: 2026-09-17: "a table for planned school visits, a separate table for planned
#: cluster meeting and a separate table for planned group training ... grouped
#: by CCEOs in tabs"). A school visit, a cluster convening and a group training
#: are planned differently, cost differently and are read for different
#: questions, and mixing them in one table made a lead scan for the rows that
#: answered the question they actually had.
ACTIVITY_FAMILIES: tuple[tuple[str, str, frozenset], ...] = (
    ("visits", "School Visits", frozenset(VISIT_TYPES)),
    ("meetings", "Cluster Meetings", frozenset(CLUSTER_MEETING_TYPES)),
    ("trainings", "Group Trainings", frozenset(TRAINING_TYPES)),
)
_FAMILY_TYPES = {key: types for key, _label, types in ACTIVITY_FAMILIES}


def in_family(items, family: str) -> list:
    """The items of one family, or every item for an unknown key.

    "all" is not a fourth family, it is the absence of one — and it is the
    default on purpose. A programme event, an SSA activity or a partner
    activity belongs to none of the three, so a page that only ever showed
    the three would quietly drop work from a lead's team.
    """
    types = _FAMILY_TYPES.get(family)
    if not types:
        return list(items)
    return [item for item in items if item.activity_type in types]


def activity_tabs(items, active: str) -> list[dict]:
    """The family strip, each tab carrying the count it will show.

    Counted from the items themselves so a tab and its table cannot disagree,
    the same reason `summarize` is a fold rather than a query.
    """
    items = list(items)
    tabs = [
        {
            "key": "all",
            "label": "All Activities",
            "count": len(items),
            "is_active": active not in _FAMILY_TYPES,
        }
    ]
    for key, label, types in ACTIVITY_FAMILIES:
        tabs.append(
            {
                "key": key,
                "label": label,
                "count": len([i for i in items if i.activity_type in types]),
                "is_active": key == active,
            }
        )
    return tabs


def program_lead_members(program_lead_id) -> list[dict]:
    """The lead and their complete reporting roster, independent of activity dates."""
    return program_lead_rosters([program_lead_id]).get(str(program_lead_id), [])


def program_lead_rosters(program_lead_ids) -> dict[str, list[dict]]:
    """`program_lead_members` for many leads at once, in two queries.

    Keyed by the id each lead was asked for (StaffProfile or User id). An id
    that is not a Programme Lead has no entry. Each roster is the lead first,
    then everyone with a supervisor link to them, by name.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
    from apps.core.rbac import EdifyRole

    wanted = {str(i) for i in program_lead_ids if i}
    if not wanted:
        return {}
    lead_for: dict[str, StaffProfile] = {}
    for lead in (
        StaffProfile.objects.filter(
            Q(id__in=wanted) | Q(user_id__in=wanted),
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        .select_related("user")
        .order_by("pk")
    ):
        for key in (lead.id, lead.user_id):
            if key in wanted:
                lead_for.setdefault(key, lead)
    if not lead_for:
        return {}
    members: dict[str, list] = {}
    for link in (
        StaffSupervisorAssignment.objects.filter(
            supervisor_id__in={lead.id for lead in lead_for.values()}
        )
        .exclude(supervisee_id=F("supervisor_id"))
        .select_related("supervisee__user")
        .order_by("supervisee__user__name", "supervisee_id")
    ):
        members.setdefault(link.supervisor_id, []).append(link.supervisee)

    def entry(p):
        return {
            "id": p.id,
            "name": p.user.name or p.user.email,
            "ids": {p.id, p.user_id},
        }

    return {
        key: [entry(p) for p in [lead, *members.get(lead.id, [])]]
        for key, lead in lead_for.items()
    }


def _canonical_staff_ids(ids) -> dict[str, str]:
    """Each id mapped to the StaffProfile id of the person it names.

    `operational_owner_id` is whatever `Activity.responsible_staff_id` held —
    a StaffProfile id from `activities.services.create`, a User id from older
    paths — so grouping on it raw filed one person under two tabs of the same
    name, each holding part of their plan (owner, 2026-09-24: oversight must
    mirror each person's My Plan, which reads both id spaces as one person).
    One query; an id naming no profile maps to itself.
    """
    from apps.accounts.models import StaffProfile

    wanted = {str(i) for i in ids if i}
    if not wanted:
        return {}
    canonical = {i: i for i in wanted}
    for staff_id, user_id in StaffProfile.objects.filter(
        Q(id__in=wanted) | Q(user_id__in=wanted)
    ).values_list("id", "user_id"):
        for key in (staff_id, user_id):
            if key and str(key) in wanted:
                canonical[str(key)] = staff_id
    return canonical


def _group_by_person(items) -> list[dict]:
    """`_group` by owner, with both id spaces folded into one person."""
    canonical = _canonical_staff_ids(i.operational_owner_id for i in items)
    names: dict[str, str] = {}
    for item in items:
        key = canonical.get(str(item.operational_owner_id or ""))
        if key and item.operational_owner_name:
            names.setdefault(key, item.operational_owner_name)

    def person(item):
        key = canonical.get(str(item.operational_owner_id or ""))
        return key, names.get(key, item.operational_owner_name)

    return _group(items, key=person)


def group_by_owner(items, *, owners=None) -> list[dict]:
    """Group work by owner; a supplied roster also shows members with no work.

    Either way one person is one group, whichever id space wrote their work.
    """
    if owners is None:
        return _group_by_person(items)
    groups = [{"id": p["id"], "name": p["name"], "items": []} for p in owners]
    lookup = {
        str(owner_id): group
        for p, group in zip(owners, groups)
        for owner_id in p["ids"]
        if owner_id
    }
    remaining = []
    for item in items:
        group = lookup.get(str(item.operational_owner_id or ""))
        if group is None:
            remaining.append(item)
        else:
            group["items"].append(item)
    # Preserve historical or unassigned owners whose scoped work is still visible.
    groups.extend(_group_by_person(remaining))
    for index, group in enumerate(groups, start=1):
        group["summary"] = summarize(group["items"])
        group["page_param"] = f"g{index}_page"
    return groups


def system_program_leads() -> list[dict]:
    """All staff with the Program Lead role, from the role system.

    This is the source of truth for PL tabs on the Country Oversight page.
    PLs are defined by their role, not inferred from activity supervisor links.
    A PL with zero activities still appears; the IA never does.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.rbac import EdifyRole

    profiles = list(
        StaffProfile.objects.filter(
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        .select_related("user")
        .order_by("user__name")
    )
    id_spaces = _each_in_both_id_spaces(p.id for p in profiles)
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "name": getattr(p.user, "name", "") or getattr(p.user, "email", ""),
            "ids": id_spaces.get(p.id, set()),
        }
        for p in profiles
    ]


def _each_in_both_id_spaces(staff_ids) -> dict[str, set[str]]:
    """`_both_id_spaces` of each id on its own, in two queries for all of them.

    Asking one id at a time cost two queries per Programme Lead on every
    country and cluster oversight load.
    """
    from apps.accounts.models import StaffProfile

    ids = {i for i in staff_ids if i}
    spaces = {i: {i} for i in ids}
    if not ids:
        return spaces
    for staff_id, user_id in StaffProfile.objects.filter(id__in=ids).values_list(
        "id", "user_id"
    ):
        if user_id:
            spaces[staff_id].add(user_id)
    for staff_id, user_id in StaffProfile.objects.filter(user_id__in=ids).values_list(
        "id", "user_id"
    ):
        if staff_id:
            spaces[user_id].add(staff_id)
    return spaces


def group_by_program_lead(items, *, program_leads=None) -> list[dict]:
    """Items folded per Program Lead — from the system's role assignments.

    When *program_leads* is supplied (the top-down list from
    ``system_program_leads``), every PL gets a group whether or not they have
    items in the current period, and items are attributed by the PL id stamped
    on the item by the supervisor link.  Items whose owner has no PL supervisor
    fall to an "Unassigned" group at the end.

    Without *program_leads* the old bottom-up grouping is used (backward
    compatible for call-sites that have not been updated).
    """
    if program_leads is None:
        # Fallback: bottom-up grouping from item data.
        return _group(items, key=lambda i: (i.supervising_pl_id, i.supervising_pl_name))

    # Build PL-id → group mapping from the system PLs.
    pl_lookup: dict[str, dict] = {}
    groups: list[dict] = []
    for pl in program_leads:
        group: dict = {"id": pl["id"], "name": pl["name"], "items": []}
        groups.append(group)
        for pid in pl["ids"]:
            pl_lookup[pid] = group

    unassigned: dict = {"id": None, "name": "Unassigned", "items": []}

    for item in items:
        target = (
            pl_lookup.get(item.supervising_pl_id) if item.supervising_pl_id else None
        )
        if target is not None:
            target["items"].append(item)
        else:
            unassigned["items"].append(item)

    # Summarise each group (including empty ones — the template shows "0 planned").
    for group in groups:
        group["summary"] = summarize(group["items"])

    if unassigned["items"]:
        unassigned["summary"] = summarize(unassigned["items"])
        groups.append(unassigned)

    for index, group in enumerate(groups, start=1):
        group["page_param"] = f"g{index}_page"

    return groups


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
    # Each group's table pages independently, so paging one person's work does
    # not move everybody else's. The key is positional rather than the owner id
    # because it ends up in a URL, and an id there would leak who is on the
    # page to anyone the link is forwarded to.
    for index, group in enumerate(groups, start=1):
        group["page_param"] = f"g{index}_page"
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
