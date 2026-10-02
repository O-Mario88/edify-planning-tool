"""The governed programme configuration Country Planning Oversight counts against.

Every figure on the page is "what was planned" against "what the programme
requires", and the requirement side is policy, not arithmetic. The rules
themselves are the planning rulebook's (``rules``, owner 2026-10-01); this
module holds what the school-by-school engine needs from them, so an approved
change moves every KPI, chart, table row, export and follow-up at once —
nothing downstream restates a 4, a 2 or a 560.

**School groups.** A school is read by its own type. For the one thing a type
does not decide — how a holder's staff capacity is shared out — the types fall
into three groups: *Core* (two staff visits and two Partner visits each),
*client-rule* (Client, Core Trained and Core Graduate: one visit, from staff
or a Partner) and *outreach* (Champion: donor and story visits only, outside
every requirement). A type the rulebook does not know sits outside every
figure until the product owner decides where it belongs.

**Annual obligation.** A Core school needs four visits — two from staff and
two from a Partner — and four trainings, split the same way. A Client or Core
Trained school needs one visit and one training; a Core Graduate school one
visit and no training; a Champion school neither.

**Staff capacity.** A CCEO plans 560 visits a year and a Programme Lead 280.
Core staff slots are required whatever the ceiling says: a ceiling below them
is shown as an internal capacity deficit, never moved silently to the Partner
side. Client-rule slots use the capacity left after Core; the balance is the
Partner's.

**Planned.** An activity counts as planned when it carries a date and sits in
a scheduled-or-later state of the canonical ``ActivityStatus`` enum. A Partner
handover the Partner has not dated is *assigned*, not planned, and verification
stays a separate figure (``VERIFIED_STATES``).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.enums import ActivityStatus, SchoolType

#: Bumped whenever a rule below changes, and stored on every follow-up and in
#: every cache key, so a snapshot always names the policy it was taken under.
POLICY_VERSION = "2026-10-02.1"

# ── School groups ────────────────────────────────────────────────────────────
CORE_FAMILY = "core_family"
CLIENT_FAMILY = "client_family"
OUTREACH_FAMILY = "outreach_family"
UNMAPPED_FAMILY = "unmapped"

FAMILY_LABELS = {
    CORE_FAMILY: "Core",
    CLIENT_FAMILY: "Client rule",
    OUTREACH_FAMILY: "Outreach only",
    UNMAPPED_FAMILY: "No governed type",
}

#: School type → group (see the module doc). Core Graduate follows the client
#: rule for its visits and Partner work (owner, 2026-09-28, PR #163); Champion
#: schools are outside the requirement (owner, 2026-10-01).
SCHOOL_TYPE_FAMILY: dict[str, str] = {
    SchoolType.CORE.value: CORE_FAMILY,
    SchoolType.CLIENT.value: CLIENT_FAMILY,
    SchoolType.CORE_TRAINED.value: CLIENT_FAMILY,
    SchoolType.CORE_GRADUATE.value: CLIENT_FAMILY,
    SchoolType.CHAMPION.value: OUTREACH_FAMILY,
}

#: School types that exist in the enum but have no approved group. Each one
#: is excluded from every requirement until the product owner decides, and
#: its schools are listed on the data-quality queue with this reason.
PENDING_FAMILY_DECISIONS: dict[str, str] = {}


def family_of(school_type: str | None) -> str:
    """The group of a school type; ``UNMAPPED_FAMILY`` if none."""
    return SCHOOL_TYPE_FAMILY.get(str(school_type or ""), UNMAPPED_FAMILY)


# ── Requirements ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FamilyRequirement:
    """One school's annual visit slots, by kind.

    ``flexible_visit_slots`` are the client-rule visit: one slot a member of
    staff or a Partner may deliver, decided by the holder's capacity
    allocation rather than by the school. Trainings are read from the
    school's own type (``training_slots_for``): Core Graduate schools follow
    the client rule for visits and take no training.
    """

    staff_visit_slots: int
    partner_visit_slots: int
    flexible_visit_slots: int

    @property
    def visit_slots(self) -> int:
        return (
            self.staff_visit_slots
            + self.partner_visit_slots
            + self.flexible_visit_slots
        )


REQUIREMENTS: dict[str, FamilyRequirement] = {
    CORE_FAMILY: FamilyRequirement(2, 2, 0),
    CLIENT_FAMILY: FamilyRequirement(0, 0, 1),
    OUTREACH_FAMILY: FamilyRequirement(0, 0, 0),
    UNMAPPED_FAMILY: FamilyRequirement(0, 0, 0),
}


def requirement_for(family: str) -> FamilyRequirement:
    return REQUIREMENTS.get(family, REQUIREMENTS[UNMAPPED_FAMILY])


def training_slots_for(school_type: str | None) -> tuple[int, int, int]:
    """(staff, Partner, either) training slots a school of this type needs."""
    from apps.planning.country_oversight import rules

    need = rules.requirement_for(school_type)
    return need.staff_trainings, need.partner_trainings, need.either_trainings


# ── Staff capacity ───────────────────────────────────────────────────────────
CCEO_ROLE = "CCEO"
PROGRAM_LEAD_ROLE = "Program Lead"

#: Annual staff-visit ceilings by the role that personally holds a portfolio:
#: the visits the role plans in a year. A school held by anyone else (or by
#: nobody) has no internal capacity behind it: its Core staff slots show as a
#: deficit and its client-rule slot falls to the Partner side, which is
#: exactly the finding a reader needs to act on.
STAFF_CEILINGS: dict[str, int] = {
    CCEO_ROLE: 560,
    PROGRAM_LEAD_ROLE: 280,
}


def ceiling_for(role: str | None) -> int:
    return STAFF_CEILINGS.get(str(role or ""), 0)


# ── The eligible portfolio ───────────────────────────────────────────────────
#: Duplicate records of another school. A merged or confirmed duplicate is the
#: same school counted twice, so it is outside every denominator.
EXCLUDED_DUPLICATE_STATUSES = ("confirmed", "merged")

# ── Planned, assigned and verified ───────────────────────────────────────────
S = ActivityStatus

#: Scheduled-or-later states. Each counts as planned only with a date on it.
PLANNED_STATES: frozenset[str] = frozenset(
    str(state)
    for state in (
        S.SCHEDULED,
        S.PARTNER_SCHEDULED,
        S.IN_PROGRESS,
        S.COMPLETION_STARTED,
        S.EVIDENCE_UPLOADED,
        S.EVIDENCE_ACCEPTED,
        S.SALESFORCE_ID_REQUIRED,
        S.SUBMITTED_TO_PL,
        # A completion returned for correction is delivered work being fixed,
        # not work sent back to planning: it keeps its slot, as the target
        # engine keeps it in planned output.
        S.RETURNED_BY_PL,
        S.AWAITING_IA_VERIFICATION,
        S.RETURNED_BY_IA,
        S.IA_VERIFIED,
        S.ACCOUNTANT_CONFIRMED,
        S.COMPLETED,
        S.CLOSED,
        # A plan with a date is priced and funded like a scheduled one; the
        # undated ones are excluded by the date rule, not the state.
        S.PLANNED,
        S.RESCHEDULED,
    )
)

#: Never planned: not yet anybody's plan, a Partner handover that has not been
#: dated, work sent back to planning, and abandoned work.
NOT_PLANNED_STATES: frozenset[str] = frozenset(
    str(state)
    for state in (
        S.NOT_PLANNED,
        S.AWAITING_OWNER_APPROVAL,
        S.ASSIGNED_TO_PARTNER,
        S.RETURNED,
        S.REJECTED,
        S.CANCELLED,
        S.DEFERRED,
    )
)

#: Verified delivery — secondary context only; planned is never verified.
VERIFIED_STATES: frozenset[str] = frozenset(
    str(state) for state in (S.IA_VERIFIED, S.ACCOUNTANT_CONFIRMED, S.CLOSED)
)


def check() -> None:
    """Every ActivityStatus is classified exactly once, planned or not."""
    everything = set(ActivityStatus.values)
    overlap = PLANNED_STATES & NOT_PLANNED_STATES
    if overlap:
        raise ValueError(f"statuses both planned and not planned: {sorted(overlap)}")
    missing = everything - PLANNED_STATES - NOT_PLANNED_STATES
    if missing:
        raise ValueError(
            "unclassified ActivityStatus value(s) for planning oversight: "
            f"{sorted(missing)} — add them to apps/planning/country_oversight/policy.py"
        )
    if not VERIFIED_STATES <= PLANNED_STATES:
        raise ValueError("a verified state must also count as planned")
    from apps.planning.country_oversight import rules

    rules.check()
    if STAFF_CEILINGS != rules.VISIT_TARGETS:
        raise ValueError("staff ceilings and the rulebook's visit targets differ")
    unknown = (
        set(SchoolType.values) - set(SCHOOL_TYPE_FAMILY) - set(PENDING_FAMILY_DECISIONS)
    )
    if unknown:
        raise ValueError(f"school types with no planning group: {sorted(unknown)}")


# ── Period phasing ───────────────────────────────────────────────────────────
#: The approved quarterly phasing of an annual commitment, shared with the
#: performance engine (apps.hr.performance_engine.DEFAULT_PHASING). There is
#: no approved weekly phasing, so a week is compared with nothing but itself
#: and the year's cumulative position.
def quarterly_phasing() -> dict[int, float]:
    from apps.hr.performance_engine import DEFAULT_PHASING

    return dict(DEFAULT_PHASING)


def phased_months(annual: int) -> list[int]:
    """An annual figure split over the twelve FY months (October first),
    preserving the total exactly — the performance engine's own split."""
    from apps.hr.performance_engine import _phased_split

    return list(_phased_split(int(annual)))
