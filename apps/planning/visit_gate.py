"""What a school's visits add up to this year — one answer for every button.

Owner, 2026-09-21:

  "can you lift restriction to school visits especially client school visit.
  All restrictions. right now it is restricting returning error and not
  scheduling."

So the CLIENT school's allowance no longer refuses anything. It is still
counted — that is what the pages show — but the count stopped being a
permission, and the buttons that used to grey out of it stay live.

The CORE package is not part of that. Its 2 + 2 split rests on the owner's
own later instruction (2026-09-17) and is enforced half here and half in
`core_planning_services.assert_can_schedule`, which delegates the partner
side to this module; the two must agree or a Core Schools row offers what
the POST refuses. `_decide` marks which half is which.

Owner, 2026-09-21:

  "Core trained, core graduate and Champion Schools can receive all the
  activities (visit, trainings) client schools should receive but cannot be
  assigned to partner."

So those three sit on the client rule beside ``client`` itself — the same
purposes, and the same allowance, now counted rather than enforced — and the
partner side of the gate is closed for them whatever the counts say. They are
listed in ``PROGRAMME_SCHOOL_TYPES`` and the Programme Schools page is the
list of them.

What counts, and is still read by the Planning, Cluster, Core Schools and
Partner pages:

* Client-rule schools (``client`` and the three Programme types): the
  follow-up visit
  — a support visit to the school in the operational fiscal year, whoever
  delivers it. Donor visits, story gathering, invitations and social visits
  are not it; neither is an in-school training, nor the companion visit the
  training pair creates, nor an in-school coaching visit. A catalogue item the
  CD has taken out of the entitlement (its rule's counts_toward_entitlement
  off) does not count. ``partner_pending`` names a live partner assignment
  nobody has scheduled yet — which is worth SAYING on the row, and no longer
  closes the school to staff.
* Core schools: ``core_visit`` activities in the fiscal year, split by
  ``delivery_type``, beside the package's trainings. Staff may hold two and
  the partner side (scheduled partner visits plus visit slots assigned to a
  partner and not yet scheduled) may hold two. These are the halves of the
  package's four visits, and the same two the core scheduling service caps
  at. Trainings are not visits: the Core Schools row keeps its own Training
  entry open while staff trainings remain.

Two answers per side, because a row button and a purpose inside a drawer are
gated differently: ``staff_can_schedule`` says whether the visit itself may be
scheduled (the purpose in the drawer, the core-visit option, the core row's
Schedule button); ``staff_locked`` says whether the whole Schedule button on a
Planning or cluster row is off. Likewise ``can_assign_partner`` (the Assign
button) and ``can_assign_visit`` (the visit purposes in the assign drawer). On
a client school all four are now always open, with an empty reason, so the
templates render a live button and no tooltip.

"Live" excludes cancelled, rejected, deferred and not-planned work, which is
what every other counter here excludes. A completed visit still counts: the
school has been visited this year.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.db.models import Count

# The shape of a year's support, as the pages display it — "1/2 visits" on a
# Core Schools row, "2 of 2" beside a client school.
#
# CLIENT_VISIT_CAP is display only since 2026-09-21: it was the figure the
# gate refused past (one visit a year until 2026-09-17, two after it), and it
# is kept named, at the owner's number, because a count shown without the
# figure it is counted against says nothing.
#
# The two CORE caps are still enforced — the package's halves, which the lift
# did not touch. See `_decide`.
CLIENT_VISIT_CAP = 2
CORE_STAFF_VISIT_CAP = 2
CORE_PARTNER_VISIT_CAP = 2

# School types under the once-a-year client rule. Core schools carry the
# package.
#
# Owner, 2026-09-21: Core Trained, Core Graduate and Champion schools "can
# receive all the activities (visit, trainings) client schools should receive
# but cannot be assigned to partner". So all three sit on the client rule —
# the same two visits a year, the same purposes, the same trainings — and
# PROGRAMME_SCHOOL_TYPES below withholds partner delivery from them. Champion
# and Core Graduate were on no rule at all before, which read as an unlimited
# entitlement rather than a deliberate one.
PROGRAMME_SCHOOL_TYPES = ("core_trained", "core_graduate", "champion")
CLIENT_RULE_SCHOOL_TYPES = ("client", *PROGRAMME_SCHOOL_TYPES)
CORE_RULE_SCHOOL_TYPES = ("core",)

DEAD_STATUSES = ("cancelled", "rejected", "deferred", "not_planned")
# A visit request a country role has filed and the owner has not decided on
# (apps.planning.visit_requests) is not a plan yet: it neither uses the
# school's visit nor is refused by the rule. Approval is where it is checked.
NOT_YET_PLANNED_STATUSES = ("awaiting_owner_approval",)


@dataclass
class VisitGate:
    school_id: str
    school_name: str
    school_type: str
    fy: str
    rule: str = "none"  # "client" | "core" | "none"
    staff_visits: int = 0
    partner_visits: int = 0
    partner_pending: int = 0
    partner_name: str = ""
    staff_can_schedule: bool = True
    staff_reason: str = ""
    staff_locked: bool = False
    staff_locked_reason: str = ""
    partner_can_schedule: bool = True
    partner_reason: str = ""
    can_assign_partner: bool = True
    assign_reason: str = ""
    can_assign_visit: bool = True
    assign_visit_reason: str = ""
    staff_cap: int = 0
    partner_cap: int = 0
    # Core only: the training half of the package, tallied the same way so
    # the Core Schools row can tell when a side has nothing left to do.
    staff_trainings: int = 0
    partner_trainings: int = 0
    partner_pending_trainings: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def total_visits(self) -> int:
        return self.staff_visits + self.partner_visits

    @property
    def partner_held_visits(self) -> int:
        return self.partner_visits + self.partner_pending

    @property
    def staff_trainings_open(self) -> bool:
        """Core only: staff still have one of their two trainings to give.

        The package's halves are not part of the 2026-09-21 lift — see
        `_decide` — and `core_planning_services.assert_can_schedule` caps
        staff trainings at the same figure, so this has to agree with it or
        the row offers an entry the POST refuses.
        """
        return self.rule == "core" and self.staff_trainings < CORE_STAFF_VISIT_CAP

    def as_dict(self) -> dict:
        data = asdict(self)
        data["total_visits"] = self.total_visits
        data["partner_held_visits"] = self.partner_held_visits
        data["staff_trainings_open"] = self.staff_trainings_open
        return data


# The follow-up visit: the support visits that use a client school's one
# visit a year. Donor, social, story-gathering and invitation visits do not;
# nor does an in-school coaching visit (in-school work is allowed) or the
# core package's own visits.
FOLLOW_UP_VISIT_TYPES = (
    "school_visit",
    "follow_up_visit",
    "training_follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
)
# The visit the in-school training pair creates beside the training: one
# mission, recorded twice for Salesforce. It is the training, not a visit.
COMPANION_VISIT_PURPOSE = "in_school_training_delivery_visit"

# Purposes in the schedule and assign drawers that ARE the follow-up visit.
FOLLOW_UP_PURPOSES = ("training_follow_up", "ssa_support")


def _client_visit_q():
    from django.db.models import Q

    from apps.activities.services import client_entitlement_consumers_q

    return Q(activity_type__in=FOLLOW_UP_VISIT_TYPES) | client_entitlement_consumers_q(
        "visit"
    )


def _exempt_by_rule(catalogue_item) -> bool:
    """The eligibility rule's counts_toward_entitlement is the governance
    exemption switch: an item the CD has taken out of the entitlement neither
    consumes the year's visit nor is refused by it."""
    if catalogue_item is None or not getattr(
        catalogue_item, "counts_toward_client_visit", False
    ):
        return False
    try:
        rule = catalogue_item.eligibility_rule
    except Exception:
        return False
    return not getattr(rule, "counts_toward_entitlement", True)


