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

* Client-rule schools (``client`` and the three Programme types), in two
  counts (owner, 2026-09-28): the support visit — a Training Follow Up or an
  In-school Training (or another support visit type) — and SSA Support, each
  in the operational fiscal year, whoever delivers it. Donor visits, story
  gathering, invitations and social visits are in neither; nor is the
  companion visit the training pair creates. A catalogue item the CD has
  taken out of the entitlement (its rule's counts_toward_entitlement off)
  does not count. ``partner_pending`` names a live partner assignment
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
# Owner, 2026-09-28: "lift all restrictions. the only restriction is for
# client schools to have one visit from the staff. treat core trained just
# like client schools." So CLIENT_STAFF_VISIT_CAP is enforced again — one
# staff support visit a year at a client-rule school — and it is the only
# cap the client rule has: partner visits are counted, never refused.
#
# The CORE package keeps one condition (owner, the same day): "staff may plan
# more core schools visits but only if the partner has not planned." Staff
# hold CORE_STAFF_VISIT_CAP visits while the partner has a core visit planned
# at the school; with none planned, staff may take the rest. The partner side
# and the trainings are no longer capped. See `_decide_by_rule`.
#
# Owner, later the same day, on what the one visit is: "other visits that are
# allowed for clients schools and core trained, core graduate after the
# support visits (follow up or in-school training) are SSA Support, Donor
# Visits, Content gathering. donor visits and content gathering can be
# scheduled as many as possible. no limit on those". Asked, the owner chose
# one support visit in total (a Training Follow Up or an In-school Training),
# one SSA Support a year counted apart from it, and no limit on social visits
# and invitations either.
CLIENT_STAFF_VISIT_CAP = 1
CLIENT_STAFF_SSA_VISIT_CAP = 1
#: The figure a client school's visits were once counted against. Kept for
#: the pages and reports that still name it; nothing refuses by it.
CLIENT_VISIT_CAP = CLIENT_STAFF_VISIT_CAP
CORE_STAFF_VISIT_CAP = 2
CORE_PARTNER_VISIT_CAP = 2
#: The package's four visits, which staff may fill alone while the partner
#: has planned none.
CORE_PACKAGE_VISITS = CORE_STAFF_VISIT_CAP + CORE_PARTNER_VISIT_CAP

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

# Owner, 2026-09-25, narrowing the 2026-09-21 rule for two of the three:
# Champion and Core Graduate schools "don't receive training, assessments, and
# the only visit they can be planned for are donor visits and content/story
# collection visit". They leave the Planning page and the cluster lists (and
# every cluster session's invitations) for their own tables on Core Schools.
# Core Trained stays on the client rule and is planned like a client school.
#
# Owner, 2026-09-28: Core Graduate now follows the client rule for its visits
# — the one support visit, SSA Support, and donor, story, invitation and
# social visits without limit. Champion keeps the donor/story-only rule. Both
# keep their own tables on Core Schools, off the Planning page and the
# cluster lists (OWN_TABLE_SCHOOL_TYPES); only where they are listed was not
# part of the change.
OWN_TABLE_SCHOOL_TYPES = ("champion", "core_graduate")
OUTREACH_ONLY_SCHOOL_TYPES = ("champion",)
OUTREACH_ACTIVITY_TYPES = ("donor_visit", "story_gathering_visit")
OUTREACH_VISIT_PURPOSES = ("donor_visit", "story_gathering")


def outreach_only_refusal(school_name: str, school_type: str) -> str:
    """The one sentence every refused Champion plan reads."""
    from apps.core.enums import SchoolType

    label = dict(SchoolType.choices).get(school_type, "Programme")
    return (
        f"{school_name} is a {label} school: it receives no training or "
        "assessment, and is planned only for a Donor Visit or a "
        "Content/Story Collection visit."
    )


def assert_outreach_activity_allowed(school, activity_type: str) -> None:
    """Refuse anything but a donor or story visit for a Champion school,
    wherever the plan comes from."""
    from apps.core.exceptions import BadRequest

    if school is None or school.school_type not in OUTREACH_ONLY_SCHOOL_TYPES:
        return
    if activity_type not in OUTREACH_ACTIVITY_TYPES:
        raise BadRequest(outreach_only_refusal(school.name, school.school_type))


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
    # Client rule only: SSA Support visits, counted apart from the support
    # visit (owner, 2026-09-28).
    staff_ssa_visits: int = 0
    partner_ssa_visits: int = 0
    partner_pending: int = 0
    partner_name: str = ""
    staff_can_schedule: bool = True
    staff_reason: str = ""
    ssa_can_schedule: bool = True
    ssa_reason: str = ""
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
    ssa_cap: int = 0
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
        """Core only: staff may schedule a core training.

        Always, since 2026-09-28 ("lift all restrictions"): the training cap
        went with the package's partner half. It stays a property so the Core
        Schools row and `core_planning_services.assert_can_schedule` keep
        asking one place.
        """
        return self.rule == "core"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["total_visits"] = self.total_visits
        data["partner_held_visits"] = self.partner_held_visits
        data["staff_trainings_open"] = self.staff_trainings_open
        return data


# The follow-up visit types: support visits to a school. Donor, social,
# story-gathering and invitation visits are not; nor are the core package's
# own visits. The duplicate-visit guard and the package credit read this
# list; the client rule's two counts are below it.
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

# The client rule counts a school's staff visits in two pools (owner,
# 2026-09-28). The SUPPORT visit is a Training Follow Up or an In-school
# Training — one a year in total. SSA SUPPORT is counted apart, one a year.
# Donor, story, invitation and social visits are in neither and have no
# limit.
SUPPORT_POOL = "support"
SSA_POOL = "ssa"
SSA_SUPPORT_VISIT_TYPES = (
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
)
# In-school Training, and the retired In-school Coaching Visit the owner
# called "the same as In-school training", are support visits.
IN_SCHOOL_SUPPORT_TYPES = ("in_school_training", "in_school_coaching_visit")

# The drawer purposes each pool governs.
POOL_PURPOSES = {
    SUPPORT_POOL: ("training_follow_up", "in_school_training"),
    SSA_POOL: ("ssa_support",),
}
# Every purpose the client rule counts.
FOLLOW_UP_PURPOSES = POOL_PURPOSES[SUPPORT_POOL] + POOL_PURPOSES[SSA_POOL]


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


def client_visit_pool(
    activity_type: str, catalogue_item=None, purpose_type: str | None = None
) -> str | None:
    """Which of a client-rule school's two counts an activity of this shape
    uses: ``SUPPORT_POOL``, ``SSA_POOL``, or None for a visit with no limit.
    Mirrors ``_support_visit_q`` / ``_ssa_visit_q`` for a row that does not
    exist yet."""
    if purpose_type == COMPANION_VISIT_PURPOSE or _exempt_by_rule(catalogue_item):
        return None
    if activity_type in SSA_SUPPORT_VISIT_TYPES:
        return SSA_POOL
    if activity_type in IN_SCHOOL_SUPPORT_TYPES:
        return SUPPORT_POOL
    if consumes_client_visit(activity_type, catalogue_item, purpose_type):
        return SUPPORT_POOL
    return None


def _support_visit_q():
    from django.db.models import Q

    return (_client_visit_q() & ~Q(activity_type__in=SSA_SUPPORT_VISIT_TYPES)) | Q(
        activity_type__in=IN_SCHOOL_SUPPORT_TYPES
    )


def _ssa_visit_q():
    from django.db.models import Q

    return Q(activity_type__in=SSA_SUPPORT_VISIT_TYPES)


def is_gated_visit(
    rule: str, activity_type: str, catalogue_item=None, purpose_type=None
) -> bool:
    """Is an activity of this shape the kind of visit the rule counts?"""
    if rule == "core":
        return activity_type == "core_visit"
    if rule == "client":
        return (
            client_visit_pool(activity_type, catalogue_item, purpose_type) is not None
        )
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
        counted = (
            live.filter(school_id__in=client_ids)
            .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
            .exclude(
                catalogue_item__counts_toward_client_visit=True,
                catalogue_item__eligibility_rule__counts_toward_entitlement=False,
            )
        )
        _tally(counted.filter(_support_visit_q()), "staff_visits", "partner_visits")
        _tally(counted.filter(_ssa_visit_q()), "staff_ssa_visits", "partner_ssa_visits")
    if core_ids:
        from apps.core_schools.core_planning_services import (
            core_training_q,
            core_visit_q,
        )

        _tally(
            live.filter(school_id__in=core_ids).filter(core_visit_q()),
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
    # A handover that names no slot (made from the Planning page) is read by
    # what it asks for, as the package reads it when it reserves its slot
    # (apps.core_schools.package_credit.assignment_kind).
    from apps.core_schools.package_credit import assignment_kind

    return assignment_kind(assignment) == "visit"


def _is_core_training_assignment(assignment) -> bool:
    from apps.core_schools.package_credit import assignment_kind

    return assignment_kind(assignment) == "training"


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

    Owner, 2026-09-28: "lift all restrictions. the only restriction is for
    client schools to have one visit from the staff. treat core trained just
    like client schools." Three things are refused, and nothing else:

    * at a client-rule school (client, Core Trained and Core Graduate), a
      second staff support visit in the year — a Training Follow Up or an
      In-school Training — or a second SSA Support;
    * at a Core school, a third staff core visit while the partner has one
      planned there ("staff may plan more core schools visits but only if
      the partner has not planned");
    * partner work at a Champion school, which takes only donor and story
      visits (kept by the owner the same day).

    The counting stays for everything else, because it is what the pages
    SHOW: a count is information, and only these three are permissions.
    """
    _decide_by_rule(gate)
    # Core Trained and Core Graduate are planned exactly like a client
    # school, partner work included (owner, 2026-09-28). Champion takes only
    # donor and story visits, which no partner delivers.
    if gate.school_type in OUTREACH_ONLY_SCHOOL_TYPES:
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
        # One staff support visit a year (a Training Follow Up or an
        # In-school Training) and one SSA Support, and nothing else (owner,
        # 2026-09-28). The whole Schedule button stays live: donor, story,
        # invitation and social visits have no limit, so only a used pool's
        # purposes grey (POOL_PURPOSES).
        gate.staff_cap = CLIENT_STAFF_VISIT_CAP
        gate.ssa_cap = CLIENT_STAFF_SSA_VISIT_CAP
        gate.partner_cap = 0  # counted, never capped
        if gate.staff_visits >= CLIENT_STAFF_VISIT_CAP:
            gate.staff_can_schedule = False
            gate.staff_reason = (
                f"{gate.school_name} has had its staff support visit (a Training "
                f"Follow Up or an In-school Training) for FY{gate.fy} "
                f"({gate.staff_visits}/{CLIENT_STAFF_VISIT_CAP})."
            )
        if gate.staff_ssa_visits >= CLIENT_STAFF_SSA_VISIT_CAP:
            gate.ssa_can_schedule = False
            gate.ssa_reason = (
                f"{gate.school_name} has had its SSA Support visit for "
                f"FY{gate.fy} ({gate.staff_ssa_visits}/{CLIENT_STAFF_SSA_VISIT_CAP})."
            )
        return

    if gate.rule == "core":
        # Owner, 2026-09-28: "staff may plan more core schools visits but
        # only if the partner has not planned." Staff keep their two while a
        # partner core visit is planned at the school this year; with none
        # planned, the package is theirs to fill. A handover the partner has
        # not dated yet is not a plan. The partner side is no longer capped,
        # and neither are trainings (`staff_trainings_open`).
        if gate.partner_visits:
            gate.staff_cap = CORE_STAFF_VISIT_CAP
            if gate.staff_visits >= CORE_STAFF_VISIT_CAP:
                gate.staff_can_schedule = False
                gate.staff_reason = (
                    f"Staff core visits complete for FY{gate.fy} "
                    f"({gate.staff_visits}/{CORE_STAFF_VISIT_CAP}). The partner "
                    "has planned the remaining visits."
                )
        else:
            gate.staff_cap = max(CORE_PACKAGE_VISITS, gate.staff_visits + 1)
        gate.partner_cap = 0  # counted, never capped
        return


def assert_staff_may_schedule_visit(
    school, fy=None, *, pool: str = SUPPORT_POOL, **kwargs
) -> VisitGate:
    """Refuse a staff visit the school's rule has no room for; else its gate.

    ``pool`` is the client rule's count the visit uses (``client_visit_pool``);
    a core school has one. The three helpers below read the same fields the
    buttons do, so a page and the POST behind it give one answer. They are
    called from the scheduling services, the partner queue and the core
    package.
    """
    from apps.core.exceptions import BadRequest

    gate = visit_gate(school, fy, **kwargs)
    if gate.rule == "client" and pool == SSA_POOL:
        if not gate.ssa_can_schedule:
            raise BadRequest(gate.ssa_reason)
    elif not gate.staff_can_schedule:
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
