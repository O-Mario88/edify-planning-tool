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


@dataclass
class PartnerOversightItem:
    """One school handed to a partner, at whatever point it has reached."""

    stage: str
    partner_assignment_id: str
    partner_activity_id: str | None = None

    # Who and where
    school_id: str | None = None
    school_name: str = ""
    school_type: str = ""
    district: str = ""
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
):
    """Every partner handover this principal may oversee, for the period.

    One bulk query per source. The partner group expansion on the page reuses
    this list rather than re-querying, so a group's numbers and its rows are
    the same rows.
    """
    from apps.partners.models import PartnerAssignment

    scope = _resolve_scope(principal)
    if scope["kind"] == "team" and not scope["staff_ids"]:
        return []

    qs = (
        PartnerAssignment.objects.select_related(
            "school", "school__district", "cluster", "partner", "scheduled_activity"
        ).filter(deleted_at__isnull=True)
        if _has_soft_delete()
        else PartnerAssignment.objects.select_related(
            "school", "school__district", "cluster", "partner", "scheduled_activity"
        )
    )
    if not scope["is_country"]:
        ids = scope["staff_ids"]
        # School ownership is the third arm, and it is not redundant.
        # `monitoring_staff_id` is nullable — every assignment written before
        # that column existed has none, and falls back to the *assigner*. So a
        # partner handed off by a PL to a CCEO's school resolves to the PL on
        # those older rows, and the CCEO who owns the school would open this
        # page to a blank list. Owning the school is the durable claim: it does
        # not depend on who clicked Handoff or on when the row was written.
        qs = qs.filter(
            Q(monitoring_staff_id__in=ids)
            | Q(assigning_staff_id__in=ids)
            | Q(school__account_owner_id__in=ids)
        )
    if partner_id:
        qs = qs.filter(partner_id=partner_id)

    assignments = list(qs)
    if fy:
        from apps.core.fy import get_operational_fy

        assignments = [
            a for a in assignments if _assignment_fy(a, get_operational_fy) == fy
        ]

    activity_ids = [
        a.scheduled_activity_id for a in assignments if a.scheduled_activity_id
    ]
    costs = _cost_by_activity(activity_ids)
    directory = _staff_directory(assignments)

    items = [_item_for(a, costs, directory) for a in assignments]
    items += _unassigned_partner_activities(
        scope, fy=fy, partner_id=partner_id, already=set(activity_ids)
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
        items = [i for i in items if i.supervising_pl_id in wanted]

    from apps.planning import partner_risk_service

    partner_risk_service.annotate(items)
    items.sort(key=lambda i: (i.partner_name, i.school_name))
    return items


def _unassigned_partner_activities(
    scope, *, fy: str, partner_id, already: set
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
        .select_related("school", "school__district", "cluster")
    )
    if fy:
        qs = qs.filter(fy=fy)
    if partner_id:
        qs = qs.filter(assigned_partner_id=partner_id)
    if already:
        qs = qs.exclude(id__in=already)
    if not scope["is_country"]:
        ids = scope["staff_ids"]
        qs = qs.filter(
            Q(monitored_by_staff_id__in=ids)
            | Q(responsible_staff_id__in=ids)
            | Q(school__account_owner_id__in=ids)
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

    items = []
    for activity in activities:
        entry = costs.get(activity.id)
        cost, catalogue_id, catalogue_version = entry if entry else (0, None, None)
        item = PartnerOversightItem(
            stage=STAGE_SCHEDULED if activity.planned_date else STAGE_AWAITING_SCHEDULE,
            partner_assignment_id="",
            partner_activity_id=activity.id,
            school_id=activity.school_id,
            school_name=getattr(activity.school, "name", "") or "",
            school_type=getattr(activity.school, "school_type", "") or "",
            district=getattr(getattr(activity.school, "district", None), "name", "")
            or "",
            cluster_name=getattr(activity.cluster, "name", "") or "",
            partner_id=activity.assigned_partner_id,
            partner_name=names.get(activity.assigned_partner_id, ""),
            responsible_cceo_id=activity.monitored_by_staff_id
            or activity.responsible_staff_id,
            activity_type=activity.activity_type or "",
            target_intervention=activity.focus_intervention or "",
            scheduled_date=activity.planned_date,
            month=activity.planned_month,
            quarter=activity.quarter or "",
            financial_year=activity.fy or "",
            activity_status=activity.status,
            evidence_status=activity.evidence_status or "",
            ia_status=activity.ia_verification_status or "",
            payment_status=activity.payment_status or "",
            planned_cost=cost,
            cost_catalogue_id=catalogue_id,
            cost_catalogue_version=catalogue_version,
        )
        _set_next_action(item)
        items.append(item)
    return items


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
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import owner_ids, resolve_user_scope

    role = getattr(principal, "active_role", "") or ""
    # Country lens for the roles whose remit genuinely is the whole country.
    # Impact Assessment and the Accountant are included because their queues
    # already are country-wide — IA verifies every submission and the
    # Accountant pays every partner — so a team-shaped scope would resolve to
    # the empty set and hand them a blank page, which reads as "no partner work
    # is stuck" rather than "you were shown nothing".
    if role in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        EdifyRole.ADMIN.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.PROGRAM_ACCOUNTANT.value,
    ) or getattr(principal, "is_superuser", False):
        return {"kind": "country", "is_country": True, "staff_ids": set()}

    from apps.planning.oversight_service import _both_id_spaces

    scope = resolve_user_scope(principal)
    own = _both_id_spaces(set(owner_ids(principal)))
    supervised = _both_id_spaces(set(scope.supervised_staff_ids or []))
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
    ids.discard(None)
    ids.discard("")
    if not ids:
        return {"names": {}, "supervisor": {}, "canonical": {}}

    names, canonical = {}, {}
    profiles = StaffProfile.objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).select_related("user")
    for p in profiles:
        label = getattr(p.user, "name", "") or getattr(p.user, "email", "")
        for key in (p.id, p.user_id):
            if key:
                names[key] = label
                canonical[key] = p.id

    supervisor = {}
    links = StaffSupervisorAssignment.objects.filter(
        supervisee_id__in={p.id for p in profiles}
    ).select_related("supervisor__user")
    for link in links:
        user = getattr(link.supervisor, "user", None)
        supervisor[link.supervisee_id] = (
            link.supervisor_id,
            getattr(user, "name", "") or getattr(user, "email", "") or "",
        )
    return {"names": names, "supervisor": supervisor, "canonical": canonical}


