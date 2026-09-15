"""Who may schedule a visit at a school this year — one answer for every button.

Owner, 2026-09-15:

  "Client school visits: they are supposed to be visited once in a year, so if
  a staff or partner has already scheduled it, the schedule buttons should be
  disabled. Assigned school to a partner should also be disabled from staff
  scheduling; only the partner can schedule it unless the partner returns the
  school back to the staff. Core schools should be scheduled by staff twice
  for visit and assigned twice to a partner. Staff can only schedule a core
  school visit twice and the button disables once those visits are done;
  the partner can also only schedule twice."

The rule is read in two places that must never disagree: the buttons on the
Planning, Cluster, Core Schools and Partner pages (greyed, with the reason as
the tooltip) and the services that create the work (which refuse with the same
sentence). Both call here. Nothing else counts visits for this purpose.

What counts:

* Client-rule schools (``client`` and ``core_trained``): a support visit to
  the school in the operational fiscal year, whoever delivers it — the
  canonical visit types (apps.core.activity_types.VISIT_TYPES) less the four
  social ones that are not support (donor, social, story-gathering,
  invitation) and the core-package ones, plus anything the catalogue flags
  as consuming the client visit. One per year. A catalogue item the CD has
  taken out of the entitlement (its rule's counts_toward_entitlement off)
  neither counts nor is refused. A live partner assignment that has not been
  scheduled yet also locks the staff buttons; a returned one does not.
* Core schools: ``core_visit`` activities in the fiscal year, split by
  ``delivery_type``. Staff may hold two; the partner side (scheduled partner
  visits plus visit slots assigned to a partner and not yet scheduled) may
  hold two. These are the halves of the package's four visits, and the same
  two the core scheduling service caps at.

"Live" excludes cancelled, rejected, deferred and not-planned work, which is
what every other counter here excludes. A completed visit still counts: the
school has been visited this year.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from django.db.models import Count

CLIENT_VISIT_CAP = 1
CORE_STAFF_VISIT_CAP = 2
CORE_PARTNER_VISIT_CAP = 2

# School types under the once-a-year client rule. Core schools carry the
# package; champions and core graduates are outside both rules.
CLIENT_RULE_SCHOOL_TYPES = ("client", "core_trained")
CORE_RULE_SCHOOL_TYPES = ("core",)

DEAD_STATUSES = ("cancelled", "rejected", "deferred", "not_planned")


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
    partner_can_schedule: bool = True
    partner_reason: str = ""
    can_assign_partner: bool = True
    assign_reason: str = ""
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
    def core_staff_share_complete(self) -> bool:
        """Staff have used their two visits and two trainings."""
        return (
            self.rule == "core"
            and self.staff_visits >= CORE_STAFF_VISIT_CAP
            and self.staff_trainings >= CORE_STAFF_VISIT_CAP
        )

    @property
    def core_partner_share_complete(self) -> bool:
        """Two visits and two trainings are scheduled by, or assigned to, a
        partner."""
        return (
            self.rule == "core"
            and self.partner_held_visits >= CORE_PARTNER_VISIT_CAP
            and self.partner_trainings + self.partner_pending_trainings
            >= CORE_PARTNER_VISIT_CAP
        )

    def as_dict(self) -> dict:
        data = asdict(self)
        data["total_visits"] = self.total_visits
        data["partner_held_visits"] = self.partner_held_visits
        data["core_staff_share_complete"] = self.core_staff_share_complete
        data["core_partner_share_complete"] = self.core_partner_share_complete
        return data


# Visits that are not support: they do not use the school's yearly visit.
SOCIAL_VISIT_TYPES = (
    "donor_visit",
    "social_visit",
    "story_gathering_visit",
    "school_invitation",
)
CORE_PACKAGE_TYPES = ("core_visit", "core_assessment_visit")


def support_visit_types() -> tuple[str, ...]:
    from apps.core.activity_types import VISIT_TYPES

    return tuple(
        t for t in VISIT_TYPES if t not in SOCIAL_VISIT_TYPES + CORE_PACKAGE_TYPES
    )


def _client_visit_q():
    from django.db.models import Q

    from apps.activities.services import client_entitlement_consumers_q

    return Q(activity_type__in=support_visit_types()) | client_entitlement_consumers_q(
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


def consumes_client_visit(activity_type: str, catalogue_item=None) -> bool:
    """Does an activity of this shape count as the client school's visit?
    Mirrors ``_client_visit_q`` for a row that does not exist yet."""
    if _exempt_by_rule(catalogue_item):
        return False
    if catalogue_item is not None and getattr(
        catalogue_item, "counts_toward_client_visit", False
    ):
        return True
    return activity_type in support_visit_types()


def is_gated_visit(rule: str, activity_type: str, catalogue_item=None) -> bool:
    """Is an activity of this shape the kind of visit the rule counts?"""
    if rule == "core":
        return activity_type == "core_visit"
    if rule == "client":
        return consumes_client_visit(activity_type, catalogue_item)
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
        status__in=DEAD_STATUSES
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
            .exclude(
                catalogue_item__counts_toward_client_visit=True,
                catalogue_item__eligibility_rule__counts_toward_entitlement=False,
            ),
            "staff_visits",
            "partner_visits",
        )
    if core_ids:
        _tally(
            live.filter(school_id__in=core_ids, activity_type="core_visit"),
            "staff_visits",
            "partner_visits",
        )
        _tally(
            live.filter(school_id__in=core_ids, activity_type="core_training"),
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


def _decide(gate: VisitGate) -> None:
    if gate.rule == "client":
        gate.staff_cap = CLIENT_VISIT_CAP
        gate.partner_cap = CLIENT_VISIT_CAP
        visited = gate.total_visits >= CLIENT_VISIT_CAP
        if visited:
            who = (
                "a partner"
                if gate.partner_visits and not gate.staff_visits
                else "staff"
            )
            visited_reason = (
                f"{gate.school_name} already has its visit for FY{gate.fy} "
                f"(scheduled by {who}). Client schools are visited once a year."
            )
            gate.staff_can_schedule = False
            gate.staff_reason = visited_reason
            gate.partner_can_schedule = False
            gate.partner_reason = visited_reason
            gate.can_assign_partner = False
            gate.assign_reason = visited_reason
        elif gate.partner_pending:
            partner = gate.partner_name or "a partner"
            locked = (
                f"{gate.school_name} is assigned to {partner}. Only the partner "
                "can schedule it until they return the school to staff."
            )
            gate.staff_can_schedule = False
            gate.staff_reason = locked
            gate.can_assign_partner = False
            gate.assign_reason = f"{gate.school_name} is already assigned to {partner}."
        return

    if gate.rule == "core":
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
            gate.assign_reason = (
                f"Partner core visits already assigned for FY{gate.fy} "
                f"({partner_held}/{CORE_PARTNER_VISIT_CAP})."
            )
        return


def assert_staff_may_schedule_visit(school, fy=None, **kwargs) -> VisitGate:
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