def consumes_client_visit(
    activity_type: str, catalogue_item=None, purpose_type: str | None = None
) -> bool:
    """Does an activity of this shape count as the client school's visit?
    Mirrors ``_client_visit_q`` for a row that does not exist yet."""
    if purpose_type == COMPANION_VISIT_PURPOSE or _exempt_by_rule(catalogue_item):
        return False
    if catalogue_item is not None and getattr(
        catalogue_item, "counts_toward_client_visit", False
    ):
        return True
    return activity_type in FOLLOW_UP_VISIT_TYPES


def is_gated_visit(
    rule: str, activity_type: str, catalogue_item=None, purpose_type=None
) -> bool:
    """Is an activity of this shape the kind of visit the rule counts?"""
    if rule == "core":
        return activity_type == "core_visit"
    if rule == "client":
        return consumes_client_visit(activity_type, catalogue_item, purpose_type)
    return False


def rule_for(school_type: str | None) -> str:
    if school_type in CORE_RULE_SCHOOL_TYPES:
        return "core"
    if school_type in CLIENT_RULE_SCHOOL_TYPES:
        return "client"
    return "none"


def visit_gates(
    schools, fy: str | None = None, *, exclude_activity_id: str | None = None
) -> dict[str, VisitGate]:
    """Gates for many schools in a bounded number of queries, keyed by
    ``School.id``. ``schools`` is any iterable of School rows (id, name,
    school_type are read). ``exclude_activity_id`` leaves one activity out of
    the count — the one being rescheduled, which must not block itself."""
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.partners.models import PartnerAssignment

    fy = str(fy or get_operational_fy())
    rows = list(schools)
    gates = {
        s.id: VisitGate(
            school_id=s.id,
            school_name=s.name,
            school_type=s.school_type,
            fy=fy,
            rule=rule_for(s.school_type),
        )
        for s in rows
    }
    client_ids = [sid for sid, g in gates.items() if g.rule == "client"]
    core_ids = [sid for sid, g in gates.items() if g.rule == "core"]
    if not client_ids and not core_ids:
        return gates

    live = Activity.objects.filter(fy=fy, deleted_at__isnull=True).exclude(
        status__in=DEAD_STATUSES + NOT_YET_PLANNED_STATUSES
    )
    if exclude_activity_id:
        live = live.exclude(id=exclude_activity_id)

    def _tally(qs, staff_attr, partner_attr):
        for row in qs.values("school_id", "delivery_type").annotate(n=Count("id")):
            gate = gates[row["school_id"]]
            attr = partner_attr if row["delivery_type"] == "partner" else staff_attr
            setattr(gate, attr, getattr(gate, attr) + row["n"])

    if client_ids:
        _tally(
            live.filter(school_id__in=client_ids)
            .filter(_client_visit_q())
            .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
            .exclude(
                catalogue_item__counts_toward_client_visit=True,
                catalogue_item__eligibility_rule__counts_toward_entitlement=False,
            ),
            "staff_visits",
            "partner_visits",
        )
    if core_ids:
        from apps.core_schools.core_planning_services import core_training_q

        _tally(
            live.filter(school_id__in=core_ids, activity_type="core_visit"),
            "staff_visits",
            "partner_visits",
        )
        _tally(
            live.filter(school_id__in=core_ids).filter(core_training_q()),
            "staff_trainings",
            "partner_trainings",
        )

    # Partner assignments still waiting on the partner. A returned or
    # scheduled one is not pending: the scheduled one is counted above as
    # the partner's activity, the returned one has let the school go.
    pending = (
        PartnerAssignment.objects.filter(
            school_id__in=client_ids + core_ids,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        )
        .select_related("partner")
        .order_by("created_at")
    )
    for assignment in pending:
        gate = gates[assignment.school_id]
        if gate.rule == "core" and not _is_core_visit_assignment(assignment):
            if _is_core_training_assignment(assignment):
                gate.partner_pending_trainings += 1
            continue
        gate.partner_pending += 1
        if not gate.partner_name and assignment.partner_id:
            gate.partner_name = assignment.partner.name

    for gate in gates.values():
        _decide(gate)
    return gates


