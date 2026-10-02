"""The plan read by the people who made it, and by the schools it reaches.

Two readings of one year, both by the rulebook (``rules``):

* ``people_plan`` — every Programme Lead and CCEO against the visits their
  role plans: the counted visits each planned, wherever the school is, the
  trainings and cluster meetings they planned, the schools they handed to a
  Partner and how much of that the Partner has dated, and the schools they
  hold. A visit belongs to whoever is responsible for it, never to whoever
  holds the school.

* ``school_year`` — every eligible school against what its type needs: the
  visit and training slots its plan fills (a slot once, however many plans
  land on it), which schools nothing is planned for yet, which are in a
  Partner's hands, and which are planned twice.

Both are a fixed handful of grouped reads whatever the size of the country.
Nothing here is stored and nothing is cached: callers that render it keep
their own snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Case, Count, IntegerField, Q, Value, When

from apps.planning.country_oversight import rules
from apps.planning.country_oversight.coverage import (
    Window,
    _Handover,
    _day,
    handover_kind,
    window_for,
)
from apps.planning.country_oversight.requirements import (
    eligible_school_queryset,
    reporting_date,
)


@dataclass(frozen=True)
class Narrow:
    """The page's filters, as the people-first read applies them.

    A person's plan is narrowed to the schools the page is showing: by the
    school's own region, district, type and cluster state, or — for a filter
    only the school-by-school fold can answer (a planning status, one
    Partner) — to the school ids it kept. ``channel`` reads one side only.
    Cluster sessions have no school; they follow the cluster's region and
    district.
    """

    region: str = ""
    district: str = ""
    school_type: str = ""
    cluster_status: str = ""
    channel: str = ""
    partner: str = ""
    school_ids: tuple | None = None

    @property
    def staff_side(self) -> bool:
        return self.channel != "partner"

    @property
    def partner_side(self) -> bool:
        return self.channel != "staff"

    def schools(self, queryset):
        if self.school_ids is not None:
            queryset = queryset.filter(id__in=self.school_ids)
        if self.region:
            queryset = queryset.filter(region_id=self.region)
        if self.district:
            queryset = queryset.filter(district_id=self.district)
        if self.school_type:
            queryset = queryset.filter(school_type=self.school_type)
        if self.cluster_status:
            from apps.clusters.models import Cluster

            active = Cluster.objects.filter(status="active").values("id")
            clustered = Q(cluster_id__in=active)
            queryset = queryset.filter(
                clustered if self.cluster_status == "clustered" else ~clustered
            )
        return queryset

    def sessions(self, queryset):
        if self.region:
            queryset = queryset.filter(cluster__region_id=self.region)
        if self.district:
            queryset = queryset.filter(cluster__district_id=self.district)
        return queryset


OTHER_TEAM_KEY = "__other__"
OTHER_TEAM_LABEL = "Other staff"
NO_OWNER_KEY = "__unassigned__"
NO_OWNER_LABEL = "No account owner"
UNRECORDED_KEY = "__unrecorded__"
UNRECORDED_LABEL = "No responsible person recorded"


def _blank_kinds() -> dict:
    return {kind: 0 for kind in rules.KIND_ORDER}


@dataclass
class PersonPlan:
    """One person's year. ``role`` is blank for somebody who is neither a
    Programme Lead nor a CCEO: they carry no target, and still show."""

    key: str
    name: str
    role: str = ""
    role_in_use: str = ""
    team_key: str = OTHER_TEAM_KEY
    team_name: str = OTHER_TEAM_LABEL
    # Schools held (account owner), by school type.
    schools: dict = field(default_factory=dict)
    # Counted visits this person planned, by kind and by the school's type.
    visits: dict = field(default_factory=_blank_kinds)
    visits_by_type: dict = field(default_factory=dict)
    # Donor, story, invitation and social visits: planned, not counted.
    outreach: int = 0
    trainings: int = 0
    cluster_trainings: int = 0
    meetings: int = 0
    # Partner work this person handed over or monitors.
    partner_school_ids: set = field(default_factory=set)
    partner_assigned: int = 0
    partner_planned: int = 0
    # The same, by Partner: partner id → [assigned, planned, school ids].
    by_partner: dict = field(default_factory=dict)

    def hand(self, partner_id, school_id, planned: int = 0) -> None:
        """One piece of work this person put in a Partner's hands."""
        self.partner_assigned += 1
        self.partner_planned += planned
        self.partner_school_ids.add(school_id)
        entry = self.by_partner.setdefault(str(partner_id or ""), [0, 0, set()])
        entry[0] += 1
        entry[1] += planned
        entry[2].add(school_id)

    @property
    def target(self) -> int:
        return rules.target_for(self.role)

    @property
    def role_label(self) -> str:
        return rules.ROLE_LABELS.get(self.role, "")

    @property
    def visits_planned(self) -> int:
        return sum(self.visits.values())

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.visits_planned)

    @property
    def share(self) -> int | None:
        return round(100 * self.visits_planned / self.target) if self.target else None

    @property
    def school_count(self) -> int:
        return sum(self.schools.values())

    @property
    def reach(self) -> int:
        """The visits staff could plan at the schools this person holds."""
        return rules.portfolio_reach(self.schools)

    @property
    def shortfall(self) -> int:
        """How far the schools held fall short of the role's target."""
        return max(0, self.target - self.reach)

    @property
    def partner_schools(self) -> int:
        return len(self.partner_school_ids)

    @property
    def partner_waiting(self) -> int:
        return max(0, self.partner_assigned - self.partner_planned)

    @property
    def has_anything(self) -> bool:
        return bool(
            self.school_count
            or self.visits_planned
            or self.outreach
            or self.trainings
            or self.cluster_trainings
            or self.meetings
            or self.partner_assigned
        )


