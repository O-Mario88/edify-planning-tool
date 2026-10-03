"""The planning rulebook the Country Director's figures are counted by.

Owner, 2026-10-01, after the dashboard audit: the page counted school slots
credited to whoever holds the school, against a requirement built from those
schools. What the Country Director follows up on is each Programme Lead's and
CCEO's own plan against the visits the role plans in a year. This module is
the one place those rules are written down; every figure that follows them
reads it, so a card, a chart, a table and the Planning Monitor cannot each
restate a 560, a list of visit types or a definition of "planned".

**Who plans.** A Programme Lead plans 280 visits a year and a CCEO 560. A
person is a Lead or a CCEO by the roles they HOLD, not the one they happen to
be switched to: a Lead who also holds another role and is using it today is
still a Lead with a team. Somebody holding both is a Lead.

**Which visits count.** Two kinds, delivered by staff: In-school Training and
Follow up (owner, 2026-10-02: "the only visits that count are in-school
visits and Training Follow Up visits"). An in-school training is one visit
and one training — its companion visit is the same mission written twice for
Salesforce and never counts again. Data collection (SSA Support) counted as
a third kind from 2026-10-01 until the owner took it out the next day: it is
collection, not support, so it is not a school's visit, not a Core package
visit and not one of a person's 560 or 280, and no school is limited in how
many it takes. Donor, content/story, social and invitation visits are the
same: real work, shown and costed, and not among the visits a person is
expected to plan.

**What a school needs in a year.** By its own type, never a family:

===============  ==========================  ==========================
School type      Visits                      Trainings
===============  ==========================  ==========================
Core             4 (2 staff + 2 Partner)     4 (2 staff + 2 Partner)
Client           1 (staff or a Partner)      1
Core Trained     1 (staff or a Partner)      1
Core Graduate    1 (staff or a Partner)      1
Champion         none (outreach only)        none
===============  ==========================  ==========================

**How a person's year is shared out** (owner, 2026-10-03; ``workload``). The
280 or 560 is a ceiling on staff visits. The Core schools a person holds take
theirs first, two each; the capacity left takes one visit at each Client,
Core Trained and Core Graduate school until it runs out; every school past
that is the Partner's. So the Partner's target is the other two visits at each
Core school plus the schools beyond staff capacity ("the overflow should be
the partner target"), and a person holding too few schools to reach the
ceiling hands nothing over. Trainings run beside the visits and use none of
the ceiling: a Core school's four are two staff and two Partner, and a
school's one follows its visit. Core schools alone at or past the ceiling
(``OVER_CAPACITY_CORE_ONLY``) leave no staff visit for any other school.

**The ceiling warns; it never refuses** (owner, 2026-10-03: "platform should
not refuse just warn and let it through"). A visit planned past it is saved,
counted and SHOWN as over the ceiling, on the plan and to whoever follows it.

**Partners.** Staff assign a school; the Partner sets the date. *Assigned* is
every school in a Partner's hands; *Partner planned* is the part of it the
Partner has dated, and it is nothing until a Partner does. A date staff set
for a Partner (a certified agency booked onto a day) is assigned, not Partner
planned.

**Planned twice.** A Client, Core Trained or Core Graduate school is visited
by staff or by a Partner, never both: two counted visits in one year are a
duplicate, and so is a school that staff planned and a Partner holds. A data
collection visit is neither, whoever makes it and however many there are.
A Core school takes two staff visits and two Partner visits; more than two on
either side is more than it takes. Nothing here removes a plan: a duplicate
is counted once as coverage and SHOWN, so the Country Director can have it
looked at.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Case, CharField, Q, Value, When

from apps.core.enums import SchoolType
from apps.planning.country_oversight import policy

#: Named in every cache key and export, so a figure says which rules made it.
RULES_VERSION = "2026-10-03.1"

# ── Who plans ────────────────────────────────────────────────────────────────
PROGRAM_LEAD_ROLE = policy.PROGRAM_LEAD_ROLE
CCEO_ROLE = policy.CCEO_ROLE

#: The visits each role plans in a year (owner, 2026-09-28 and 2026-09-29).
VISIT_TARGETS: dict[str, int] = {PROGRAM_LEAD_ROLE: 280, CCEO_ROLE: 560}

ROLE_LABELS = {PROGRAM_LEAD_ROLE: "Programme Lead", CCEO_ROLE: "CCEO"}

NO_LEAD_KEY = "__no_lead__"
NO_LEAD_LABEL = "No Programme Lead"


def planning_role(roles, active_role: str | None = None) -> str | None:
    """The planning role somebody holds: Programme Lead before CCEO, or None.

    ``roles`` is every role on the account; ``active_role`` the one in use,
    read as held too so an account whose role list was never filled in still
    counts.
    """
    held = {str(role) for role in (roles or []) if role}
    if active_role:
        held.add(str(active_role))
    if PROGRAM_LEAD_ROLE in held:
        return PROGRAM_LEAD_ROLE
    if CCEO_ROLE in held:
        return CCEO_ROLE
    return None


def target_for(role: str | None) -> int:
    return VISIT_TARGETS.get(str(role or ""), 0)


@dataclass(frozen=True)
class Person:
    """A Programme Lead or a CCEO, in both of their id spaces."""

    key: str  # the StaffProfile id
    name: str
    role: str  # PROGRAM_LEAD_ROLE | CCEO_ROLE
    user_id: str = ""
    # The role the account is switched to today, when it is not ``role``.
    role_in_use: str = ""
    ids: frozenset = field(default_factory=frozenset)

    @property
    def target(self) -> int:
        return target_for(self.role)

    @property
    def is_lead(self) -> bool:
        return self.role == PROGRAM_LEAD_ROLE

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, "")


@dataclass
class Team:
    """A Programme Lead and the CCEOs who report to them, the Lead first."""

    key: str
    name: str
    people: list = field(default_factory=list)

    @property
    def is_no_lead(self) -> bool:
        return self.key == NO_LEAD_KEY

    @property
    def target(self) -> int:
        return sum(person.target for person in self.people)


def roster(country: str = "") -> list[Team]:
    """Every Programme Lead with their CCEOs, then the CCEOs with no Lead.

    ``country`` keeps a country reader inside their country; blank reads the
    deployment. A CCEO linked to several Leads is filed under the first by
    name, so the country counts them once. In three queries.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    profiles = StaffProfile.objects.filter(
        deleted_at__isnull=True,
        user__is_active=True,
        user__deleted_at__isnull=True,
    ).filter(
        Q(user__roles__overlap=[PROGRAM_LEAD_ROLE, CCEO_ROLE])
        | Q(user__active_role__in=[PROGRAM_LEAD_ROLE, CCEO_ROLE])
    )
    if country:
        profiles = profiles.filter(Q(country=country) | Q(country=""))
    people: dict[str, Person] = {}
    for profile in profiles.select_related("user"):
        user = profile.user
        role = planning_role(user.roles, user.active_role)
        if role is None:
            continue
        in_use = user.active_role or ""
        people[profile.id] = Person(
            key=str(profile.id),
            name=user.name or user.email or str(profile.id),
            role=role,
            user_id=str(profile.user_id or ""),
            role_in_use="" if in_use == role else in_use,
            ids=frozenset(str(i) for i in (profile.id, profile.user_id) if i),
        )

    def by_name(person: Person):
        return (person.name.casefold(), person.key)

    leads = sorted((p for p in people.values() if p.is_lead), key=by_name)
    lead_order = {lead.key: index for index, lead in enumerate(leads)}
    members: dict[str, list[Person]] = {lead.key: [] for lead in leads}
    placed: dict[str, str] = {}
    for supervisor_id, supervisee_id in StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=list(members), supervisee_id__in=list(people)
    ).values_list("supervisor_id", "supervisee_id"):
        person = people[supervisee_id]
        if person.is_lead or supervisor_id == supervisee_id:
            continue
        current = placed.get(supervisee_id)
        if current is None or lead_order[supervisor_id] < lead_order[current]:
            placed[supervisee_id] = supervisor_id
    for supervisee_id, supervisor_id in placed.items():
        members[supervisor_id].append(people[supervisee_id])

    teams = [
        Team(
            key=lead.key,
            name=lead.name,
            people=[lead, *sorted(members[lead.key], key=by_name)],
        )
        for lead in leads
    ]
    loose = sorted(
        (p for p in people.values() if not p.is_lead and p.key not in placed),
        key=by_name,
    )
    if loose:
        teams.append(Team(key=NO_LEAD_KEY, name=NO_LEAD_LABEL, people=loose))
    return teams


