"""PlanningHierarchyService — the same figures, folded up the organisation.

Country → Programme Lead → the Lead and each CCEO → delivery channel and
Partner → school. Every level is a sum of the level below it.

A row carries two readings of one person's year, and they are different
questions (owner, 2026-10-01):

* **Their plan** — the counted visits, trainings and cluster meetings the
  person planned, wherever the school is, against the visits their role
  plans (a CCEO 560, a Programme Lead 280), and the Partner work they handed
  over. These are the ``PEOPLE_FIELDS``; they are read per person
  (``people``) and added to the row.

* **Their schools** — what the schools they hold need and what is planned
  for them, by anybody. These start from per-school figures that are already
  capped at the school's slots, so a heading and the rows under it cannot
  disagree and nothing is counted twice: a school belongs to exactly one
  holder, a holder to exactly one Lead (or to "No Programme Lead"), and
  Partner rows share a school's Partner claims between the Partners holding it.

For a quarter or a month the requirement is the approved phasing of each
person's annual figure (the performance engine's own split), applied at the
person and summed upward — so the country's phased figure is the sum of its
people's, as a personal target is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.planning.country_oversight import policy
from apps.planning.country_oversight.coverage import (
    Claims,
    SchoolFacts,
    Window,
    duplicate_reasons,
)

#: School types that have a column of their own, and the field it fills.
TYPE_FIELDS: dict[str, str] = {
    "core": "core_schools",
    "client": "client_schools",
    "core_trained": "core_trained_schools",
    "core_graduate": "core_graduate_schools",
    "champion": "champion_schools",
}

#: A person's own plan (see the module doc): read per person, not per school.
PEOPLE_FIELDS: tuple[str, ...] = (
    # The visits the role plans in the year (phased for a quarter or month).
    "target",
    # Counted visits the person planned, and by kind.
    "p_visits",
    "p_follow_up",
    "p_in_school",
    "p_ssa",
    # Donor, story, invitation and social visits: planned, not counted.
    "p_outreach",
    "p_trainings",
    "p_cluster_trainings",
    "p_meetings",
    # Partner work the person handed over, and what the Partner has dated.
    "pa_work",
    "pp_work",
    "pa_schools",
)

FIELDS: tuple[str, ...] = (
    # The portfolio, and by school type.
    "schools",
    "core_schools",
    "client_schools",
    "core_trained_schools",
    "core_graduate_schools",
    "champion_schools",
    "unmapped_schools",
    # Schools the requirement asks a visit of, and a training of.
    "visit_schools",
    "training_schools",
    # Requirement (annual, or phased for a quarter/month at owner level).
    "visit_slots",
    "staff_expected",
    "partner_expected",
    "core_staff_slots",
    "core_partner_slots",
    "client_slots",
    "client_staff_expected",
    "client_partner_expected",
    "deficit",
    # Claims in the window.
    "staff",
    "staff_core",
    "staff_client",
    "partner_assigned",
    "partner_scheduled",
    "partner_core_assigned",
    "partner_core_scheduled",
    "partner_client_assigned",
    "partner_client_scheduled",
    "staff_verified",
    "partner_verified",
    "returned",
    # The year to the window's end.
    "cum_staff",
    "cum_partner_assigned",
    "cum_partner_scheduled",
    "cum_training",
    "cum_meeting_covered",
    # Gaps.
    "unallocated",
    "staff_gap",
    "partner_gap",
    # Unique schools.
    "any_staff",
    "any_partner_scheduled",
    "any_partner_assigned",
    "any_visit",
    "staff_only",
    "partner_only",
    "both",
    "no_visit",
    # No visit planned and none in a Partner's hands: nobody has it to plan
    # (owner, 2026-10-02: a school assigned to a Partner is the Partner's to
    # plan, and is followed in the Partner table).
    "unplanned",
    # Training.
    "training_slots",
    "training",
    "training_verified",
    "any_training",
    "no_training",
    "training_gap",
    # Clusters and meetings.
    "clustered",
    "unclustered",
    "meeting_covered",
    "meeting_covered_clustered",
    "clustered_no_meeting",
    # Planning status, school by school.
    "fully_planned",
    "partially_planned",
    "not_planned",
    "awaiting_partner",
    # In a Partner's hands (any live Partner work), and client-rule schools
    # whose one visit is planned twice (coverage.duplicate_reasons).
    "with_partner",
    "duplicates",
    *PEOPLE_FIELDS,
)
IDX = {name: index for index, name in enumerate(FIELDS)}
WIDTH = len(FIELDS)
I_FULLY = IDX["fully_planned"]
I_PARTIAL = IDX["partially_planned"]
I_NOT_PLANNED = IDX["not_planned"]
I_AWAITING = IDX["awaiting_partner"]
I_UNALLOCATED = IDX["unallocated"]
I_UNMAPPED = IDX["unmapped_schools"]
I_PEOPLE = tuple(IDX[name] for name in PEOPLE_FIELDS)

#: Requirement fields a quarter or a month phases.
PHASED_FIELDS = (
    "visit_slots",
    "staff_expected",
    "partner_expected",
    "core_staff_slots",
    "core_partner_slots",
    "client_slots",
    "client_staff_expected",
    "client_partner_expected",
    "training_slots",
    "target",
)


def blank() -> list:
    return [0] * WIDTH


def planning_state(claims: Claims) -> str:
    """ "full" | "partial" | "none" — the school's visit slots, year to date —
    or "outside" for a school the requirement asks nothing of."""
    if claims.outside:
        return "outside"
    planned = claims.cum_staff + claims.cum_partner_scheduled
    if claims.visit_slots <= 0:
        return "none" if not planned else "full"
    if planned >= claims.visit_slots:
        return "full"
    return "partial" if planned else "none"


def school_values(school: SchoolFacts, claims: Claims) -> list:
    """One school's contribution to every figure, as a vector."""
    values = blank()
    if not school.is_governed:
        values[IDX["unmapped_schools"]] = 1
        return values
    is_core = school.family == policy.CORE_FAMILY
    v = values
    v[IDX["schools"]] = 1
    type_field = TYPE_FIELDS.get(school.school_type)
    if type_field:
        v[IDX[type_field]] = 1
    if school.clustered:
        v[IDX["clustered"]] = 1
        if claims.meeting_covered:
            v[IDX["meeting_covered_clustered"]] = 1
        else:
            v[IDX["clustered_no_meeting"]] = 1
    else:
        v[IDX["unclustered"]] = 1
    v[IDX["meeting_covered"]] = 1 if claims.meeting_covered else 0
    v[IDX["cum_meeting_covered"]] = 1 if claims.cum_meeting_covered else 0
    if school.with_partner:
        v[IDX["with_partner"]] = 1

    # Training: only the schools the requirement asks a training of.
    if claims.training_slots:
        v[IDX["training_schools"]] = 1
        v[IDX["training_slots"]] = claims.training_slots
        v[IDX["training"]] = claims.training
        v[IDX["training_verified"]] = claims.training_verified
        v[IDX["cum_training"]] = claims.cum_training
        v[IDX["any_training"]] = 1 if claims.any_training else 0
        v[IDX["no_training"]] = 0 if claims.any_training else 1
        v[IDX["training_gap"]] = max(0, claims.training_slots - claims.cum_training)

    if claims.outside:
        # A Champion school: in the portfolio, outside the visit requirement.
        return values

    v[IDX["visit_schools"]] = 1
    v[IDX["visit_slots"]] = claims.visit_slots
    v[IDX["staff_expected"]] = claims.staff_expected
    v[IDX["partner_expected"]] = claims.partner_expected
    if is_core:
        v[IDX["core_staff_slots"]] = claims.staff_expected
        v[IDX["core_partner_slots"]] = claims.partner_expected
        v[IDX["partner_core_assigned"]] = claims.partner_assigned
        v[IDX["partner_core_scheduled"]] = claims.partner_scheduled
    else:
        v[IDX["client_slots"]] = claims.visit_slots
        v[IDX["client_staff_expected"]] = claims.staff_expected
        v[IDX["client_partner_expected"]] = claims.partner_expected
        v[IDX["partner_client_assigned"]] = claims.partner_assigned
        v[IDX["partner_client_scheduled"]] = claims.partner_scheduled
    v[IDX["deficit"]] = claims.deficit
    v[IDX["staff"]] = claims.staff
    v[IDX["staff_core"]] = claims.staff_core
    v[IDX["staff_client"]] = claims.staff_client
    v[IDX["partner_assigned"]] = claims.partner_assigned
    v[IDX["partner_scheduled"]] = claims.partner_scheduled
    v[IDX["staff_verified"]] = claims.staff_verified
    v[IDX["partner_verified"]] = claims.partner_verified
    v[IDX["returned"]] = claims.returned
    v[IDX["cum_staff"]] = claims.cum_staff
    v[IDX["cum_partner_assigned"]] = claims.cum_partner_assigned
    v[IDX["cum_partner_scheduled"]] = claims.cum_partner_scheduled
    v[IDX["unallocated"]] = max(
        0, claims.visit_slots - claims.cum_staff - claims.cum_partner_assigned
    )
    v[IDX["staff_gap"]] = claims.staff_gap
    v[IDX["partner_gap"]] = claims.partner_gap
    staff_planned = claims.any_staff
    partner_planned = claims.any_partner_scheduled
    v[IDX["any_staff"]] = 1 if staff_planned else 0
    v[IDX["any_partner_scheduled"]] = 1 if partner_planned else 0
    v[IDX["any_partner_assigned"]] = 1 if claims.any_partner_assigned else 0
    v[IDX["any_visit"]] = 1 if (staff_planned or partner_planned) else 0
    if staff_planned and partner_planned:
        v[IDX["both"]] = 1
    elif staff_planned:
        v[IDX["staff_only"]] = 1
    elif partner_planned:
        v[IDX["partner_only"]] = 1
    else:
        v[IDX["no_visit"]] = 1
        if not claims.any_partner_assigned:
            v[IDX["unplanned"]] = 1
    state = planning_state(claims)
    v[
        IDX[
            {
                "full": "fully_planned",
                "partial": "partially_planned",
                "none": "not_planned",
            }[state]
        ]
    ] = 1
    if claims.cum_partner_assigned > claims.cum_partner_scheduled:
        v[IDX["awaiting_partner"]] = 1
    if duplicate_reasons(school):
        v[IDX["duplicates"]] = 1
    return values


