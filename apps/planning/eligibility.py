"""Can this school take this plan, and if not, exactly why.

Owner, 2026-10-08:

  "Build a centralized FY-aware School Visit Planning Eligibility Engine that
  prevents duplicate operational coverage while preserving legitimate
  exceptions such as SSA Support."

The rule itself, its counts and its sentences live in
``apps.planning.visit_gate``, which every scheduling and hand-over door
already asks. This module is that answer in the shape the brief asks for: one
question — school, what is being planned, financial year — and one structured
reply, so a page, an export or an API client never works the rule out for
itself.

What can be planned (``context``):

* ``STAFF_VISIT`` — a staff member's support visit: a Training Follow Up or
  an In-school Training. Closed where the school has its staff visit for the
  year (``STAFF_VISIT_SCHEDULED``) or a partner holds it
  (``PARTNER_VISIT_ASSIGNED``).
* ``PARTNER_VISIT`` — handing the school to a partner for that visit. Closed
  for the same two reasons, read from the other side.
* ``PARTNER_SSA_SUPPORT`` — handing the school to a partner for SSA Support.
  Open only until the school has completed its SSA for the year
  (``SSA_SUPPORT_ELIGIBLE`` / ``CURRENT_FY_SSA_EXISTS``); a visit, staff's or
  a partner's, has no say in it.

A school that has closed down is closed to all three (``SCHOOL_CLOSED``) until
it is reopened, and a Special Project's work is counted on its training: it
neither holds a school's visit nor is held by one.

Not asked here, because none of it is a visit commitment and each has its
own rule: donor, story, invitation and social visits, staff SSA Support,
group trainings and their ceilings (``apps.planning.training_ceilings``),
cluster sessions, and who may plan a school at all (``apps.core.scoping``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from apps.planning import visit_gate as gate_rules
from apps.planning.visit_gate import (
    AVAILABLE,
    CORE_PACKAGE_SIDE_COMPLETE,
    CURRENT_FY_SSA_EXISTS,
    PARTNER_VISIT_ASSIGNED,
    REASON_LABELS,
    SCHOOL_CLOSED,
    SSA_SUPPORT_ELIGIBLE,
    STAFF_DELIVERED_ONLY,
    STAFF_VISIT_SCHEDULED,
    VisitGate,
)

STAFF_VISIT = "STAFF_VISIT"
PARTNER_VISIT = "PARTNER_VISIT"
PARTNER_SSA_SUPPORT = "PARTNER_SSA_SUPPORT"
CONTEXTS = (STAFF_VISIT, PARTNER_VISIT, PARTNER_SSA_SUPPORT)

#: What a hand-over is for, as the data records it. Read from the hand-over's
#: purpose and activity type, never from the partner's name.
ASSIGNMENT_NORMAL_VISIT = "NORMAL_VISIT"
ASSIGNMENT_SSA_SUPPORT = "SSA_SUPPORT"


@dataclass(frozen=True)
class Eligibility:
    """One school's answer for one kind of plan in one financial year."""

    school_id: str
    context: str
    fy: str
    eligible: bool
    reason: str
    label: str
    message: str = ""
    category: str = ""
    assigned_to: str = ""
    assignment_type: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        # The brief's own spelling, beside the snake-case one.
        data["assignedTo"] = self.assigned_to
        data["assignmentType"] = self.assignment_type
        return data


def from_gate(gate: VisitGate, context: str = STAFF_VISIT) -> Eligibility:
    """The gate's answer for ``context``, as an ``Eligibility``."""
    if context not in CONTEXTS:
        raise ValueError(f"Unknown planning context: {context!r}")
    if context == PARTNER_SSA_SUPPORT:
        eligible, reason, message = (
            gate.can_assign_ssa,
            gate.assign_ssa_code,
            gate.assign_ssa_reason,
        )
        assignment_type = ASSIGNMENT_SSA_SUPPORT
    elif context == PARTNER_VISIT:
        eligible, reason, message = (
            gate.can_assign_visit,
            gate.assign_visit_code,
            gate.assign_visit_reason,
        )
        assignment_type = ASSIGNMENT_NORMAL_VISIT
    else:
        eligible, reason, message = (
            gate.staff_can_schedule,
            gate.staff_code,
            gate.staff_reason,
        )
        assignment_type = ""
    held = reason == PARTNER_VISIT_ASSIGNED
    return Eligibility(
        school_id=gate.school_id,
        context=context,
        fy=gate.fy,
        eligible=eligible,
        reason=reason,
        label=REASON_LABELS.get(reason, reason),
        message="" if eligible else message,
        category=str(gate.school_type or "").upper(),
        assigned_to=gate.holder if held else "",
        assignment_type=ASSIGNMENT_NORMAL_VISIT if held else assignment_type,
    )


