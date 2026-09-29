"""The governed programme configuration Country Planning Oversight counts against.

Every figure on the page is "what was planned" against "what the programme
requires", and the requirement side is policy, not arithmetic. It lives here,
in one module, so an approved change to it moves every KPI, chart, table row,
export and follow-up at once — nothing downstream restates a 4, a 2 or a 560.

**School families.** The platform's two families are the ones the target
engine already keys on (apps.hr.target_distribution): Core and Champion are
Core-family, Client and Core Trained are Client-family. They are read from
there rather than restated, so the two can never disagree about which family a
school is in.

Core Graduate is a distinct ``SchoolType`` the target engine does not list.
It is not folded into a family by guesswork: the owner decided it (2026-09-28,
PR #163 — "Core Graduate follows the client rule for its visits ... and
partner work"), so it is Client-family here by that decision, recorded in
``GOVERNED_FAMILY_DECISIONS``. It still receives no training and sits off the
cluster lists (apps.planning.visit_gate), so its training slot is listed as
undeliverable rather than read as somebody's gap. A type with no family and no
decision sits outside every denominator (``PENDING_FAMILY_DECISIONS``).

**Annual obligation.** A Core-family school needs four visit slots — two for
staff and two for a Partner — and four school-training slots. A Client-family
school needs one visit slot, delivered by staff or a Partner according to the
owner's capacity allocation, and one school-training slot. So the country's
visit requirement is 4C + L and its training requirement is 4C + L.

**Staff capacity.** A CCEO can deliver 560 staff visits a year and a
Programme Lead 280 of their own. Core staff slots are required whatever the
ceiling says: a ceiling below them is shown as an internal capacity deficit,
never moved silently to the Partner side. Client slots use the capacity left
after Core; the balance is the Partner's.

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
POLICY_VERSION = "2026-09-28.2"

# ── School families ──────────────────────────────────────────────────────────
CORE_FAMILY = "core_family"
CLIENT_FAMILY = "client_family"
UNMAPPED_FAMILY = "unmapped"

FAMILY_LABELS = {
    CORE_FAMILY: "Core-family",
    CLIENT_FAMILY: "Client-family",
    UNMAPPED_FAMILY: "No governed family",
}


def _family_map() -> dict[str, str]:
    from apps.hr.target_distribution import CLIENT_FAMILY as CLIENT_TYPES
    from apps.hr.target_distribution import CORE_FAMILY as CORE_TYPES

    mapping = {school_type: CORE_FAMILY for school_type in CORE_TYPES}
    mapping.update({school_type: CLIENT_FAMILY for school_type in CLIENT_TYPES})
    return mapping


#: Owner decisions for school types the target engine does not list: the
#: type, its family, and where the decision is recorded.
GOVERNED_FAMILY_DECISIONS: dict[str, tuple[str, str]] = {
    SchoolType.CORE_GRADUATE.value: (
        CLIENT_FAMILY,
        "Owner, 2026-09-28 (PR #163): Core Graduate follows the client rule for "
        "its visits and Partner work.",
    ),
}

#: School type → family: the target engine's own definition, then the owner's
#: decisions for the types it does not list.
SCHOOL_TYPE_FAMILY: dict[str, str] = {
    **_family_map(),
    **{
        school_type: family
        for school_type, (family, _) in GOVERNED_FAMILY_DECISIONS.items()
    },
}

#: School types that exist in the enum but have no approved family. Each one
#: is excluded from every requirement until the product owner decides, and
#: its schools are listed on the data-quality queue with this reason.
PENDING_FAMILY_DECISIONS: dict[str, str] = {}


def family_of(school_type: str | None) -> str:
    """The governed family of a school type; ``UNMAPPED_FAMILY`` if none."""
    return SCHOOL_TYPE_FAMILY.get(str(school_type or ""), UNMAPPED_FAMILY)


# ── Requirements ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FamilyRequirement:
    """One school's annual slots, by kind.

    ``flexible_visit_slots`` are the Client visit: one slot a member of staff
    or a Partner may deliver, decided by the owner's capacity allocation
    rather than by the school.
    """

    staff_visit_slots: int
    partner_visit_slots: int
    flexible_visit_slots: int
    training_slots: int

    @property
    def visit_slots(self) -> int:
        return (
            self.staff_visit_slots
            + self.partner_visit_slots
            + self.flexible_visit_slots
        )


REQUIREMENTS: dict[str, FamilyRequirement] = {
    CORE_FAMILY: FamilyRequirement(
        staff_visit_slots=2,
        partner_visit_slots=2,
        flexible_visit_slots=0,
        training_slots=4,
    ),
    CLIENT_FAMILY: FamilyRequirement(
        staff_visit_slots=0,
        partner_visit_slots=0,
        flexible_visit_slots=1,
        training_slots=1,
    ),
    UNMAPPED_FAMILY: FamilyRequirement(0, 0, 0, 0),
}


def requirement_for(family: str) -> FamilyRequirement:
    return REQUIREMENTS.get(family, REQUIREMENTS[UNMAPPED_FAMILY])


# ── Staff capacity ───────────────────────────────────────────────────────────
CCEO_ROLE = "CCEO"
PROGRAM_LEAD_ROLE = "Program Lead"

#: Annual staff-visit ceilings by the role that personally holds a portfolio.
#: A school held by anyone else (or by nobody) has no internal capacity behind
#: it: its Core staff slots show as a deficit and its Client slot falls to the
#: Partner side, which is exactly the finding a reader needs to act on.
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


# ── What cannot be delivered under today's scheduling rules ──────────────────
#: Slots the policy requires but the scheduling rules refuse, by school type.
#: Champion schools are Core-family here, yet the platform plans them only for
#: donor and story visits, never trains them and never hands them to a
#: Partner (apps.planning.visit_gate, owner 2026-09-21/25). Their Partner and
#: training slots therefore cannot close; the data-quality queue says so
#: rather than letting the gap read as somebody's neglect.
UNDELIVERABLE_SLOTS: dict[str, tuple[str, ...]] = {
    SchoolType.CHAMPION.value: ("partner_visit", "training"),
    # Client-family for its visits (owner, 2026-09-28), still untrained
    # (owner, 2026-09-25): the training slot cannot close.
    SchoolType.CORE_GRADUATE.value: ("training",),
}


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