# ── Which visits count ───────────────────────────────────────────────────────
KIND_SSA = "ssa_support"
KIND_IN_SCHOOL = "in_school_training"
KIND_FOLLOW_UP = "follow_up"

KIND_LABELS = {
    KIND_SSA: "SSA Support",
    KIND_IN_SCHOOL: "In-school Training",
    KIND_FOLLOW_UP: "Follow up",
}
#: The kinds that count, in the order the pages show them. ``KIND_SSA`` keeps
#: its name and label for the lists that show a data collection visit; it is
#: no longer one of them (owner, 2026-10-02).
KIND_ORDER = (KIND_FOLLOW_UP, KIND_IN_SCHOOL)

#: The visit an in-school training writes beside itself: the same mission.
COMPANION_PURPOSE = "in_school_training_delivery_visit"

#: Real visits nobody is expected to plan a number of.
OUTREACH_PURPOSES = (
    "donor_visit",
    "story_gathering",
    "school_invitation",
    "social_visit",
)
OUTREACH_TYPES = (
    "donor_visit",
    "story_gathering_visit",
    "school_invitation",
    "social_visit",
)

#: Data collection: SSA Support and the assessment visits. Shown and costed,
#: counted nowhere and limited nowhere (owner, 2026-10-02).
DATA_COLLECTION_PURPOSES = ("ssa_support",)
DATA_COLLECTION_TYPES = (
    "school_visit_ssa_collection",
    "baseline_ssa_visit",
    "partner_ssa_collection",
    "ssa_activity",
    "core_assessment_visit",
)