def school_planning_eligibilities(
    schools, context: str = STAFF_VISIT, fy: str | None = None, **kwargs
) -> dict[str, Eligibility]:
    """The answer for a page of schools, in the gate's bounded queries."""
    return {
        school_id: from_gate(gate, context)
        for school_id, gate in gate_rules.visit_gates(schools, fy, **kwargs).items()
    }


def school_planning_eligibility(
    school, context: str = STAFF_VISIT, fy: str | None = None, **kwargs
) -> Eligibility:
    """Whether ``school`` can take a plan of kind ``context`` in ``fy`` (the
    operational year by default), and the reason where it cannot."""
    return school_planning_eligibilities([school], context, fy, **kwargs)[school.id]


def handover_context(
    purpose_of_visit=None, expected_activity_type=None, training_course=None
) -> str | None:
    """What a hand-over of this shape commits the school to.

    ``PARTNER_SSA_SUPPORT`` for data collection, ``PARTNER_VISIT`` for the
    school's support visit, and None for a universal training, which is on
    top of every school's year and holds nobody's visit (owner, 2026-10-06).
    """
    from apps.planning.country_oversight import rules
    from apps.planning.training_entitlement import is_universal

    if rules.is_data_collection(expected_activity_type, purpose_of_visit):
        return PARTNER_SSA_SUPPORT
    if is_universal(training_course):
        return None
    return PARTNER_VISIT


def assert_handover_eligible(
    school,
    *,
    purpose_of_visit=None,
    expected_activity_type=None,
    training_course=None,
    past_school_rules: bool = False,
    fy: str | None = None,
    **kwargs,
) -> None:
    """Refuse a hand-over the school has no room for.

    Asked by every door that puts a school in a partner's hands, with the
    school's row locked, so the button, the drawer and the save agree and two
    people cannot both be first. ``past_school_rules`` is a Special Project's
    hand-over (owner, 2026-10-05: "all projects schools added to a project
    can be assigned to any partner"; ``apps.partners.handover_policy``): it
    goes past both rules here as it goes past the others, and comes back
    under them with that module's one switch.
    """
    if school is None or past_school_rules:
        return
    context = handover_context(
        purpose_of_visit, expected_activity_type, training_course
    )
    if context == PARTNER_SSA_SUPPORT:
        if gate_rules.rule_for(school.school_type) != "none":
            gate_rules.assert_may_assign_ssa_support(school, fy, **kwargs)
        return
    if context is None:
        return
    if school.school_type in gate_rules.ONE_COMMITMENT_SCHOOL_TYPES:
        gate_rules.assert_may_hand_over_visit(school, fy, **kwargs)


__all__ = [
    "ASSIGNMENT_NORMAL_VISIT",
    "ASSIGNMENT_SSA_SUPPORT",
    "AVAILABLE",
    "CONTEXTS",
    "CORE_PACKAGE_SIDE_COMPLETE",
    "CURRENT_FY_SSA_EXISTS",
    "Eligibility",
    "PARTNER_SSA_SUPPORT",
    "PARTNER_VISIT",
    "PARTNER_VISIT_ASSIGNED",
    "SCHOOL_CLOSED",
    "SSA_SUPPORT_ELIGIBLE",
    "STAFF_DELIVERED_ONLY",
    "STAFF_VISIT",
    "STAFF_VISIT_SCHEDULED",
    "assert_handover_eligible",
    "from_gate",
    "handover_context",
    "school_planning_eligibilities",
    "school_planning_eligibility",
]