#: PersonPlan counts a team and the country add up.
SUMMED = (
    "target",
    "visits_planned",
    "outreach",
    "trainings",
    "cluster_trainings",
    "meetings",
    "partner_assigned",
    "partner_planned",
    "partner_schools",
    "school_count",
    "reach",
    "shortfall",
)


@dataclass
class TeamPlan:
    key: str
    name: str
    people: list = field(default_factory=list)

    def total(self, name: str) -> int:
        return sum(getattr(person, name) for person in self.people)

    def visits_of(self, kind: str) -> int:
        return sum(person.visits.get(kind, 0) for person in self.people)

    @property
    def share(self) -> int | None:
        target = self.total("target")
        return round(100 * self.total("visits_planned") / target) if target else None


@dataclass
class PeoplePlan:
    fy: str
    window: Window
    as_of: date
    teams: list = field(default_factory=list)

    @property
    def people(self) -> list:
        return [person for team in self.teams for person in team.people]

    def total(self, name: str) -> int:
        return sum(team.total(name) for team in self.teams)

    def visits_of(self, kind: str) -> int:
        return sum(team.visits_of(kind) for team in self.teams)

    @property
    def share(self) -> int | None:
        target = self.total("target")
        return round(100 * self.total("visits_planned") / target) if target else None

    def headcount(self, role: str) -> int:
        return sum(1 for person in self.people if person.role == role)


# ── Reads ────────────────────────────────────────────────────────────────────
def _scope_and_schools(user, fy: str, today: date | None = None, scope=None):
    from apps.core.scoping import resolve_user_scope

    scope = scope or resolve_user_scope(user)
    as_of = reporting_date(str(fy), today)
    return scope, as_of, eligible_school_queryset(scope, as_of)


def _activities(fy: str, school_ids=None):
    from apps.activities.models import Activity

    queryset = Activity.objects.filter(fy=str(fy), deleted_at__isnull=True)
    if school_ids is not None:
        queryset = queryset.filter(school_id__in=school_ids)
    return queryset


def _in_window(queryset, window: Window, prefix: str = ""):
    """Rows dated inside the window. The year keeps everything filed under
    it, as the year's own pages do."""
    if window.is_annual:
        return queryset
    return queryset.annotate(day=_day(prefix)).filter(
        day__gte=window.start, day__lt=window.end
    )