def _is_core_visit_assignment(assignment) -> bool:
    support = (assignment.support_type or "").strip().lower()
    if support:
        return support == "visit"
    return bool(assignment.visit_number)


def _is_core_training_assignment(assignment) -> bool:
    support = (assignment.support_type or "").strip().lower()
    if support:
        return support == "training"
    return bool(assignment.training_number)


def visit_gate(school, fy: str | None = None, **kwargs) -> VisitGate:
    return visit_gates([school], fy, **kwargs)[school.id]


def programme_school_partner_refusal(school_name: str, school_type: str) -> str:
    """The refusal, in one voice: the greyed control, the drawer and the
    partner creation door all say this same sentence."""
    from apps.core.enums import SchoolType

    label = dict(SchoolType.choices).get(school_type, "Programme")
    return (
        f"{school_name} is a {label} school. Edify staff deliver its visits "
        "and trainings themselves; it is never assigned to a partner."
    )


def _decide(gate: VisitGate) -> None:
    """Fill in the shape of the year's support, and say what is still refused.

    Owner, 2026-09-21: "can you lift restriction to school visits especially
    client school visit. All restrictions. right now it is restricting
    returning error and not scheduling."

    So on the CLIENT rule this refuses nothing. What it used to do there, and
    no longer does:

    * the follow-up visit was capped at CLIENT_VISIT_CAP a year across staff
      and partner together, and the cap greyed the purpose in the drawer and
      refused the POST behind it;
    * a live partner assignment locked the school away from staff entirely
      until the partner returned it.

    The counting stays, because it is what the pages SHOW: the row reads
    "2 of 2" and names the partner holding a school. A count is information;
    on that rule it stopped being a permission.

    Two things are still refused, and neither is part of that lift. The CORE
    package keeps its halves — see the branch below. And a Programme school
    (core trained, core graduate, champion) is never a partner's work, which
    is applied here, after the rule, so a rule's own sentence about a spent
    entitlement cannot overwrite it.
    """
    _decide_by_rule(gate)
    if gate.school_type in PROGRAMME_SCHOOL_TYPES:
        refusal = programme_school_partner_refusal(gate.school_name, gate.school_type)
        gate.partner_can_schedule = False
        gate.partner_reason = refusal
        gate.can_assign_partner = False
        gate.assign_reason = refusal
        gate.can_assign_visit = False
        gate.assign_visit_reason = refusal
        gate.partner_cap = 0


