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

**Which visits count.** Three kinds, delivered by staff: SSA Support,
In-school Training and Follow up. An in-school training is one visit and one
training — its companion visit is the same mission written twice for
Salesforce and never counts again. Donor, content/story, social and
invitation visits are real work and are shown, but they are not among the
visits a person is expected to plan.

**What a school needs in a year.** By its own type, never a family:

===============  ==========================  ==========================
School type      Visits                      Trainings
===============  ==========================  ==========================
Core             4 (2 staff + 2 Partner)     4 (2 staff + 2 Partner)
Client           1 (staff or a Partner)      1
Core Trained     1 (staff or a Partner)      1
Core Graduate    1 (staff or a Partner)      none
Champion         none (outreach only)        none
===============  ==========================  ==========================

**Partners.** Staff assign a school; the Partner sets the date. *Assigned* is
every school in a Partner's hands; *Partner planned* is the part of it the
Partner has dated, and it is nothing until a Partner does. A date staff set
for a Partner (a certified agency booked onto a day) is assigned, not Partner
planned.

**Planned twice.** A Client, Core Trained or Core Graduate school is visited
by staff or by a Partner, never both. A support visit and an SSA Support in
one year are two planned visits at one covered school; two of the same kind
are a duplicate, and so is a school that staff planned and a Partner holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Case, CharField, Q, Value, When

from apps.core.enums import SchoolType
from apps.planning.country_oversight import policy

#: Named in every cache key and export, so a figure says which rules made it.
RULES_VERSION = "2026-10-01.1"

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
KIND_ORDER = (KIND_FOLLOW_UP, KIND_IN_SCHOOL, KIND_SSA)

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

#: The purpose a planner chose says what kind of visit it is ...
_PURPOSE_KIND = {
    "ssa_support": KIND_SSA,
    "in_school_training": KIND_IN_SCHOOL,
    # Retired purpose the owner called "the same as In-school training".
    "in_school_coaching": KIND_IN_SCHOOL,
    "training_follow_up": KIND_FOLLOW_UP,
}
#: ... and a row written without one is read by its activity type. Every
#: counted type is here: a type left out is never a counted visit.
_TYPE_KIND = {
    "school_visit_ssa_collection": KIND_SSA,
    "baseline_ssa_visit": KIND_SSA,
    "partner_ssa_collection": KIND_SSA,
    "ssa_activity": KIND_SSA,
    "core_assessment_visit": KIND_SSA,
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


def visit_kind(
    activity_type: str | None, purpose_type: str | None = None
) -> str | None:
    """The counted kind of an activity of this shape, or None when it is not
    a counted visit. ``counted_visit_q`` and ``visit_kind_case`` say the same
    for rows in the database."""
    activity_type = str(activity_type or "")
    purpose_type = str(purpose_type or "")
    if activity_type not in _TYPE_KIND:
        return None
    if purpose_type == COMPANION_PURPOSE or purpose_type in OUTREACH_PURPOSES:
        return None
    return _PURPOSE_KIND.get(purpose_type) or _TYPE_KIND[activity_type]


def counted_visit_q(prefix: str = "") -> Q:
    """Activities that are a counted visit at a school, whoever delivers them."""
    return (
        Q(**{f"{prefix}activity_type__in": COUNTED_VISIT_TYPES})
        & Q(**{f"{prefix}school_id__isnull": False})
        & Q(**{f"{prefix}cluster_id__isnull": True})
        & ~Q(**{f"{prefix}purpose_type": COMPANION_PURPOSE})
        & ~Q(**{f"{prefix}purpose_type__in": OUTREACH_PURPOSES})
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


def outreach_visit_q(prefix: str = "") -> Q:
    """Donor, story, invitation and social visits at a school: shown beside
    the counted visits, never among them."""
    return Q(**{f"{prefix}school_id__isnull": False}) & (
        Q(**{f"{prefix}activity_type__in": OUTREACH_TYPES})
        | (
            Q(**{f"{prefix}activity_type__in": COUNTED_VISIT_TYPES})
            & Q(**{f"{prefix}purpose_type__in": OUTREACH_PURPOSES})
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


#: The two yearly counts at a client-rule school (apps.planning.visit_gate):
#: SSA Support is counted apart from the support visit.
POOL_SSA = "ssa"
POOL_SUPPORT = "support"


def pool_of(kind: str | None) -> str | None:
    if kind is None:
        return None
    return POOL_SSA if kind == KIND_SSA else POOL_SUPPORT


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
    # Client for its visits (owner, 2026-09-28), untrained (owner, 2026-09-25).
    SchoolType.CORE_GRADUATE.value: TypeRequirement(either_visits=1),
    # Donor and story visits only: outside the requirement (owner, 2026-10-01).
    SchoolType.CHAMPION.value: NO_REQUIREMENT,
}


def requirement_for(school_type: str | None) -> TypeRequirement:
    return REQUIREMENTS.get(str(school_type or ""), NO_REQUIREMENT)


def portfolio_reach(schools_by_type: dict) -> int:
    """The visits staff could plan across a portfolio: 2 per Core school and
    1 per Client, Core Trained and Core Graduate school. Below the person's
    target, the target cannot be met from the schools they hold."""
    return sum(
        requirement_for(school_type).staff_reach * int(count or 0)
        for school_type, count in schools_by_type.items()
    )


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
DUPLICATE_LABELS = {
    DUPLICATE_BOTH: "Planned by staff and held by a Partner",
    DUPLICATE_STAFF: "The same kind of staff visit planned twice",
    DUPLICATE_PARTNER: "The same kind of Partner visit assigned twice",
}


def duplicate_reasons(
    school_type: str | None, staff_by_pool: dict, partner_by_pool: dict
) -> tuple[str, ...]:
    """Why a client-rule school's year is planned twice, if it is.

    ``staff_by_pool`` and ``partner_by_pool`` map POOL_SSA / POOL_SUPPORT to
    the year's count on that side (a Partner's includes work not yet dated).
    """
    if str(school_type or "") not in CLIENT_RULE_TYPES:
        return ()
    reasons = []
    if sum(staff_by_pool.values()) and sum(partner_by_pool.values()):
        reasons.append(DUPLICATE_BOTH)
    if any(count > 1 for count in staff_by_pool.values()):
        reasons.append(DUPLICATE_STAFF)
    if any(count > 1 for count in partner_by_pool.values()):
        reasons.append(DUPLICATE_PARTNER)
    return tuple(reasons)


def check() -> None:
    """The rulebook agrees with the enums it reads."""
    from apps.core.enums import ActivityType

    unknown = set(COUNTED_VISIT_TYPES) | set(OUTREACH_TYPES)
    unknown -= set(ActivityType.values)
    if unknown:
        raise ValueError(f"rulebook names unknown activity types: {sorted(unknown)}")
    overlap = set(COUNTED_VISIT_TYPES) & set(OUTREACH_TYPES)
    if overlap:
        raise ValueError(f"types both counted and outreach: {sorted(overlap)}")
    missing = set(SchoolType.values) - set(REQUIREMENTS)
    if missing:
        raise ValueError(
            f"school types with no requirement in the rulebook: {sorted(missing)}"
        )