#: The purpose a planner chose says what kind of visit it is ...
_PURPOSE_KIND = {
    "in_school_training": KIND_IN_SCHOOL,
    # Retired purpose the owner called "the same as In-school training".
    "in_school_coaching": KIND_IN_SCHOOL,
    "training_follow_up": KIND_FOLLOW_UP,
}
#: ... and a row written without one is read by its activity type. Every
#: counted type is here: a type left out is never a counted visit.
_TYPE_KIND = {
    "in_school_training": KIND_IN_SCHOOL,
    "in_school_coaching_visit": KIND_IN_SCHOOL,
    "training_follow_up_visit": KIND_FOLLOW_UP,
    "follow_up_visit": KIND_FOLLOW_UP,
    "school_visit": KIND_FOLLOW_UP,
    "coaching_visit": KIND_FOLLOW_UP,
    "in_school_support": KIND_FOLLOW_UP,
    "core_visit": KIND_FOLLOW_UP,
}
COUNTED_VISIT_TYPES: tuple[str, ...] = tuple(_TYPE_KIND)


def not_outside_ssa_q(prefix: str = "") -> Q:
    """Rows that are not the work of a project no SSA intervention measures.

    Owner, 2026-10-02: "Alumni is not an intervention ... it is not measured
    via ssa." A visit under such a project is not one of the school's support
    visits: it is not among the 560 an officer plans, it does not put the
    school in a Partner's hands, and it closes no gap on a monitor. The same
    line `apps.planning.visit_gate` and the Core package already draw.
    Activities and hand-overs both carry ``project_id``.
    """
    from apps.projects.models import projects_outside_ssa

    outside = list(projects_outside_ssa())
    if not outside:
        return Q()
    return ~Q(**{f"{prefix}project_id__in": outside})