def _item_for(assignment, costs, directory) -> PartnerOversightItem:
    from apps.partners.models import PartnerAssignment

    activity = assignment.scheduled_activity
    cceo_id = assignment.monitoring_staff_id or assignment.assigning_staff_id
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

    item = PartnerOversightItem(
        stage=stage,
        partner_assignment_id=assignment.id,
        partner_activity_id=getattr(activity, "id", None),
        school_id=assignment.school_id,
        school_name=getattr(assignment.school, "name", "") or "",
        school_type=getattr(assignment.school, "school_type", "") or "",
        district=getattr(getattr(assignment.school, "district", None), "name", "")
        or "",
        cluster_name=getattr(assignment.cluster, "name", "") or "",
        project_id=assignment.project_id,
        partner_id=assignment.partner_id,
        partner_name=getattr(assignment.partner, "name", "") or "",
        responsible_cceo_id=cceo_id,
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
        assignment_date=assignment.created_at.date() if assignment.created_at else None,
        schedule_by_date=assignment.scheduled_date,
        assignment_status=assignment.status,
        return_reason_category=assignment.return_reason_category or "",
        return_reason=assignment.return_reason or "",
        planned_cost=cost,
        cost_catalogue_id=catalogue_id,
        cost_catalogue_version=catalogue_version,
    )

    if activity is not None:
        item.scheduled_date = activity.planned_date
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
        PartnerAssignment.objects.select_related(
            "school", "school__district", "cluster", "partner", "scheduled_activity"
        ).filter(school_id=school_id)
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
        key=lambda i: (i.scheduled_date or i.assignment_date or date.min), reverse=True
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
        PartnerAssignment.objects.select_related(
            "school", "school__district", "cluster", "partner", "scheduled_activity"
        )
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
        "payment_pending": len(
            [
                i
                for i in scheduled
                if i.payment_status in ("", "none", "pending")
                and i.activity_status in _COMPLETE_STATUSES
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
        group["contact_person"] = partner.contact_person or ""
        group["phone"] = partner.phone or ""
        group["region_name"] = partner.region_name or ""
        group["intervention_label"] = partner.ssa_intervention_label or ""


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

    if not scope["is_country"]:
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