def _decide_by_rule(gate: VisitGate) -> None:
    if gate.rule == "client":
        gate.staff_cap = CLIENT_VISIT_CAP
        gate.partner_cap = CLIENT_VISIT_CAP
        return

    if gate.rule == "core":
        # The core package's 2 + 2 split is NOT part of the lift, and stands
        # on the owner's own later instruction (2026-09-17, quoted in
        # `core_planning_services.assert_can_schedule`): "Lift all FY
        # restriction and package restrictions. Only block staff visit
        # schedule after 2 scheduling and block partner assignment and
        # schedule after 2 assignment and scheduling."
        #
        # That service enforces the staff half itself and delegates the
        # partner half here, so dropping these would have removed the partner
        # cap outright and left a Core Schools row offering a Schedule button
        # the staff cap then refused. The client school's allowance is what
        # 2026-09-21 lifted; the package is a funded 4 + 4 and keeps its
        # halves.
        gate.staff_cap = CORE_STAFF_VISIT_CAP
        gate.partner_cap = CORE_PARTNER_VISIT_CAP
        if gate.staff_visits >= CORE_STAFF_VISIT_CAP:
            gate.staff_can_schedule = False
            gate.staff_reason = (
                f"Staff core visits complete for FY{gate.fy} "
                f"({gate.staff_visits}/{CORE_STAFF_VISIT_CAP}). The remaining "
                "visits belong to the partner."
            )
        partner_held = gate.partner_held_visits
        if gate.partner_visits >= CORE_PARTNER_VISIT_CAP:
            gate.partner_can_schedule = False
            gate.partner_reason = (
                f"Partner core visits complete for FY{gate.fy} "
                f"({gate.partner_visits}/{CORE_PARTNER_VISIT_CAP})."
            )
        if partner_held >= CORE_PARTNER_VISIT_CAP:
            gate.can_assign_partner = False
            gate.can_assign_visit = False
            gate.assign_reason = gate.assign_visit_reason = (
                f"Partner core visits already assigned for FY{gate.fy} "
                f"({partner_held}/{CORE_PARTNER_VISIT_CAP})."
            )
        return


def assert_staff_may_schedule_visit(school, fy=None, **kwargs) -> VisitGate:
    """The school's counts, and no refusal (owner, 2026-09-21).

    The three helpers below read the same always-open fields the buttons do,
    so they return the gate rather than raising. They are called from the
    scheduling services, the partner queue and the core package, and they stay
    because the gate they return is used there — and because a restriction the
    owner asks for again belongs at this seam, not spread back out.
    """
    from apps.core.exceptions import BadRequest

    gate = visit_gate(school, fy, **kwargs)
    if not gate.staff_can_schedule:
        raise BadRequest(gate.staff_reason)
    return gate


def assert_partner_may_schedule_visit(school, fy=None, **kwargs) -> VisitGate:
    from apps.core.exceptions import BadRequest

    gate = visit_gate(school, fy, **kwargs)
    if not gate.partner_can_schedule:
        raise BadRequest(gate.partner_reason)
    return gate


def assert_may_assign_partner_visit(school, fy=None, **kwargs) -> VisitGate:
    from apps.core.exceptions import BadRequest

    gate = visit_gate(school, fy, **kwargs)
    if not gate.can_assign_partner:
        raise BadRequest(gate.assign_reason)
    return gate