def visit_kind(
    activity_type: str | None,
    purpose_type: str | None = None,
    project_id: str | None = None,
) -> str | None:
    """The counted kind of an activity of this shape, or None when it is not
    a counted visit. ``counted_visit_q`` and ``visit_kind_case`` say the same
    for rows in the database."""
    activity_type = str(activity_type or "")
    purpose_type = str(purpose_type or "")
    if activity_type not in _TYPE_KIND:
        return None
    if project_id:
        from apps.projects.models import is_outside_ssa

        if is_outside_ssa(project_id):
            return None
    if purpose_type == COMPANION_PURPOSE or purpose_type in OUTREACH_PURPOSES:
        return None
    if purpose_type in DATA_COLLECTION_PURPOSES:
        return None
    return _PURPOSE_KIND.get(purpose_type) or _TYPE_KIND[activity_type]


def is_data_collection(
    activity_type: str | None, purpose_type: str | None = None
) -> bool:
    """Whether work of this shape is a data collection visit: by its type, or
    by the purpose a planner chose on a visit of any other type (a Core
    Schools visit booked as SSA Support is a ``core_visit``)."""
    return (
        str(activity_type or "") in DATA_COLLECTION_TYPES
        or str(purpose_type or "") in DATA_COLLECTION_PURPOSES
    )


def data_collection_q(prefix: str = "") -> Q:
    """``is_data_collection`` for rows in the database."""
    return Q(**{f"{prefix}activity_type__in": DATA_COLLECTION_TYPES}) | Q(
        **{f"{prefix}purpose_type__in": DATA_COLLECTION_PURPOSES}
    )


def is_uncounted_visit(activity_type: str | None, purpose_type=None) -> bool:
    """A donor, story, invitation or social visit, or a data collection
    visit: ``outreach_visit_q`` for a row already read at a school."""
    activity_type = str(activity_type or "")
    purpose_type = str(purpose_type or "")
    return (
        activity_type in OUTREACH_TYPES
        or activity_type in DATA_COLLECTION_TYPES
        or (
            activity_type in COUNTED_VISIT_TYPES
            and purpose_type in (*OUTREACH_PURPOSES, *DATA_COLLECTION_PURPOSES)
        )
    )


def handover_data_collection_q(prefix: str = "") -> Q:
    """Partner hand-overs that ask for data collection: assigned on any
    school, and no part of "the schools assigned to Partners" for an
    in-school training or a follow up (owner, 2026-10-02)."""
    return Q(**{f"{prefix}purpose_of_visit__in": DATA_COLLECTION_PURPOSES}) | Q(
        **{f"{prefix}expected_activity_type__in": DATA_COLLECTION_TYPES}
    )


def counted_visit_q(prefix: str = "") -> Q:
    """Activities that are a counted visit at a school, whoever delivers them."""
    return (
        Q(**{f"{prefix}activity_type__in": COUNTED_VISIT_TYPES})
        & Q(**{f"{prefix}school_id__isnull": False})
        & Q(**{f"{prefix}cluster_id__isnull": True})
        & ~Q(**{f"{prefix}purpose_type": COMPANION_PURPOSE})
        & ~Q(**{f"{prefix}purpose_type__in": OUTREACH_PURPOSES})
        & ~Q(**{f"{prefix}purpose_type__in": DATA_COLLECTION_PURPOSES})
        & not_outside_ssa_q(prefix)
    )