def state_of(vector) -> str:
    """The planning state a school's vector records (see planning_state)."""
    if vector[I_FULLY]:
        return "full"
    if vector[I_PARTIAL]:
        return "partial"
    if vector[I_NOT_PLANNED]:
        return "none"
    return "outside"


def add_into(total: list, values: list) -> None:
    for index, value in enumerate(values):
        if value:
            total[index] += value


def sum_vectors(vectors: list) -> list:
    """Column sums of many vectors: one pass per figure, in C, rather than a
    Python addition per school per figure (about twice as fast at 50,000)."""
    if not vectors:
        return blank()
    if len(vectors) == 1:
        return list(vectors[0])
    return [sum(column) for column in zip(*vectors)]


def phase(values: list, window: Window) -> list:
    """An owner's tally with its requirement phased to a quarter or a month.

    The gaps are re-read against the phased requirement. Annual windows and
    weeks pass through: a week has no approved phasing, so it keeps the year's
    requirement and the year-to-date gaps, and the page says so.
    """
    if not window.has_phased_target:
        return values
    phased = list(values)
    months = window.months_of_fy
    for name in PHASED_FIELDS:
        annual = values[IDX[name]]
        split = policy.phased_months(annual)
        phased[IDX[name]] = sum(split[month - 1] for month in months)
    g = phased
    g[IDX["unallocated"]] = max(
        0, g[IDX["visit_slots"]] - g[IDX["staff"]] - g[IDX["partner_assigned"]]
    )
    g[IDX["staff_gap"]] = max(0, g[IDX["staff_expected"]] - g[IDX["staff"]])
    g[IDX["partner_gap"]] = max(
        0, g[IDX["partner_expected"]] - g[IDX["partner_assigned"]]
    )
    g[IDX["training_gap"]] = max(0, g[IDX["training_slots"]] - g[IDX["training"]])
    return phased