def _other_people(raw_ids) -> dict[str, tuple[str, str, str]]:
    """raw id → (StaffProfile id, name, role in use) for ids the roster does
    not name, in either id space."""
    from apps.accounts.models import StaffProfile

    ids = {str(i) for i in raw_ids if i}
    found: dict[str, tuple[str, str, str]] = {}
    if not ids:
        return found
    for profile_id, user_id, name, email, role in StaffProfile.all_objects.filter(
        Q(id__in=ids) | Q(user_id__in=ids)
    ).values_list("id", "user_id", "user__name", "user__email", "user__active_role"):
        entry = (str(profile_id), name or email or str(profile_id), role or "")
        for key in (profile_id, user_id):
            if key:
                found[str(key)] = entry
    return found


class _People:
    """The roster, and a row for anyone else the year's records name."""

    def __init__(self, country: str = ""):
        self.teams: dict[str, TeamPlan] = {}
        self.by_id: dict[str, PersonPlan] = {}
        self._pending: set[str] = set()
        for team in rules.roster(country):
            plan = self.teams[team.key] = TeamPlan(key=team.key, name=team.name)
            for person in team.people:
                row = PersonPlan(
                    key=person.key,
                    name=person.name,
                    role=person.role,
                    role_in_use=person.role_in_use,
                    team_key=team.key,
                    team_name=team.name,
                )
                plan.people.append(row)
                for raw in person.ids:
                    self.by_id[raw] = row

    def note(self, raw_ids) -> None:
        """Remember ids the roster may not know, to resolve in one query."""
        self._pending.update(str(i) for i in raw_ids if i and str(i) not in self.by_id)

    def resolve(self) -> None:
        others = _other_people(self._pending)
        self._pending.clear()
        for raw, (profile_id, name, role) in others.items():
            if raw in self.by_id:
                continue
            row = self.by_id.get(profile_id)
            if row is None:
                row = PersonPlan(key=profile_id, name=name, role_in_use=role)
                self._other_team().people.append(row)
                self.by_id[profile_id] = row
            self.by_id[raw] = row

    def _other_team(self) -> TeamPlan:
        team = self.teams.get(OTHER_TEAM_KEY)
        if team is None:
            team = self.teams[OTHER_TEAM_KEY] = TeamPlan(
                key=OTHER_TEAM_KEY, name=OTHER_TEAM_LABEL
            )
        return team

    def get(self, raw_id, *, fallback: str = UNRECORDED_KEY) -> PersonPlan:
        row = self.by_id.get(str(raw_id or ""))
        if row is not None:
            return row
        row = self.by_id.get(fallback)
        if row is None:
            label = NO_OWNER_LABEL if fallback == NO_OWNER_KEY else UNRECORDED_LABEL
            row = self.by_id[fallback] = PersonPlan(key=fallback, name=label)
            self._other_team().people.append(row)
        return row

    def first(self, *raw_ids) -> PersonPlan | None:
        for raw in raw_ids:
            row = self.by_id.get(str(raw or ""))
            if row is not None:
                return row
        return None