def visit_kind_case(prefix: str = "") -> Case:
    """``visit_kind`` as a column, for rows ``counted_visit_q`` already kept."""
    whens = [
        When(**{f"{prefix}purpose_type": purpose}, then=Value(kind))
        for purpose, kind in _PURPOSE_KIND.items()
    ]
    whens += [
        When(**{f"{prefix}activity_type": activity_type}, then=Value(kind))
        for activity_type, kind in _TYPE_KIND.items()
    ]
    return Case(*whens, default=Value(KIND_FOLLOW_UP), output_field=CharField())


def kind_q(kind: str, prefix: str = "") -> Q:
    """Rows ``counted_visit_q`` kept that are of this kind (``visit_kind``)."""
    purposes = [p for p, k in _PURPOSE_KIND.items() if k == kind]
    types = [t for t, k in _TYPE_KIND.items() if k == kind]
    return Q(**{f"{prefix}purpose_type__in": purposes}) | (
        Q(**{f"{prefix}activity_type__in": types})
        & ~Q(**{f"{prefix}purpose_type__in": list(_PURPOSE_KIND)})
    )


def outreach_visit_q(prefix: str = "") -> Q:
    """Donor, story, invitation and social visits, and data collection, at a
    school: shown beside the counted visits, never among them."""
    return (
        Q(**{f"{prefix}school_id__isnull": False})
        & Q(**{f"{prefix}cluster_id__isnull": True})
        & (
            Q(**{f"{prefix}activity_type__in": OUTREACH_TYPES})
            | Q(**{f"{prefix}activity_type__in": DATA_COLLECTION_TYPES})
            | (
                Q(**{f"{prefix}activity_type__in": COUNTED_VISIT_TYPES})
                & Q(
                    **{
                        f"{prefix}purpose_type__in": (
                            *OUTREACH_PURPOSES,
                            *DATA_COLLECTION_PURPOSES,
                        )
                    }
                )
            )
        )
    )


def staff_delivery_q(prefix: str = "") -> Q:
    return ~Q(**{f"{prefix}delivery_type": "partner"})


def planned_q(prefix: str = "") -> Q:
    """Planned: a scheduled-or-later state with a date on it (policy)."""
    return Q(**{f"{prefix}status__in": policy.PLANNED_STATES}) & (
        Q(**{f"{prefix}planned_date__isnull": False})
        | Q(**{f"{prefix}scheduled_date__isnull": False})
    )


#: The yearly count at a client-rule school (apps.planning.visit_gate): its
#: one support visit. SSA Support was a second count until the owner took data
#: collection out of every count (2026-10-02); ``POOL_SSA`` stays for the
#: callers that still name it and is always empty.
POOL_SSA = "ssa"
POOL_SUPPORT = "support"


def pool_of(kind: str | None) -> str | None:
    if kind is None:
        return None
    return POOL_SUPPORT


# ── What a school needs ──────────────────────────────────────────────────────
TYPE_ORDER: tuple[str, ...] = (
    SchoolType.CORE.value,
    SchoolType.CLIENT.value,
    SchoolType.CORE_TRAINED.value,
    SchoolType.CORE_GRADUATE.value,
    SchoolType.CHAMPION.value,
)
TYPE_LABELS = {
    SchoolType.CORE.value: "Core",
    SchoolType.CLIENT.value: "Client",
    SchoolType.CORE_TRAINED.value: "Core Trained",
    SchoolType.CORE_GRADUATE.value: "Core Graduate",
    SchoolType.CHAMPION.value: "Champion",
}
#: The types whose one visit is staff's or a Partner's, never both.
CLIENT_RULE_TYPES: tuple[str, ...] = (
    SchoolType.CLIENT.value,
    SchoolType.CORE_TRAINED.value,
    SchoolType.CORE_GRADUATE.value,
)
#: Types with a visit or a training requirement: the planning portfolio.
PLANNED_TYPES: tuple[str, ...] = (SchoolType.CORE.value, *CLIENT_RULE_TYPES)