class Tally:
    """A row's figures, readable by name, with the shares the page shows.

    Shares are computed here, on the server, from the same integers the row
    prints — the browser never divides anything.
    """

    __slots__ = ("values",)

    def __init__(self, values: list | None = None):
        self.values = values if values is not None else blank()

    def __getattr__(self, name):
        # Only the figures are looked up by name. Anything else — including
        # the special names pickle asks for before `values` exists, when a
        # cached tree is read back — is a plain missing attribute.
        if name.startswith("__") or name == "values":
            raise AttributeError(name)
        try:
            return self.values[IDX[name]]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def as_dict(self) -> dict:
        return dict(zip(FIELDS, self.values))

    @staticmethod
    def share(part: int, whole: int) -> int | None:
        return round(100 * part / whole) if whole else None

    @property
    def partner_to_plan(self) -> int:
        """Schools with no visit planned whose visit a Partner holds."""
        return self.no_visit - self.unplanned

    # The page's ratios, each named for the figure it is.
    @property
    def staff_share(self):
        return self.share(self.staff, self.staff_expected)

    @property
    def partner_share(self):
        return self.share(self.partner_assigned, self.partner_expected)

    @property
    def partner_scheduled_share(self):
        return self.share(self.partner_scheduled, self.partner_expected)

    @property
    def planned(self) -> int:
        return self.staff + self.partner_scheduled

    @property
    def visit_share(self):
        return self.share(self.planned, self.visit_slots)

    @property
    def training_share(self):
        return self.share(self.training, self.training_slots)

    @property
    def cluster_share(self):
        return self.share(self.clustered, self.schools)

    @property
    def meeting_share(self):
        return self.share(self.meeting_covered, self.schools)

    @property
    def meeting_clustered_share(self):
        return self.share(self.meeting_covered_clustered, self.clustered)

    @property
    def assigned_unscheduled(self) -> int:
        return max(0, self.partner_assigned - self.partner_scheduled)

    @property
    def cum_planned(self) -> int:
        return self.cum_staff + self.cum_partner_scheduled

    # A person's own plan against the visits their role plans.
    @property
    def plan_share(self):
        return self.share(self.p_visits, self.target)

    @property
    def plan_remaining(self) -> int:
        return max(0, self.target - self.p_visits)

    @property
    def partner_plan_share(self):
        return self.share(self.pp_work, self.pa_work)

    @property
    def partner_waiting(self) -> int:
        return max(0, self.pa_work - self.pp_work)

    @property
    def unique_visit_share(self):
        return self.share(self.any_visit, self.visit_schools)

    @property
    def reach(self) -> int:
        """The visits staff could plan at the schools held: 2 per Core
        school, 1 per Client, Core Trained and Core Graduate school."""
        return 2 * self.core_schools + (
            self.client_schools + self.core_trained_schools + self.core_graduate_schools
        )

    @property
    def shortfall(self) -> int:
        """How far the schools held fall short of the person's target."""
        return max(0, self.target - self.reach) if self.target else 0