class Reads:
    """The year's rows by the rulebook, narrowed as the page is.

    One definition of each set — counted visits, outreach, trainings, cluster
    sessions, Partner work, hand-overs — as a queryset. The cards count them
    (``people_plan``) and the consolidated tables list them (``tables``), so a
    card and the table it opens cannot disagree.
    """

    def __init__(
        self,
        user,
        fy: str,
        *,
        window: Window | None = None,
        today: date | None = None,
        scope=None,
        narrow: Narrow | None = None,
    ):
        self.fy = str(fy)
        self.window = window or window_for(self.fy)
        self.narrow = narrow or Narrow()
        self.scope, self.as_of, schools = _scope_and_schools(
            user, self.fy, today, scope
        )
        self.schools = None if schools is None else self.narrow.schools(schools)
        self.country = getattr(self.scope, "country", "") or ""

    @property
    def school_ids(self):
        return self.schools.values("id")

    @property
    def _staff(self):
        return _activities(self.fy, self.school_ids).filter(
            rules.planned_q() & rules.staff_delivery_q()
        )

    def counted_visits(self):
        """Staff visits that count, with their ``kind``."""
        return _in_window(
            self._staff.filter(rules.counted_visit_q()), self.window
        ).annotate(kind=rules.visit_kind_case())

    def outreach(self):
        """Donor, story, invitation and social visits: shown, never counted."""
        return _in_window(self._staff.filter(rules.outreach_visit_q()), self.window)

    def school_trainings(self):
        """Staff trainings at a school."""
        from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES

        return _in_window(
            self._staff.filter(
                activity_type__in=SCHOOL_TRAINING_TYPES, cluster_id__isnull=True
            ),
            self.window,
        )

    def sessions(self):
        """Staff cluster trainings and cluster meetings."""
        from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES

        return _in_window(
            self.narrow.sessions(
                _activities(self.fy).filter(
                    rules.planned_q() & rules.staff_delivery_q(),
                    cluster_id__isnull=False,
                    activity_type__in=(*TRAINING_TYPES, *CLUSTER_MEETING_TYPES),
                )
            ),
            self.window,
        )

    def other_work(self):
        """Staff work at a school that is none of the above — not a counted
        visit, an outreach visit or a training: listed with every activity
        (owner, 2026-10-02), counted nowhere. The visit an in-school training
        writes beside itself is that training, not a second activity."""
        from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES

        return _in_window(
            self._staff.filter(cluster_id__isnull=True)
            .exclude(rules.counted_visit_q())
            .exclude(rules.outreach_visit_q())
            .exclude(activity_type__in=SCHOOL_TRAINING_TYPES)
            .exclude(purpose_type=rules.COMPANION_PURPOSE),
            self.window,
        )

    def partner_sessions(self):
        """Cluster trainings and meetings a Partner delivers. They have no
        school of their own, so no read of a school's Partner work finds
        them."""
        from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES

        held = self.narrow.sessions(
            _activities(self.fy).filter(
                rules.partner_held_q(),
                cluster_id__isnull=False,
                school_id__isnull=True,
                activity_type__in=(*TRAINING_TYPES, *CLUSTER_MEETING_TYPES),
            )
        )
        if self.narrow.partner:
            held = held.filter(assigned_partner_id=self.narrow.partner)
        return _in_window(held, self.window).annotate(
            partner_planned=Case(
                When(rules.partner_planned_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

    def partner_work(self, *, every: bool = False):
        """Live Partner activities, each marked ``partner_planned`` (1/0).

        Alumni work (a project no SSA intervention measures) is not counted
        by this rulebook, so it is left out; ``every`` keeps it, for the one
        list that holds every activity whether it counts or not. A Partner's
        data collection (SSA Support) is Partner work like any other: the
        school is assigned to the Partner, and the work is no visit of the
        school's (owner, 2026-10-02: "it should show SSA support")."""
        held = _activities(self.fy, self.school_ids).filter(rules.partner_held_q())
        if not every:
            held = held.filter(rules.not_outside_ssa_q())
        if self.narrow.partner:
            held = held.filter(assigned_partner_id=self.narrow.partner)
        return _in_window(held, self.window).annotate(
            partner_planned=Case(
                When(rules.partner_planned_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )

    def handovers(self, *, every: bool = False):
        """Hand-overs that still put a school in a Partner's hands; ``every``
        as for ``partner_work``."""
        from apps.partners.models import PartnerAssignment

        rows = PartnerAssignment.objects.filter(school_id__in=self.school_ids).exclude(
            status__in=rules.CLOSED_HANDOVER_STATUSES
        )
        if not every:
            rows = rows.filter(rules.not_outside_ssa_q())
        if self.narrow.partner:
            rows = rows.filter(partner_id=self.narrow.partner)
        return rows

    @property
    def reads_handovers(self) -> bool:
        """A hand-over has no date of its own: it is outstanding from the
        year's first day, so it is read by a window that holds that day."""
        return self.window.start <= self.window.fy_start < self.window.end

    def waiting(self, status, created_at) -> bool:
        """Is this hand-over still waiting for the Partner's date, this year?"""
        from apps.core.fy import get_operational_fy
        from apps.partners.models import PartnerAssignment

        return (
            status in PartnerAssignment.UNSCHEDULED_STATUSES
            and created_at is not None
            and int(get_operational_fy(created_at)) <= int(self.fy)
        )


def people_plan(
    user,
    fy: str,
    *,
    window: Window | None = None,
    today: date | None = None,
    scope=None,
    narrow: Narrow | None = None,
    portfolio: bool = True,
) -> PeoplePlan:
    """Every Programme Lead's and CCEO's year, by the rulebook.

    ``scope`` stands in for ``user`` when the system reads a country;
    ``narrow`` applies the page's filters; ``portfolio=False`` skips the
    schools each person holds, for a caller that already has them.
    """
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    reads = Reads(user, fy, window=window, today=today, scope=scope, narrow=narrow)
    fy, window, narrow = reads.fy, reads.window, reads.narrow
    people = _People(reads.country)
    plan = PeoplePlan(fy=fy, window=window, as_of=reads.as_of)
    if reads.schools is None:
        plan.teams = list(people.teams.values())
        return plan

    held, visits, outreach, trainings, sessions = [], [], [], [], []
    handovers, partner_work = [], []
    # 1. The schools each person holds, by type.
    if portfolio:
        held = list(
            reads.schools.values_list("account_owner_id", "school_type")
            .annotate(n=Count("id"))
            .order_by()
        )
    if narrow.staff_side:
        # 2. Counted visits, by who is responsible for them.
        visits = list(
            reads.counted_visits()
            .values_list("responsible_staff_id", "school__school_type", "kind")
            .annotate(n=Count("id"))
            .order_by()
        )
        # 3. Outreach visits: shown, never counted.
        outreach = list(
            reads.outreach()
            .values_list("responsible_staff_id")
            .annotate(n=Count("id"))
            .order_by()
        )
        # 4. Trainings at a school, cluster trainings and cluster meetings.
        trainings = list(
            reads.school_trainings()
            .values_list("responsible_staff_id")
            .annotate(n=Count("id"))
            .order_by()
        )
        sessions = list(
            reads.sessions()
            .values_list("responsible_staff_id", "activity_type")
            .annotate(n=Count("id"))
            .order_by()
        )
    if narrow.partner_side:
        # 5. Partner work: hand-overs still waiting, and the Partner's
        # activities.
        handovers = list(
            reads.handovers().values_list(
                "school_id",
                "partner_id",
                "status",
                "monitoring_staff_id",
                "assigning_staff_id",
                "scheduled_activity_id",
                "source_activity_id",
                "school__account_owner_id",
                "created_at",
            )
        )
        partner_work = list(
            reads.partner_work().values_list(
                "id",
                "school_id",
                "assigned_partner_id",
                "monitored_by_staff_id",
                "responsible_staff_id",
                "school__account_owner_id",
                "partner_planned",
            )
        )

    people.note(row[0] for row in held)
    people.note(row[0] for row in visits)
    people.note(row[0] for row in outreach)
    people.note(row[0] for row in trainings)
    people.note(row[0] for row in sessions)
    people.note(i for row in handovers for i in (row[3], row[4], row[7]))
    people.note(i for row in partner_work for i in (row[3], row[4], row[5]))
    people.resolve()

    for owner_id, school_type, n in held:
        person = people.get(owner_id, fallback=NO_OWNER_KEY)
        person.schools[school_type] = person.schools.get(school_type, 0) + n
    for staff_id, school_type, kind, n in visits:
        person = people.get(staff_id)
        person.visits[kind] = person.visits.get(kind, 0) + n
        person.visits_by_type[school_type] = (
            person.visits_by_type.get(school_type, 0) + n
        )
    for staff_id, n in outreach:
        people.get(staff_id).outreach += n
    for staff_id, n in trainings:
        people.get(staff_id).trainings += n
    meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
    for staff_id, activity_type, n in sessions:
        person = people.get(staff_id)
        if activity_type in meeting_types:
            person.meetings += n
        else:
            person.cluster_trainings += n

    # A hand-over the Partner has dated is read as the activity it became;
    # one still waiting is assigned from the year it was made in onwards.
    handed_by: dict[str, tuple] = {}
    carried: set[str] = set()
    for (
        school_id,
        partner_id,
        status,
        monitor,
        assigner,
        scheduled_activity_id,
        source_activity_id,
        holder,
        created_at,
    ) in handovers:
        if scheduled_activity_id:
            handed_by[scheduled_activity_id] = (monitor, assigner)
            continue
        if not reads.waiting(status, created_at):
            continue
        if source_activity_id:
            carried.add(source_activity_id)
            handed_by[source_activity_id] = (monitor, assigner)
        if not reads.reads_handovers:
            continue
        person = people.first(monitor, assigner, holder) or people.get(None)
        person.hand(partner_id, school_id)
    for (
        activity_id,
        school_id,
        partner_id,
        monitor,
        responsible,
        holder,
        planned,
    ) in partner_work:
        if activity_id in carried:
            continue  # counted once, as the hand-over that carries it
        person = people.first(
            *handed_by.get(activity_id, ()), monitor, responsible, holder
        ) or people.get(None)
        person.hand(partner_id, school_id, planned)

    plan.teams = [team for team in people.teams.values() if _keeps_team(team)]
    return plan


def _keeps_team(team: TeamPlan) -> bool:
    """Roster teams always show; the 'Other staff' rows only when they hold
    or planned something."""
    if team.key != OTHER_TEAM_KEY:
        return True
    team.people = [person for person in team.people if person.has_anything]
    team.people.sort(key=lambda person: (person.key.startswith("__"), person.name))
    return bool(team.people)


# ── The schools' year ────────────────────────────────────────────────────────
@dataclass(slots=True)
class SchoolYear:
    """One eligible school, and what the year's records plan for it."""

    id: str
    code: str
    name: str
    school_type: str
    owner_id: str | None
    clustered: bool = False
    # Counted staff visits, by kind.
    staff: dict | None = None
    # Partner visits the Partner has dated, by kind.
    partner_planned: dict | None = None
    # Partner visits assigned and not dated by the Partner, by pool.
    partner_waiting: dict | None = None
    # Partner work that is not a counted visit (trainings, other support).
    partner_other: int = 0
    partner_ids: set | None = None
    staff_trainings: int = 0
    partner_trainings: int = 0
    cluster_trainings: int = 0
    meetings: int = 0

    @property
    def requirement(self) -> rules.TypeRequirement:
        return rules.requirement_for(self.school_type)

    @property
    def staff_visits(self) -> int:
        return sum((self.staff or {}).values())

    @property
    def partner_visits_planned(self) -> int:
        return sum((self.partner_planned or {}).values())

    @property
    def partner_visits_waiting(self) -> int:
        return sum((self.partner_waiting or {}).values())

    @property
    def with_partner(self) -> bool:
        """In a Partner's hands: any live Partner work, dated or not."""
        return bool(
            self.partner_visits_planned
            or self.partner_visits_waiting
            or self.partner_other
            or self.partner_trainings
        )

    @property
    def staff_slots(self) -> int:
        """Visit slots staff plans fill: a slot once, however many plans."""
        requirement = self.requirement
        return min(self.staff_visits, requirement.staff_reach)

    @property
    def partner_slots(self) -> int:
        """Visit slots the Partner's own dates fill. At a client-rule school
        the one slot is staff's when staff planned the school."""
        requirement = self.requirement
        either_left = max(0, requirement.either_visits - self.staff_slots)
        return min(
            self.partner_visits_planned, requirement.partner_visits + either_left
        )

    @property
    def visit_slots(self) -> int:
        return self.staff_slots + self.partner_slots

    @property
    def has_visit(self) -> bool:
        return bool(self.staff_visits or self.partner_visits_planned)

    @property
    def training_slots(self) -> int:
        requirement = self.requirement
        # A group training planned through the school's cluster is a training
        # of the school's, in a Core package too (owner, 2026-10-02): it is
        # one of the staff half's two.
        staff = self.staff_trainings + self.cluster_trainings
        if requirement.either_trainings:
            return min(staff + self.partner_trainings, requirement.either_trainings)
        return min(staff, requirement.staff_trainings) + min(
            self.partner_trainings, requirement.partner_trainings
        )

    @property
    def has_training(self) -> bool:
        return bool(
            self.staff_trainings or self.cluster_trainings or self.partner_trainings
        )

    @property
    def duplicate_reasons(self) -> tuple[str, ...]:
        staff: dict[str, int] = {}
        for kind, n in (self.staff or {}).items():
            pool = rules.pool_of(kind)
            staff[pool] = staff.get(pool, 0) + n
        partner = dict(self.partner_waiting or {})
        for kind, n in (self.partner_planned or {}).items():
            pool = rules.pool_of(kind)
            partner[pool] = partner.get(pool, 0) + n
        return rules.duplicate_reasons(self.school_type, staff, partner)


def _bump(counts: dict | None, key: str, n: int) -> dict:
    counts = {} if counts is None else counts
    counts[key] = counts.get(key, 0) + n
    return counts


def _handover_pool(expected_activity_type, purpose) -> str:
    kind = rules.visit_kind(expected_activity_type or "school_visit", purpose)
    return rules.pool_of(kind) or rules.POOL_SUPPORT


def school_year(user, fy: str, *, today: date | None = None) -> dict[str, SchoolYear]:
    """Every eligible school's year, by the rulebook, in a few grouped reads."""
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.activities.models import ClusterActivityAttendance
    from apps.clusters.models import Cluster
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.core.fy import get_operational_fy
    from apps.partners.models import PartnerAssignment

    fy = str(fy)
    _scope, _as_of, schools = _scope_and_schools(user, fy, today)
    if schools is None:
        return {}
    active_clusters = set(
        Cluster.objects.filter(status="active").values_list("id", flat=True)
    )
    year: dict[str, SchoolYear] = {}
    for pk, code, name, school_type, owner_id, cluster_id in schools.values_list(
        "id", "school_id", "name", "school_type", "account_owner_id", "cluster_id"
    ):
        year[pk] = SchoolYear(
            id=pk,
            code=code or "",
            name=name or "",
            school_type=school_type or "",
            owner_id=owner_id or None,
            clustered=cluster_id in active_clusters,
        )
    if not year:
        return year
    school_ids = schools.values("id")
    # A school's year by the rulebook is its SSA-measured support: Alumni
    # work is no visit, no training and no Partner's hold on it.
    in_scope = _activities(fy, school_ids).filter(rules.not_outside_ssa_q())
    counted = rules.counted_visit_q()

    # Staff visits that count, by kind.
    for school_id, kind, n in (
        in_scope.filter(rules.planned_q() & rules.staff_delivery_q() & counted)
        .annotate(kind=rules.visit_kind_case())
        .values_list("school_id", "kind")
        .annotate(n=Count("id"))
        .order_by()
    ):
        school = year.get(school_id)
        if school is not None:
            school.staff = _bump(school.staff, kind, n)

    # Partner work: dated by the Partner, or held and still waiting.
    carried = set(
        PartnerAssignment.objects.filter(
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            source_activity_id__isnull=False,
        ).values_list("source_activity_id", flat=True)
    )
    training_types = {str(t) for t in TRAINING_TYPES}
    for (
        activity_id,
        school_id,
        partner_id,
        activity_type,
        purpose,
        planned,
    ) in (
        in_scope.filter(rules.partner_held_q())
        .annotate(
            partner_planned=Case(
                When(rules.partner_planned_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .values_list(
            "id",
            "school_id",
            "assigned_partner_id",
            "activity_type",
            "purpose_type",
            "partner_planned",
        )
    ):
        school = year.get(school_id)
        if school is None or activity_id in carried:
            continue
        if partner_id:
            school.partner_ids = (school.partner_ids or set()) | {partner_id}
        # An in-school training is a visit and a training, as it is for staff.
        kind = rules.visit_kind(activity_type, purpose)
        trains = activity_type in training_types and bool(planned)
        if trains:
            school.partner_trainings += 1
        if kind is None:
            if not trains:
                school.partner_other += 1
        elif planned:
            school.partner_planned = _bump(school.partner_planned, kind, 1)
        else:
            school.partner_waiting = _bump(
                school.partner_waiting, rules.pool_of(kind), 1
            )
    for (
        school_id,
        partner_id,
        created_at,
        *kind_fields,
    ) in (
        PartnerAssignment.objects.filter(
            school_id__in=school_ids,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        )
        .filter(rules.not_outside_ssa_q())
        .values_list(
            "school_id",
            "partner_id",
            "created_at",
            "support_type",
            "visit_number",
            "training_number",
            "project_id",
            "expected_activity_type",
            "purpose_of_visit",
        )
    ):
        school = year.get(school_id)
        if school is None:
            continue
        if created_at is None or int(get_operational_fy(created_at)) > int(fy):
            continue
        if partner_id:
            school.partner_ids = (school.partner_ids or set()) | {partner_id}
        handover = _Handover(*kind_fields)
        if handover_kind(school.school_type, handover) != "visit":
            school.partner_other += 1
            continue
        school.partner_waiting = _bump(
            school.partner_waiting,
            _handover_pool(handover.expected_activity_type, handover.purpose_of_visit),
            1,
        )

    # Trainings at the school, by who delivers them.
    # (A Partner's are counted above, once the Partner has dated them.)
    for school_id, n in (
        in_scope.filter(
            rules.planned_q() & rules.staff_delivery_q(),
            activity_type__in=SCHOOL_TRAINING_TYPES,
            cluster_id__isnull=True,
        )
        .values_list("school_id")
        .annotate(n=Count("id"))
        .order_by()
    ):
        school = year.get(school_id)
        if school is not None:
            school.staff_trainings += n

    # Cluster sessions: one for each school on the planned roster.
    cluster_trainings = tuple(
        t for t in TRAINING_TYPES if t not in SCHOOL_TRAINING_TYPES
    )
    for attribute, types in (
        ("cluster_trainings", cluster_trainings),
        ("meetings", CLUSTER_MEETING_TYPES),
    ):
        for school_id, n in (
            ClusterActivityAttendance.objects.filter(
                invited=True,
                school_id__in=school_ids,
                activity__fy=fy,
                activity__deleted_at__isnull=True,
                activity__cluster_id__isnull=False,
                activity__activity_type__in=types,
            )
            .filter(rules.planned_q("activity__"))
            .values_list("school_id")
            .annotate(n=Count("id"))
            .order_by()
        ):
            school = year.get(school_id)
            if school is not None:
                setattr(school, attribute, getattr(school, attribute) + n)
    return year


@dataclass
class TypeSummary:
    """The schools of one type: what they need and what is planned."""

    school_type: str
    schools: int = 0
    visit_slots: int = 0
    staff_slots: int = 0
    partner_slots: int = 0
    schools_with_visit: int = 0
    training_slots: int = 0
    trainings: int = 0
    schools_with_training: int = 0
    with_partner: int = 0
    clustered: int = 0
    in_meeting: int = 0
    duplicates: int = 0

    @property
    def label(self) -> str:
        return rules.type_label(self.school_type)

    @property
    def visits_planned(self) -> int:
        return self.staff_slots + self.partner_slots

    @property
    def schools_without_visit(self) -> int:
        return self.schools - self.schools_with_visit

    @property
    def schools_without_training(self) -> int:
        return self.schools - self.schools_with_training


def summarise_by_type(year: dict[str, SchoolYear]) -> list[TypeSummary]:
    """One row per school type, the rulebook's order first."""
    by_type: dict[str, TypeSummary] = {
        school_type: TypeSummary(school_type) for school_type in rules.TYPE_ORDER
    }
    for school in year.values():
        row = by_type.get(school.school_type)
        if row is None:
            row = by_type[school.school_type] = TypeSummary(school.school_type)
        requirement = school.requirement
        row.schools += 1
        row.visit_slots += requirement.visits
        row.staff_slots += school.staff_slots
        row.partner_slots += school.partner_slots
        row.schools_with_visit += 1 if school.has_visit else 0
        row.training_slots += requirement.trainings
        row.trainings += school.training_slots
        row.schools_with_training += 1 if school.has_training else 0
        row.with_partner += 1 if school.with_partner else 0
        row.clustered += 1 if school.clustered else 0
        row.in_meeting += 1 if school.meetings else 0
        row.duplicates += 1 if school.duplicate_reasons else 0
    return list(by_type.values())


def duplicates(year: dict[str, SchoolYear]) -> list[SchoolYear]:
    """Client-rule schools planned twice, by name."""
    found = [school for school in year.values() if school.duplicate_reasons]
    found.sort(key=lambda school: (school.name.casefold(), school.id))
    return found


__all__ = [
    "Narrow",
    "PeoplePlan",
    "PersonPlan",
    "Reads",
    "SchoolYear",
    "TeamPlan",
    "TypeSummary",
    "duplicates",
    "people_plan",
    "school_year",
    "summarise_by_type",
]