def type_label(school_type: str | None) -> str:
    value = str(school_type or "")
    return TYPE_LABELS.get(value) or value.replace("_", " ").title() or "No type"


@dataclass(frozen=True)
class TypeRequirement:
    """One school's year. ``either`` is a slot staff or a Partner may take."""

    staff_visits: int = 0
    partner_visits: int = 0
    either_visits: int = 0
    staff_trainings: int = 0
    partner_trainings: int = 0
    either_trainings: int = 0

    @property
    def visits(self) -> int:
        return self.staff_visits + self.partner_visits + self.either_visits

    @property
    def trainings(self) -> int:
        return self.staff_trainings + self.partner_trainings + self.either_trainings

    @property
    def staff_reach(self) -> int:
        """The most visits staff can plan at one school of this type."""
        return self.staff_visits + self.either_visits


NO_REQUIREMENT = TypeRequirement()
REQUIREMENTS: dict[str, TypeRequirement] = {
    SchoolType.CORE.value: TypeRequirement(
        staff_visits=2, partner_visits=2, staff_trainings=2, partner_trainings=2
    ),
    SchoolType.CLIENT.value: TypeRequirement(either_visits=1, either_trainings=1),
    SchoolType.CORE_TRAINED.value: TypeRequirement(either_visits=1, either_trainings=1),
    # As a client school (owner, 2026-10-02: "core trained, core graduate and
    # client schools should be treated the same"). From 2026-09-25 until then
    # it took its visit and no training, so a training planned for one was
    # counted nowhere and the school read as having none.
    SchoolType.CORE_GRADUATE.value: TypeRequirement(
        either_visits=1, either_trainings=1
    ),
    # Donor and story visits only: outside the requirement (owner, 2026-10-01).
    SchoolType.CHAMPION.value: NO_REQUIREMENT,
}


def requirement_for(school_type: str | None) -> TypeRequirement:
    return REQUIREMENTS.get(str(school_type or ""), NO_REQUIREMENT)


#: The types that take a training in the year: Core, Client, Core Trained
#: and Core Graduate. A Champion school takes neither a visit nor a training,
#: so a page that lists schools "with no training planned" lists only these.
TRAINED_TYPES: tuple[str, ...] = tuple(
    school_type for school_type in TYPE_ORDER if REQUIREMENTS[school_type].trainings
)


def takes_training(school_type: str | None) -> bool:
    return str(school_type or "") in TRAINED_TYPES


def portfolio_reach(schools_by_type: dict) -> int:
    """The visits staff could plan across a portfolio: 2 per Core school and
    1 per Client, Core Trained and Core Graduate school. Below the person's
    target, the target cannot be met from the schools they hold."""
    return sum(
        requirement_for(school_type).staff_reach * int(count or 0)
        for school_type, count in schools_by_type.items()
    )


# ── How a person's year is shared out ────────────────────────────────────────
#: Raised when a person's Core schools alone take the whole ceiling: every
#: other school they hold is the Partner's.
OVER_CAPACITY_CORE_ONLY = "OVER_CAPACITY_CORE_ONLY"