@dataclass
class OwnerRow:
    key: str
    name: str
    kind: str  # "cceo" | "pl_personal" | "other" | "unassigned"
    role: str
    lead_key: str
    tally: Tally
    ceiling: int = 0
    # The schools this person holds, by the Partner working them (school
    # side): partner id → Tally.
    partners: dict = field(default_factory=dict)
    # The work this person handed to each Partner (their own plan): partner
    # id → Tally carrying pa_work, pp_work and pa_schools.
    assigned: dict = field(default_factory=dict)
    staff_only_tally: Tally | None = None
    open_followups: int = 0

    @property
    def label(self) -> str:
        return self.name


@dataclass
class LeadRow:
    key: str
    name: str
    tally: Tally
    owners: list = field(default_factory=list)
    open_followups: int = 0
    is_no_lead: bool = False


@dataclass
class Tree:
    country: Tally
    leads: list
    window: Window
    # school id → (owner key, lead key) for everything the filters kept.
    placement: dict = field(default_factory=dict)
    # school type → Tally of the kept schools of that type.
    by_type: dict = field(default_factory=dict)


class PlanningHierarchyService:
    """The fold, as one importable surface."""

    fields = FIELDS
    school_values = staticmethod(school_values)
    add_into = staticmethod(add_into)
    phase = staticmethod(phase)
    planning_state = staticmethod(planning_state)