@dataclass(frozen=True)
class Workload:
    """One person's year, shared between staff and the Partner (module doc).

    ``cap`` is the staff visit ceiling (0 for somebody who is neither a Lead
    nor a CCEO: no staff capacity stands behind their schools). The schools
    are the ones the person holds; ``client_schools`` are the Client, Core
    Trained and Core Graduate schools together.
    """

    cap: int
    core_schools: int
    client_schools: int

    @property
    def staff_core_visits(self) -> int:
        return REQUIREMENTS[SchoolType.CORE.value].staff_visits * self.core_schools

    @property
    def partner_core_visits(self) -> int:
        return REQUIREMENTS[SchoolType.CORE.value].partner_visits * self.core_schools

    @property
    def staff_core_trainings(self) -> int:
        return REQUIREMENTS[SchoolType.CORE.value].staff_trainings * self.core_schools

    @property
    def partner_core_trainings(self) -> int:
        return REQUIREMENTS[SchoolType.CORE.value].partner_trainings * self.core_schools

    @property
    def remaining_capacity(self) -> int:
        """The ceiling left once the Core schools have theirs."""
        return max(0, self.cap - self.staff_core_visits)

    @property
    def staff_client_visits(self) -> int:
        return min(self.client_schools, self.remaining_capacity)

    @property
    def partner_client_visits(self) -> int:
        """The schools beyond staff capacity: the Partner's (the spillover)."""
        return self.client_schools - self.staff_client_visits

    @property
    def staff_visits(self) -> int:
        return self.staff_core_visits + self.staff_client_visits

    @property
    def partner_visits(self) -> int:
        """The Partner's target: its half of each Core package and the
        schools beyond staff capacity."""
        return self.partner_core_visits + self.partner_client_visits

    @property
    def staff_trainings(self) -> int:
        """A school's one training follows its one visit."""
        return self.staff_core_trainings + self.staff_client_visits

    @property
    def partner_trainings(self) -> int:
        return self.partner_core_trainings + self.partner_client_visits

    @property
    def core_over(self) -> int:
        """Core staff visits the ceiling cannot hold."""
        return max(0, self.staff_core_visits - self.cap) if self.cap else 0

    @property
    def core_only(self) -> bool:
        return bool(
            self.cap and self.core_schools and self.staff_core_visits >= self.cap
        )

    @property
    def warning(self) -> str:
        return OVER_CAPACITY_CORE_ONLY if self.core_only else ""


def workload(cap: int, core_schools: int, client_schools: int) -> Workload:
    return Workload(
        cap=max(0, int(cap or 0)),
        core_schools=max(0, int(core_schools or 0)),
        client_schools=max(0, int(client_schools or 0)),
    )


def workload_for(role: str | None, schools_by_type: dict) -> Workload:
    """The share-out for somebody of this role holding these schools
    (school type → how many)."""
    return workload(
        target_for(role),
        schools_by_type.get(SchoolType.CORE.value, 0),
        sum(int(schools_by_type.get(t, 0) or 0) for t in CLIENT_RULE_TYPES),
    )


def over_ceiling(planned: int, cap: int) -> int:
    """Counted visits planned past the ceiling. Nothing refuses them (the
    module doc); this is the number every page shows."""
    return max(0, int(planned or 0) - int(cap)) if cap else 0


# ── Partners: assigned, and planned by the Partner ───────────────────────────
#: Who set the date on a Partner-delivered activity (Activity.partner_date_set_by).
DATED_BY_PARTNER = "partner"
DATED_BY_STAFF = "staff"

#: Hand-overs that no longer put a school in a Partner's hands.
CLOSED_HANDOVER_STATUSES = (
    "returned_to_staff",
    "returned",
    "withdrawn",
    "cancelled",
    "rejected",
)


def partner_delivery_q(prefix: str = "") -> Q:
    return Q(**{f"{prefix}delivery_type": "partner"})


def partner_planned_q(prefix: str = "") -> Q:
    """Partner-delivered work the PARTNER has dated.

    Rows written before the date's author was recorded carry no mark; they
    are read as the Partner's unless staff booked a certified agency onto the
    day, which is the one path where staff chose it.
    """
    from apps.core.enums import ExecutorType

    return (
        partner_delivery_q(prefix)
        & planned_q(prefix)
        & (
            Q(**{f"{prefix}partner_date_set_by": DATED_BY_PARTNER})
            | (
                Q(**{f"{prefix}partner_date_set_by": ""})
                & ~Q(
                    **{
                        f"{prefix}executor_type": ExecutorType.CERTIFIED_PARTNER_AGENCY.value
                    }
                )
            )
        )
    )


def partner_held_q(prefix: str = "") -> Q:
    """Partner-delivered work that is live: handed over, dated or delivered."""
    return partner_delivery_q(prefix) & Q(
        **{
            f"{prefix}status__in": (
                *policy.PLANNED_STATES,
                str(policy.S.ASSIGNED_TO_PARTNER),
            )
        }
    )


def is_partner_principal(principal) -> bool:
    """Is the person acting a Partner's own user?"""
    from apps.partners.engagement_services import PARTNER_ROLES

    return (getattr(principal, "active_role", "") or "") in PARTNER_ROLES


def date_author(principal, current: str = "", *, already_dated: bool = False) -> str:
    """Who a Partner activity's date belongs to after ``principal`` sets it.

    A Partner's own date is the Partner's. Staff moving a date somebody else
    chose change nothing about whose plan it is; staff putting the FIRST date
    on Partner work make it a staff date.
    """
    if is_partner_principal(principal):
        return DATED_BY_PARTNER
    if current or already_dated:
        return current
    return DATED_BY_STAFF


# ── Planned twice ────────────────────────────────────────────────────────────
DUPLICATE_BOTH = "both"
DUPLICATE_STAFF = "staff"
DUPLICATE_PARTNER = "partner"
DUPLICATE_STAFF_OVER = "staff_over"
DUPLICATE_PARTNER_OVER = "partner_over"
DUPLICATE_LABELS = {
    DUPLICATE_BOTH: "Planned by staff and held by a Partner",
    DUPLICATE_STAFF: "The same kind of staff visit planned twice",
    DUPLICATE_PARTNER: "The same kind of Partner visit assigned twice",
    DUPLICATE_STAFF_OVER: "More staff visits than a Core school takes",
    DUPLICATE_PARTNER_OVER: "More Partner visits than a Core school takes",
}


def duplicate_reasons(
    school_type: str | None, staff_by_pool: dict, partner_by_pool: dict
) -> tuple[str, ...]:
    """Why a school's year is planned more often than it should be, if it is.

    ``staff_by_pool`` and ``partner_by_pool`` map POOL_SSA / POOL_SUPPORT to
    the year's count on that side (a Partner's includes work not yet dated).
    """
    school_type = str(school_type or "")
    staff, partner = sum(staff_by_pool.values()), sum(partner_by_pool.values())
    reasons = []
    if school_type in CLIENT_RULE_TYPES:
        if staff and partner:
            reasons.append(DUPLICATE_BOTH)
        if any(count > 1 for count in staff_by_pool.values()):
            reasons.append(DUPLICATE_STAFF)
        if any(count > 1 for count in partner_by_pool.values()):
            reasons.append(DUPLICATE_PARTNER)
    else:
        need = requirement_for(school_type)
        if need.staff_visits and staff > need.staff_visits:
            reasons.append(DUPLICATE_STAFF_OVER)
        if need.partner_visits and partner > need.partner_visits:
            reasons.append(DUPLICATE_PARTNER_OVER)
    return tuple(reasons)


def check() -> None:
    """The rulebook agrees with the enums it reads."""
    from apps.core.enums import ActivityType

    unknown = (
        set(COUNTED_VISIT_TYPES) | set(OUTREACH_TYPES) | set(DATA_COLLECTION_TYPES)
    )
    unknown -= set(ActivityType.values)
    if unknown:
        raise ValueError(f"rulebook names unknown activity types: {sorted(unknown)}")
    overlap = set(COUNTED_VISIT_TYPES) & (
        set(OUTREACH_TYPES) | set(DATA_COLLECTION_TYPES)
    )
    if overlap:
        raise ValueError(f"types both counted and not counted: {sorted(overlap)}")
    missing = set(SchoolType.values) - set(REQUIREMENTS)
    if missing:
        raise ValueError(
            f"school types with no requirement in the rulebook: {sorted(missing)}"
        )
