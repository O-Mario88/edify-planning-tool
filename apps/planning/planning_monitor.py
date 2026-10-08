"""The Planning Monitor: each CCEO's year against the visits it should hold.

Owner, 2026-09-28:

  "Every CCEO is supposed to plan 560 visits that includes the 2 visits from
  each core school and client school. ... if a staff has 80 core schools, the
  total visits for core schools will be 160 total visits for the core
  schools, and the remaining 400 school visit will be client visit, core
  trained. The rest of the remaining number should be assigned to the
  partner. CD and IA needs to track the planning by how many total number of
  schools and how many unique school visits have been planned. For
  trainings, every schools need to be trained so the IA and CD needs to track
  how many schools have been planned for training (through cluster group
  training and Cluster Meetings). They also would want to track all school
  not clustered, not planned for (Visits, training and both). They also need
  to track how many schools are assigned to projects ... Basically CD and IA
  need to Monitor planning and later execution in real time just like the PLs
  are doing."

Owner, 2026-09-29: "PL plans for maximum of 280 and CCEO 560 ... fetch the
right data based on what people have planned." The rows are the people
(apps.planning.monitor_roster): every Programme Lead and every CCEO in the
reader's scope, whether or not the directory lists a school under them.

Owner, 2026-10-01: the monitor and Country Planning Oversight count by one
rulebook (apps.planning.country_oversight.rules), so the two pages cannot
give the Country Director two figures for one plan. The people are the
rulebook's (a Lead or a CCEO by the role they hold); a visit that counts is a
Follow up or an In-school Training, planned and dated (data collection
counts nowhere: owner, 2026-10-02);
Partner work is planned once the Partner has dated it.

So, per person, for one fiscal year:

* **The visit target** — 280 for a Programme Lead, 560 for a CCEO.
* **Visits planned** — the counted staff visits the person planned, wherever
  they are. SSA Support (data collection), donor, story, social and
  invitation visits are not counted.
* **Core visits** — two staff visits a year at each Core school
  (``CORE_STAFF_VISITS_PER_SCHOOL``): the target is 2 × Core schools.
* **Client visits** — the rest of the target, at Client, Core Trained and
  Core Graduate schools (planned alike since 2026-09-28).
* **Partner share** — client-rule schools beyond what the officer's client
  visits can reach are the partner's: needed = schools − client target;
  assigned = schools with partner work (a visit the partner has dated, or
  work the partner has not dated yet); remaining = needed − assigned.
* **The Core package's partner half** (owner, 2026-09-30 and 2026-10-02) —
  each Core school's package is two staff and two partner visits, two staff
  and two partner trainings. Assigned = what the partner side of each package
  holds, hand-overs not yet dated included, to the two it takes
  (apps.core_schools.package_split); the target is 2 × Core schools of each.
* **Unique schools** with a visit planned, **schools planned for training**
  (invited to a live group training or cluster meeting, or given an in-school
  training), schools **not clustered**, **not planned** for a visit, for
  training, or for either, and schools **in a Special Project**. Training is
  read against the schools that take one: Core, Client, Core Trained and
  Core Graduate (owner, 2026-10-02: the last three "should be treated the
  same").
* **Execution** beside each plan: visits delivered and schools whose
  training has been delivered, counted from the same rows as it happens.

Only schools the requirement asks a visit of are counted: Core, Client, Core
Trained and Core Graduate. Champion schools take donor and story visits only
(owner, 2026-09-25) and are followed on Programme Schools.

Scope is the country for the CD and IA (``scoped_school_queryset``) and, for
a Programme Lead, the schools held by the Lead and the people who report to
them (``_monitored_schools``). Every figure is folded from the school rows
under it, so a lead's total is the sum of their officers' and cannot disagree
with them. A fixed handful of queries whatever the size of the country.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.core.activity_types import SSA_TYPES, TRAINING_TYPES, VISIT_TYPES
from apps.core.metrics import percentage
from apps.planning.monitor_roster import (
    CCEO_VISITS_TARGET,
    PL_VISITS_TARGET,
    ROLE_CCEO,
    ROLE_PL,
    VISITS_TARGET_BY_ROLE,
)

#: The visits a CCEO plans in a year.
DEFAULT_VISITS_TARGET = CCEO_VISITS_TARGET

#: Every visit type and SSA Support: the types a visit row can carry. The
#: visits that COUNT are the rulebook's (``_counted_visits``).
PLANNED_VISIT_TYPES = tuple(str(t) for t in (*VISIT_TYPES, *SSA_TYPES))
#: Staff visits a year at each Core school (two of the package's four; the
#: partner delivers the other two).
CORE_STAFF_VISITS_PER_SCHOOL = 2

#: Partner visits a year at each Core school, and as many partner trainings
#: (the other half of the package).
CORE_PARTNER_PER_SCHOOL = 2

#: School types the monitor counts.
CORE_TYPES = ("core",)
CLIENT_TYPES = ("client", "core_trained", "core_graduate")
MONITORED_TYPES = CORE_TYPES + CLIENT_TYPES

#: The drill-down filters, in the order the page offers them.
GAPS = (
    ("no_both", "Not planned for visits or training"),
    ("no_visit", "No visit planned"),
    ("no_training", "No training planned"),
    ("not_clustered", "Not clustered"),
    ("no_partner", "Beyond staff reach, no partner"),
    # Not gaps: the schools behind two counts of Planned and remaining.
    ("staff_scheduled", "Scheduled for a visit by staff"),
    ("staff_and_partner", "Scheduled by staff and also with a Partner"),
)
#: The schools behind every count on the monitor and on My Plan (owner,
#: 2026-10-05: "All those numbers should be link to the actual tables where
#: those schools are located"). Not gaps, so they are not offered in the gap
#: filter and no follow-up is sent from them; `in_list` says which schools
#: each one holds.
LISTS = (
    ("all", "Schools held"),
    ("core", "Core schools"),
    ("client", "Client, Core Trained and Core Graduate schools"),
    ("visited", "With a visit planned"),
    (
        "staff_queue",
        "The staff queue: Core schools, and schools not in a Partner's hands",
    ),
    ("staff_visits_left", "Still owed a staff visit"),
    ("core_staff_visits", "Core schools with a staff visit planned"),
    ("core_staff_visits_left", "Core schools short of two staff visits"),
    ("client_staff_visits", "Client schools with a staff visit planned"),
    ("client_staff_visits_left", "Client schools with no staff visit planned"),
    # The two visit flags of Planned and remaining (owner, 2026-10-07: "flag
    # visits planned by both staff and also assigned to partners for visits
    # ... core one should have 2 visits from staff and 2 from partner. more
    # than those should be flagged").
    (
        "core_visits_over",
        "Core schools with more than two staff visits or two Partner visits",
    ),
    (
        "client_staff_and_partner",
        "Client schools scheduled by staff and also with a Partner: booked twice",
    ),
    ("core_staff_trainings", "Core schools with a staff training in their package"),
    ("core_staff_trainings_left", "Core schools short of two staff trainings"),
    ("training", "In a group or in-school training"),
    ("training_due", "Schools that take a training"),
    ("with_partner", "In a Partner's hands"),
    (
        "partner_queue",
        "The Partner's queue: Core schools, and schools staff have not scheduled",
    ),
    ("partner_left", "Not yet handed to a Partner"),
    ("partner_dated", "With a Partner visit dated"),
    ("partner_waiting", "Awaiting the Partner's date"),
    ("partner_visits_left", "Still owed a Partner visit"),
    ("core_partner_visits", "Core schools with a Partner visit in their package"),
    ("core_partner_visits_left", "Core schools short of two Partner visits"),
    ("core_partner_trainings", "Core schools with a Partner training in their package"),
    ("core_partner_trainings_left", "Core schools short of two Partner trainings"),
    ("in_project", "In a project"),
    ("not_in_project", "Not in a project"),
    ("project_added", "Added to a project by the person who holds them"),
    ("fully_planned", "Fully planned"),
    ("partly_planned", "Partly planned"),
    ("not_yet_planned", "Not yet planned"),
    ("duplicates", "Booked more than once"),
    ("core_no_partner_half", "Core schools without their Partner half"),
)
LIST_KEYS = frozenset(key for key, _label in LISTS)
GAP_LABELS = {**dict(GAPS), **dict(LISTS)}


def in_list(school, key: str) -> bool:
    """Whether `school` (a SchoolState) is one of the schools behind `key`:
    a gap, or one of `LISTS`."""
    if key not in LIST_KEYS:
        return school.has_gap(key)
    core = school.is_core
    if key == "all":
        return True
    if key == "core":
        return core
    if key == "client":
        return not core
    if key == "visited":
        return school.has_visit
    if key == "staff_queue":
        return core or not (school.has_partner and not school.staff_visits)
    if key == "staff_visits_left":
        if core:
            return school.staff_visits < CORE_STAFF_VISITS_PER_SCHOOL
        return not school.staff_visits and not school.has_partner
    if key == "core_staff_visits":
        return core and school.staff_visits > 0
    if key == "core_staff_visits_left":
        return core and school.staff_visits < CORE_STAFF_VISITS_PER_SCHOOL
    if key == "client_staff_visits":
        return not core and school.staff_visits > 0
    if key == "client_staff_visits_left":
        return not core and not school.staff_visits
    if key == "core_visits_over":
        return school.core_visits_over
    if key == "client_staff_and_partner":
        return not core and school.staff_and_partner
    if key == "core_staff_trainings":
        return school.core_staff_trainings > 0
    if key == "core_staff_trainings_left":
        return core and school.core_staff_trainings < CORE_STAFF_VISITS_PER_SCHOOL
    if key == "training":
        return school.has_training
    if key == "training_due":
        return school.needs_training
    if key == "with_partner":
        return bool(
            school.has_partner
            or school.core_partner_visits
            or school.core_partner_trainings
        )
    if key == "partner_queue":
        return core or not school.staff_visits
    if key == "partner_left":
        if core:
            return not (
                school.has_partner
                or school.core_partner_visits
                or school.core_partner_trainings
            )
        return not school.staff_visits and not school.has_partner
    if key == "partner_dated":
        return school.partner_visits > 0
    if key == "partner_waiting":
        return school.partner_pending > 0
    if key == "partner_visits_left":
        if core:
            return school.partner_visits < CORE_PARTNER_PER_SCHOOL
        return not school.partner_visits and not school.staff_visits
    if key == "core_partner_visits":
        return school.core_partner_visits > 0
    if key == "core_partner_visits_left":
        return core and school.core_partner_visits < CORE_PARTNER_PER_SCHOOL
    if key == "core_partner_trainings":
        return school.core_partner_trainings > 0
    if key == "core_partner_trainings_left":
        return core and school.core_partner_trainings < CORE_PARTNER_PER_SCHOOL
    if key == "in_project":
        return school.in_project
    if key == "not_in_project":
        return not school.in_project
    if key == "project_added":
        return school.project_places > 0
    from apps.planning import readiness

    if key in ("fully_planned", "partly_planned", "not_yet_planned"):
        return readiness.school_state(school) == key.replace("_planned", "")
    if key == "duplicates":
        return readiness.is_duplicate(school)
    if key == "core_no_partner_half":
        return readiness.core_missing_partner_half(school)
    return False


def list_schools(officers, key: str, *, school_type: str = "") -> list:
    """The schools behind `key` for these people, by holder then name. A list
    reads the outreach-only schools a person holds as well: they are held,
    typed and in or out of a project like any other."""
    found = []
    for officer in officers:
        held = officer.schools
        if key in LIST_KEYS:
            held = [*officer.schools, *officer.outreach_schools]
        for school in held:
            if school_type and (school.school_type or "") != school_type:
                continue
            if in_list(school, key):
                found.append(school)
    found.sort(key=lambda s: (s.officer_name.casefold(), s.name.casefold()))
    return found


#: The gap columns of the monitor's table, each with the tone its count reads.
GAP_COLUMNS = (
    ("not_clustered", "Not clustered", "warning"),
    ("no_visit", "No visit", "danger"),
    ("no_training", "No training", "danger"),
    ("no_both", "Neither", "danger"),
)


#: The figure each gap column shows, where it is not named as the gap is.
GAP_FIGURES = {"no_visit": "unplanned"}


def _gap_cells(row) -> list[tuple[dict, int]]:
    return [
        (
            {"key": key, "label": label, "tone": tone},
            getattr(row, GAP_FIGURES.get(key, key)),
        )
        for key, label, tone in GAP_COLUMNS
    ]


@dataclass
class SchoolState:
    id: str
    code: str
    name: str
    school_type: str
    district: str
    cluster_id: str
    cluster_name: str
    clustered: bool
    officer_id: str
    officer_name: str
    lead_id: str
    lead_name: str
    staff_visits: int = 0
    # Of those, the SSA Support visits (counted when staff schedule them).
    staff_ssa_visits: int = 0
    staff_visits_done: int = 0
    partner_visits: int = 0
    # Counted visits in a Partner's hands that the Partner has not dated.
    partner_visits_undated: int = 0
    partner_pending: int = 0
    group_training: bool = False
    meeting: bool = False
    in_school_training: bool = False
    training_done: bool = False
    in_project: bool = False
    # Places in open projects the person who holds this school used on it:
    # one for each project they added it to (`_count_project_places`).
    project_places: int = 0
    # The partner half of this Core school's package: visits and trainings a
    # partner holds, to the two of each it takes (`_count_core_packages`).
    core_partner_visits: int = 0
    core_partner_trainings: int = 0
    # The staff half's trainings, to the two it takes (owner, 2026-10-03).
    core_staff_trainings: int = 0

    @property
    def is_core(self) -> bool:
        return self.school_type in CORE_TYPES

    @property
    def has_visit(self) -> bool:
        return bool(self.staff_visits or self.partner_visits)

    @property
    def has_partner(self) -> bool:
        return bool(self.partner_visits or self.partner_pending)

    @property
    def awaiting_partner(self) -> bool:
        """Handed to a Partner who has not dated the visit yet. The school is
        covered — staff did their part — and it is not "planned by the
        Partner" until the Partner sets a date."""
        return self.has_partner and not self.has_visit

    @property
    def has_training(self) -> bool:
        """Attached to an in-school training or a group training (owner,
        2026-10-03: "for training look at inschool trainings and group
        trainings ... count all the schools attached to those"). A cluster
        meeting is not a training; it counted as one from 2026-09-28 until
        then, and is still shown beside the count."""
        return self.group_training or self.in_school_training

    @property
    def staff_scheduled(self) -> bool:
        """Staff scheduled a counted visit here themselves."""
        return self.staff_visits > 0

    @property
    def staff_and_partner(self) -> bool:
        """Scheduled by staff and also in a Partner's hands."""
        return self.staff_scheduled and self.has_partner

    @property
    def partner_visits_assigned(self) -> int:
        """The Partner's visits here, dated or still awaiting its date."""
        return self.partner_visits + self.partner_visits_undated

    @property
    def core_visits_over(self) -> bool:
        """A Core school with more visits than its package takes: two by
        staff and two by a Partner (owner, 2026-10-07). Staff and a Partner
        both visiting is the package itself, and is not flagged."""
        return self.is_core and (
            self.staff_visits > CORE_STAFF_VISITS_PER_SCHOOL
            or self.partner_visits_assigned > CORE_PARTNER_PER_SCHOOL
        )

    @property
    def needs_training(self) -> bool:
        """Whether a school of this type takes a training in the year (the
        rulebook): every type the monitor counts does; a type the rulebook
        gives none is never a school "with no training planned"."""
        from apps.planning.country_oversight import rules

        return rules.takes_training(self.school_type)

    @property
    def url(self) -> str:
        return f"/schools/{self.code or self.id}"

    @property
    def cluster_url(self) -> str:
        return f"/clusters/{self.cluster_id}" if self.cluster_id else ""

    def has_gap(self, gap: str) -> bool:
        if gap == "not_clustered":
            return not self.clustered
        # A school in a Partner's hands is not unplanned (owner, 2026-10-02
        # for the consolidated tables, and 2026-10-03 here: staff who had
        # handed every school over still read as having planned nothing).
        if gap == "no_visit":
            return not self.has_visit and not self.has_partner
        if gap == "no_training":
            return self.needs_training and not self.has_training
        if gap == "no_both":
            return not (self.has_visit or self.has_partner or self.has_training)
        if gap == "staff_scheduled":
            return self.staff_scheduled
        if gap == "staff_and_partner":
            return self.staff_and_partner
        if gap == "no_partner":
            return not self.is_core and not self.staff_visits and not self.has_partner
        return True


def _folded_once(cls):
    """Let a finished row work each of its figures out once.

    Every figure on a row is a property folded from the row's schools, and a
    page reads them thousands of times: the country's monitor asked one row
    for its Core schools 2,500 times and walked its schools each time, which
    was most of the page (2.2 million school reads; 2026-10-08).

    A row answers from memory only once `_settle` has marked it finished. The
    counting functions fill a row in place and read some of its figures while
    they do, so a row that is still being built answers as it always has.
    """

    def remembered(name, read):
        def figure(self):
            settled = self.__dict__.get("_settled")
            if settled is None:
                return read(self)
            try:
                return settled[name]
            except KeyError:
                value = settled[name] = read(self)
                return value

        figure.__name__ = name
        return figure

    for name, attr in list(vars(cls).items()):
        if isinstance(attr, property) and attr.fset is None and attr.fdel is None:
            setattr(cls, name, property(remembered(name, attr.fget), doc=attr.__doc__))
    return cls


def _settle(officers) -> None:
    """Mark these rows finished: every count is in and none will change."""
    for officer in officers:
        officer.__dict__["_settled"] = {}


@_folded_once
@dataclass
class OfficerMonitor:
    """One CCEO's year. Every figure is folded from ``schools``."""

    key: str
    name: str
    lead_id: str
    lead_name: str
    visits_target: int = DEFAULT_VISITS_TARGET
    role: str = ROLE_CCEO
    ids: frozenset = field(default_factory=frozenset)
    schools: list = field(default_factory=list)
    # Schools held that take no visit and no training (Champion: donor and
    # story visits only). Outside every visit and training figure, and still
    # part of what the person holds: the inventory and the project count read
    # them (apps.planning.readiness).
    outreach_schools: list = field(default_factory=list)
    # The visits this officer planned — theirs, at any school — split by the
    # school's type, and those already delivered (`_count_planned_visits`).
    planned_core: int = 0
    planned_client: int = 0
    planned_done: int = 0
    # The partner work this person hands over and monitors
    # (`_count_partner_work`, owner 2026-09-29): schools with a partner, the
    # partner's dated activities, those delivered, and handovers the partner
    # has not dated yet.
    partner_assigned_schools: int = 0
    partner_scheduled: int = 0
    partner_delivered: int = 0
    partner_awaiting: int = 0
    # Special Projects (`_count_project_places`, owner 2026-10-06): the
    # ceilings the Project Coordinator set this person on open projects, put
    # together, and the schools the person has added to open projects.
    project_ceiling: int = 0
    project_added: int = 0

    @property
    def list_scope(self) -> str:
        """What a count on this person's row adds to the monitor's address
        to open the schools behind it."""
        return f"&officer={self.key}"

    @property
    def is_lead(self) -> bool:
        return self.role == ROLE_PL

    @property
    def role_label(self) -> str:
        return {ROLE_PL: "Programme Lead", ROLE_CCEO: "CCEO"}.get(self.role, "")

    # ── Portfolio ──
    @property
    def school_count(self) -> int:
        return len(self.schools)

    @property
    def core_schools(self) -> int:
        return sum(1 for s in self.schools if s.is_core)

    @property
    def client_schools(self) -> int:
        return self.school_count - self.core_schools

    @property
    def outreach_count(self) -> int:
        return len(self.outreach_schools)

    # ── Visits against the target ──
    @property
    def core_visit_target(self) -> int:
        """Two at each Core school, to the person's target: with the Client
        visits it is the 280 or 560 the role plans, never more."""
        return min(CORE_STAFF_VISITS_PER_SCHOOL * self.core_schools, self.visits_target)

    @property
    def client_visit_target(self) -> int:
        return max(0, self.visits_target - self.core_visit_target)

    @property
    def core_visits(self) -> int:
        return self.planned_core

    @property
    def client_visits(self) -> int:
        return self.planned_client

    @property
    def staff_visits(self) -> int:
        return self.core_visits + self.client_visits

    @property
    def visits_done(self) -> int:
        return self.planned_done

    @property
    def visit_progress(self) -> int | None:
        return percentage(self.staff_visits, self.visits_target)

    @property
    def delivery_progress(self) -> int | None:
        return percentage(self.visits_done, self.staff_visits)

    # ── Past the ceiling (owner, 2026-10-03: it warns, it never refuses) ──
    @property
    def over_ceiling(self) -> int:
        """Counted visits planned past the visits the role plans in a year."""
        from apps.planning.country_oversight import rules

        return rules.over_ceiling(self.staff_visits, self.visits_target)

    @property
    def over_ceiling_people(self) -> int:
        return 1 if self.over_ceiling else 0

    @property
    def core_only_people(self) -> int:
        """1 when the Core schools held take the whole ceiling at two visits
        each (``rules.OVER_CAPACITY_CORE_ONLY``): every other school held is
        the Partner's."""
        from apps.planning.country_oversight import rules

        share = rules.workload(self.visits_target, self.core_schools, 0)
        return 1 if share.core_only else 0

    # ── Too few schools for the target (owner, 2026-10-07) ──
    @property
    def portfolio_visits(self) -> int:
        """Staff visits the schools held can take: two a Core school, one
        each of the others."""
        return self._workload.portfolio_visits

    @property
    def schools_to_recruit(self) -> int:
        """Schools the person still needs to recruit for their schools to
        take the visits their role plans (``rules.Workload.short_of_target``)."""
        return self._workload.short_of_target

    @property
    def short_people(self) -> int:
        return 1 if self.schools_to_recruit else 0

    @property
    def _workload(self):
        from apps.planning.country_oversight import rules

        return rules.workload(
            self.visits_target, self.core_schools, self.client_schools
        )

    # ── The partner's share ──
    @property
    def partner_needed(self) -> int:
        return max(0, self.client_schools - self.client_visit_target)

    @property
    def partner_schools(self) -> int:
        return sum(1 for s in self.schools if not s.is_core and s.has_partner)

    @property
    def partner_remaining(self) -> int:
        """Schools beyond staff reach that no partner holds yet."""
        return max(0, self.partner_needed - self.partner_schools)

    @property
    def partner_tone(self) -> str:
        if not self.partner_needed:
            return "neutral"
        return "success" if not self.partner_remaining else "warning"

    # ── The Core package's partner half ──
    @property
    def core_partner_target(self) -> int:
        """Partner visits — and as many partner trainings — the Core
        packages take: two a school."""
        return CORE_PARTNER_PER_SCHOOL * self.core_schools

    @property
    def core_partner_visits(self) -> int:
        return sum(s.core_partner_visits for s in self.schools if s.is_core)

    @property
    def core_partner_trainings(self) -> int:
        return sum(s.core_partner_trainings for s in self.schools if s.is_core)

    @property
    def core_partner_visits_tone(self) -> str:
        return _share_tone(self.core_partner_visits, self.core_partner_target)

    @property
    def core_partner_trainings_tone(self) -> str:
        return _share_tone(self.core_partner_trainings, self.core_partner_target)

    # ── The staff half's trainings, and the Partner's whole target ──
    @property
    def core_staff_training_target(self) -> int:
        """Staff trainings the Core packages take: two a school, beside the
        two staff visits and using none of the visit ceiling."""
        return CORE_STAFF_VISITS_PER_SCHOOL * self.core_schools

    @property
    def core_staff_trainings(self) -> int:
        return sum(s.core_staff_trainings for s in self.schools if s.is_core)

    @property
    def core_staff_trainings_tone(self) -> str:
        return _share_tone(self.core_staff_trainings, self.core_staff_training_target)

    @property
    def partner_visit_target(self) -> int:
        """The Partner's visits at this person's schools (owner, 2026-10-03:
        "the overflow should be the partner target"): two at each Core school
        and one at each school beyond staff reach."""
        return self.core_partner_target + self.partner_needed

    # ── Coverage ──
    @property
    def schools_with_visit(self) -> int:
        return sum(1 for s in self.schools if s.has_visit)

    @property
    def training_schools(self) -> int:
        """The schools that take a training in the year: the ones training
        coverage is read against."""
        return sum(1 for s in self.schools if s.needs_training)

    @property
    def schools_with_training(self) -> int:
        return sum(1 for s in self.schools if s.needs_training and s.has_training)

    @property
    def schools_group_training(self) -> int:
        return sum(1 for s in self.schools if s.group_training)

    @property
    def schools_meeting(self) -> int:
        return sum(1 for s in self.schools if s.meeting)

    @property
    def schools_trained(self) -> int:
        return sum(1 for s in self.schools if s.training_done)

    @property
    def not_clustered(self) -> int:
        return sum(1 for s in self.schools if not s.clustered)

    @property
    def schools_staff_scheduled(self) -> int:
        """Schools held that staff scheduled a counted visit at themselves
        (owner, 2026-10-03: "how many schools the staff has scheduled for
        visits for themselves")."""
        return sum(1 for s in self.schools if s.staff_scheduled)

    @property
    def schools_staff_and_partner(self) -> int:
        """Of those, the schools also in a Partner's hands."""
        return sum(1 for s in self.schools if s.staff_and_partner)

    @property
    def client_staff_and_partner(self) -> int:
        """The Client, Core Trained and Core Graduate schools among them. Such
        a school takes one visit, staff's or the Partner's: it is booked
        twice (``readiness.is_duplicate``). A Core school takes both, so it
        is flagged only past its package (``core_visits_over``)."""
        return sum(1 for s in self.schools if not s.is_core and s.staff_and_partner)

    @property
    def core_visits_over(self) -> int:
        """Core schools with more than two staff visits or two Partner visits."""
        return sum(1 for s in self.schools if s.core_visits_over)

    @property
    def schools_in_school_training(self) -> int:
        return sum(1 for s in self.schools if s.in_school_training)

    @property
    def schools_awaiting_partner(self) -> int:
        """Schools handed to a Partner and not yet dated by it."""
        return sum(1 for s in self.schools if s.awaiting_partner)

    @property
    def schools_covered(self) -> int:
        """Schools with a visit planned or in a Partner's hands."""
        return self.schools_with_visit + self.schools_awaiting_partner

    @property
    def no_visit(self) -> int:
        """Schools with no visit planned yet, a Partner's undated ones
        included: Country Planning Oversight's ``no_visit``."""
        return self.school_count - self.schools_with_visit

    @property
    def unplanned(self) -> int:
        """Of those, the schools no Partner holds either: nobody has them to
        plan (Country Planning Oversight's ``unplanned``). This is what the
        page shows as "No visit": a school handed to a Partner is the
        Partner's to date, and reading it as unplanned made staff who had
        handed every school over look as if they had planned nothing (owner,
        2026-10-03)."""
        return self.school_count - self.schools_covered

    @property
    def no_training(self) -> int:
        return self.training_schools - self.schools_with_training

    @property
    def no_both(self) -> int:
        return sum(1 for s in self.schools if s.has_gap("no_both"))

    @property
    def in_projects(self) -> int:
        return sum(1 for s in self.schools if s.in_project)

    @property
    def visit_tone(self) -> str:
        # Past the ceiling is not a better plan than one at it.
        return "danger" if self.over_ceiling else _tone(self.visit_progress)

    @property
    def gap_cells(self) -> list[tuple[dict, int]]:
        return _gap_cells(self)


#: OfficerMonitor's plain counts a lead's and the country's rows add up.
SUMMED_FIELDS = (
    "planned_core",
    "planned_client",
    "planned_done",
    "partner_assigned_schools",
    "partner_scheduled",
    "partner_delivered",
    "partner_awaiting",
)


@dataclass
class LeadMonitor:
    """A Programme Lead's column: their CCEOs, and the sums of them."""

    key: str
    name: str
    officers: list = field(default_factory=list)

    def _sum(self, attr: str) -> int:
        return sum(getattr(o, attr) for o in self.officers)

    def __getattr__(self, attr):
        # Every OfficerMonitor count sums the same way; spelling each one out
        # again would be two definitions of one figure.
        if attr.startswith("_") or attr in ("key", "name", "officers"):
            raise AttributeError(attr)
        if isinstance(getattr(OfficerMonitor, attr, None), property) or attr in (
            "visits_target",
            *SUMMED_FIELDS,
        ):
            return self._sum(attr)
        raise AttributeError(attr)

    @property
    def list_scope(self) -> str:
        """A team's counts open its own people's schools; the total's open
        everyone's."""
        return "" if self.key == "all" else f"&program_lead={self.key}"

    @property
    def visit_progress(self) -> int | None:
        return percentage(self.staff_visits, self.visits_target)

    @property
    def delivery_progress(self) -> int | None:
        return percentage(self.visits_done, self.staff_visits)

    @property
    def visit_tone(self) -> str:
        return _tone(self.visit_progress)

    @property
    def partner_tone(self) -> str:
        if not self.partner_needed:
            return "neutral"
        return "success" if not self.partner_remaining else "warning"

    @property
    def core_partner_visits_tone(self) -> str:
        return _share_tone(self.core_partner_visits, self.core_partner_target)

    @property
    def core_partner_trainings_tone(self) -> str:
        return _share_tone(self.core_partner_trainings, self.core_partner_target)

    @property
    def core_staff_trainings_tone(self) -> str:
        return _share_tone(self.core_staff_trainings, self.core_staff_training_target)

    @property
    def officer_count(self) -> int:
        return len(self.officers)

    @property
    def gap_cells(self) -> list[tuple[dict, int]]:
        return _gap_cells(self)


def _share_tone(part: int, whole: int) -> str:
    """How a count reads against what it should reach; no tone for nothing
    to reach."""
    if not whole:
        return "neutral"
    return "success" if part >= whole else "warning"


def _tone(progress: int | None) -> str:
    if progress is None:
        return "neutral"
    if progress >= 100:
        return "success"
    if progress >= 50:
        return "info"
    return "warning"


def planning_monitor(
    principal,
    *,
    fy: str,
    program_lead_id: str | None = None,
    gap: str | None = None,
    officer_id: str | None = None,
    school_type: str = "",
) -> dict:
    """The monitor for this reader and year.

    Returns ``leads`` (LeadMonitor, each holding its OfficerMonitors),
    ``totals`` (a LeadMonitor over everyone), ``lead_options``, and
    ``gap_schools`` — the schools matching the chosen gap, narrowed to the
    chosen lead and officer, for the drill-down table.
    """
    from apps.planning.portfolio_service import NO_LEAD_KEY, UNASSIGNED_KEY

    fy = str(fy)
    empty = {
        "fy": fy,
        "leads": [],
        "totals": LeadMonitor(key="all", name="All"),
        "lead_options": [],
        "officer_options": [],
        "gap_schools": [],
    }
    queryset = _monitored_schools(principal)
    if queryset is None:
        return empty
    schools, outreach = _school_states(queryset, fy)

    officers, leads = _people(principal, {**schools, **outreach})
    if not officers:
        return empty
    for school in (*schools.values(), *outreach.values()):
        officer = officers[school.officer_id]
        # The school follows its officer to the team the roster files them
        # under, so a school and its officer never sit under two Leads.
        school.lead_id, school.lead_name = officer.lead_id, officer.lead_name
        if school.id in schools:
            officer.schools.append(school)
        else:
            officer.outreach_schools.append(school)

    _count_planned_visits(officers.values(), fy)
    _count_partner_work(officers.values(), fy)
    _count_project_places(officers.values())
    _settle(officers.values())

    # The roster's order: each Lead, then their CCEOs by name; the country's
    # CCEOs with no Lead, and schools with no officer, last.
    ordered = sorted(
        (lead for lead in leads.values() if lead.officers),
        key=lambda g: (g.key == NO_LEAD_KEY, g.key == UNASSIGNED_KEY),
    )
    lead_options = [
        {"id": lead.key, "name": lead.name, "count": lead.school_count}
        for lead in ordered
    ]
    totals = LeadMonitor(
        key="all",
        name="All",
        officers=[officer for lead in ordered for officer in lead.officers],
    )

    shown = ordered
    if program_lead_id and program_lead_id not in ("all", "All"):
        shown = [lead for lead in ordered if lead.key == program_lead_id] or ordered
    officer_options = [
        {"id": officer.key, "name": officer.name}
        for lead in shown
        for officer in lead.officers
    ]
    gap_schools = []
    if gap in GAP_LABELS:
        gap_schools = list_schools(
            (
                officer
                for lead in shown
                for officer in lead.officers
                if not officer_id or officer.key == officer_id
            ),
            gap,
            school_type=school_type,
        )

    return {
        "fy": fy,
        "leads": shown,
        "totals": totals,
        "lead_options": lead_options,
        "officer_options": officer_options,
        "gap_schools": gap_schools,
    }


def _school_states(base, fy: str) -> tuple[dict, dict]:
    """(monitored, outreach): a SchoolState for every operating school in
    ``base``, counted for ``fy``.

    *Monitored* are the types the requirement asks a visit of; *outreach* is
    every other operating school (Champion). Nothing operating is left out of
    both: a school that takes no visit is still held by somebody and still
    belongs to a project or to none.
    """
    from apps.planning.portfolio_service import (
        NO_LEAD_KEY,
        NO_LEAD_LABEL,
        UNASSIGNED_KEY,
        UNASSIGNED_LABEL,
        _staff_directory,
    )
    from apps.schools.lifecycle_service import active_schools

    operating = active_schools(base)
    queryset = operating.filter(school_type__in=MONITORED_TYPES)
    rows = list(
        operating.order_by("name").values(
            "id",
            "school_id",
            "name",
            "school_type",
            "district__name",
            "cluster_id",
            "cluster_status",
            "account_owner_id",
        )
    )
    directory = _staff_directory({r["account_owner_id"] for r in rows})
    clusters = _cluster_names({r["cluster_id"] for r in rows})
    active_clusters = _active_clusters(set(clusters))
    schools: dict[str, SchoolState] = {}
    outreach: dict[str, SchoolState] = {}
    for r in rows:
        owner = directory.get(str(r["account_owner_id"] or ""))
        state = SchoolState(
            id=r["id"],
            code=r["school_id"] or "",
            name=r["name"],
            school_type=r["school_type"] or "",
            district=r["district__name"] or "",
            cluster_id=r["cluster_id"] or "",
            cluster_name=clusters.get(r["cluster_id"], ""),
            # In an ACTIVE cluster, as Country Planning Oversight reads it.
            clustered=r["cluster_id"] in active_clusters,
            officer_id=owner["officer_id"] if owner else UNASSIGNED_KEY,
            officer_name=owner["officer_name"] if owner else UNASSIGNED_LABEL,
            lead_id=owner["lead_id"] if owner else NO_LEAD_KEY,
            lead_name=owner["lead_name"] if owner else NO_LEAD_LABEL,
        )
        if state.school_type in MONITORED_TYPES:
            schools[state.id] = state
        else:
            outreach[state.id] = state

    if schools:
        school_ids = queryset.values("id")
        _count_activities(schools, school_ids, fy)
        _count_partner_handovers(schools, school_ids)
        _count_cluster_sessions(schools, school_ids, fy)
        _mark_projects(schools, school_ids)
        _count_core_packages(schools, fy)
    if outreach:
        _mark_projects(outreach, list(outreach))
    return schools, outreach


def own_monitor(principal, fy: str) -> OfficerMonitor | None:
    """One Programme Lead's or CCEO's own year: the row the Planning Monitor
    shows their Lead and the Country Director, built for the person
    themselves. None for anybody whose role plans no visits."""
    from apps.core.scoping import owner_ids
    from apps.planning.country_oversight import rules
    from apps.planning.monitor_roster import _role_code
    from apps.schools.models import School

    role = _role_code(
        rules.planning_role(
            getattr(principal, "roles", None), getattr(principal, "active_role", None)
        )
        or ""
    )
    if not role:
        return None
    ids = frozenset(str(i) for i in owner_ids(principal) if i)
    fy = str(fy)
    schools, outreach = _school_states(
        School.objects.filter(account_owner_id__in=list(ids)), fy
    )
    officer = OfficerMonitor(
        key=str(getattr(principal, "staff_profile_id", "") or next(iter(ids), "")),
        name=getattr(principal, "name", "") or getattr(principal, "email", "") or "",
        lead_id="",
        lead_name="",
        visits_target=VISITS_TARGET_BY_ROLE.get(role, 0),
        role=role,
        ids=ids,
        schools=list(schools.values()),
        outreach_schools=list(outreach.values()),
    )
    _count_planned_visits([officer], fy)
    _count_partner_work([officer], fy)
    _count_project_places([officer])
    return officer


def schools_in_scope(principal) -> int | None:
    """How many operating schools this reader's monitor should hold, counted
    apart from its rows: what `apps.planning.readiness` checks them against.
    """
    from apps.schools.lifecycle_service import active_schools

    queryset = _monitored_schools(principal)
    return None if queryset is None else active_schools(queryset).count()


def _monitored_schools(principal):
    """The schools this reader's monitor follows.

    The country reads the country. A Programme Lead reads the schools HELD by
    themselves and the people who report to them — ``School.account_owner_id``,
    the column every row of the monitor is filed by — and the schools in
    their scope that nobody holds yet.

    The Lead's scope used to decide it (``StaffSchoolAssignment``), and the
    two can part company: an upload, an edit or a bulk match that names a new
    holder adds the new holder's assignment row and has not always removed
    the old one. The old holder's Lead then counted the school, and the
    monitor added a row for a person on somebody else's team to file it
    under. Read by the holder, a school sits in one team's monitor — the one
    the Country Director's page files it in — and a Lead's rows are their
    own people.
    """
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.planning.oversight_service import resolve_oversight_scope

    user_scope = resolve_user_scope(principal)
    queryset = scoped_school_queryset(user_scope)
    oversight_scope = resolve_oversight_scope(principal)
    if queryset is None or oversight_scope.kind != "pl":
        return queryset

    held = Q(account_owner_id__in=list(oversight_scope.team_ids))
    unheld_in_scope = Q(id__in=list(user_scope.school_ids or [])) & (
        Q(account_owner_id__isnull=True) | Q(account_owner_id="")
    )
    from apps.schools.models import School

    return School.objects.filter(deleted_at__isnull=True).filter(held | unheld_in_scope)


def _both_ids(staff_ids) -> dict[str, frozenset]:
    """Each StaffProfile id with the User id of the same person: an
    activity names its officer in either (apps.core.scoping.owner_ids)."""
    from apps.accounts.models import StaffProfile

    ids = {str(i) for i in staff_ids if i}
    spaces = {i: {i} for i in ids}
    for staff_id, user_id in StaffProfile.objects.filter(id__in=ids).values_list(
        "id", "user_id"
    ):
        if user_id:
            spaces[str(staff_id)].add(str(user_id))
    return {key: frozenset(value) for key, value in spaces.items()}


def _people(principal, schools: dict) -> tuple[dict, dict]:
    """Every person the reader follows, and a row for whoever else holds a
    school in scope.

    The roster (apps.planning.monitor_roster) comes first, so a Lead or a
    CCEO who holds no school is still a row with their plan against their
    target. An owner the roster does not name — a CCEO whose Lead is outside
    this reader's teams, or someone in another role — keeps a row under the
    Lead the directory files them with, so no school in scope drops out of
    the totals. Schools with no owner are one "Unassigned" row with no
    target: nobody is planning against it.
    """
    from apps.planning.monitor_roster import monitor_roster, roles_of
    from apps.planning.portfolio_service import (
        NO_LEAD_KEY,
        NO_LEAD_LABEL,
        UNASSIGNED_KEY,
        UNASSIGNED_LABEL,
    )

    officers: dict[str, OfficerMonitor] = {}
    leads: dict[str, LeadMonitor] = {}

    def lead_for(key, name):
        lead = leads.get(key)
        if lead is None:
            lead = leads[key] = LeadMonitor(key=key, name=name)
        return lead

    def add(lead, key, name, role, ids, target):
        officer = officers[key] = OfficerMonitor(
            key=key,
            name=name,
            lead_id=lead.key,
            lead_name=lead.name,
            visits_target=target,
            role=role,
            ids=frozenset(ids),
        )
        lead.officers.append(officer)
        return officer

    lead_hint = {s.lead_id for s in schools.values()}
    for team in monitor_roster(principal, lead_ids_hint=lead_hint):
        lead = lead_for(team.key, team.name)
        for person in team.people:
            if person.key not in officers:
                add(
                    lead,
                    person.key,
                    person.name,
                    person.role,
                    person.ids,
                    person.visits_target,
                )

    extra = [
        s
        for s in schools.values()
        if s.officer_id not in officers and s.officer_id != UNASSIGNED_KEY
    ]
    roles = roles_of({s.officer_id for s in extra})
    # Both id spaces, as the roster's people carry them: with the profile id
    # alone, the visits such a person planned under their User id went
    # uncounted (a deactivated officer read 6 of their 12).
    extra_ids = _both_ids({s.officer_id for s in extra})
    for school in sorted(extra, key=lambda s: s.officer_name.casefold()):
        if school.officer_id in officers:
            continue
        role = roles.get(school.officer_id, "")
        lead = lead_for(
            school.lead_id if school.lead_id in leads else NO_LEAD_KEY,
            school.lead_name if school.lead_id in leads else NO_LEAD_LABEL,
        )
        add(
            lead,
            school.officer_id,
            school.officer_name,
            role,
            extra_ids.get(str(school.officer_id), {school.officer_id}),
            VISITS_TARGET_BY_ROLE.get(role, 0),
        )
    if any(s.officer_id == UNASSIGNED_KEY for s in schools.values()):
        add(
            lead_for(UNASSIGNED_KEY, UNASSIGNED_LABEL),
            UNASSIGNED_KEY,
            UNASSIGNED_LABEL,
            "",
            (),
            0,
        )
    return officers, leads


def _active_clusters(cluster_ids) -> set:
    from apps.clusters.models import Cluster

    if not cluster_ids:
        return set()
    return set(
        Cluster.objects.filter(id__in=cluster_ids, status="active").values_list(
            "id", flat=True
        )
    )


def _cluster_names(cluster_ids) -> dict[str, str]:
    from apps.clusters.models import Cluster

    ids = {c for c in cluster_ids if c}
    if not ids:
        return {}
    return dict(Cluster.objects.filter(id__in=ids).values_list("id", "name"))


def _planned(qs):
    """Activities that are a plan, by the rulebook: a scheduled-or-later
    state with a date on it, and not deleted."""
    from apps.planning.country_oversight import rules

    return qs.filter(rules.planned_q(), deleted_at__isnull=True)


def _counted_visits(qs):
    """Of those, the visits that count: Follow up, In-school Training and
    SSA Support at a school (apps.planning.country_oversight.rules)."""
    from apps.planning.country_oversight import rules

    return _planned(qs).filter(rules.counted_visit_q())


def _delivered_statuses():
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        VERIFIED_STATUSES,
    )

    return AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES


def _count_activities(schools: dict, school_ids, fy: str) -> None:
    """Counted visits and in-school trainings at each school, planned and
    delivered. A Partner's visit counts once the Partner has dated it."""
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.activities.models import Activity
    from apps.planning.country_oversight import rules

    delivered = _delivered_statuses()
    # The school's SSA-measured support. Alumni work (a project no SSA
    # intervention measures) is not a visit or a training here and does not
    # put the school in a Partner's hands.
    at_schools = Activity.objects.filter(school_id__in=school_ids, fy=fy).filter(
        rules.not_outside_ssa_q()
    )
    for school_id, delivery_type, status, n, ssa in (
        _counted_visits(at_schools)
        .filter(rules.staff_delivery_q() | rules.partner_planned_q())
        .values_list("school_id", "delivery_type", "status")
        .annotate(n=Count("id"), ssa=Count("id", filter=rules.kind_q(rules.KIND_SSA)))
        .order_by()
    ):
        school = schools.get(school_id)
        if school is None:
            continue
        if delivery_type == "partner":
            school.partner_visits += n
        else:
            school.staff_visits += n
            school.staff_ssa_visits += ssa
            if status in delivered:
                school.staff_visits_done += n
    for school_id, status in (
        _planned(at_schools)
        .filter(activity_type__in=SCHOOL_TRAINING_TYPES, cluster_id__isnull=True)
        .filter(rules.staff_delivery_q() | rules.partner_planned_q())
        .values_list("school_id", "status")
        .order_by()
    ):
        school = schools.get(school_id)
        if school is None:
            continue
        school.in_school_training = True
        if status in delivered:
            school.training_done = True
    # Partner work a Partner has not dated: the school is in its hands.
    for school_id, n, visits in (
        at_schools.filter(deleted_at__isnull=True)
        .filter(rules.partner_held_q())
        .exclude(rules.partner_planned_q())
        .values_list("school_id")
        .annotate(n=Count("id"), visits=Count("id", filter=rules.counted_visit_q()))
        .order_by()
    ):
        if school_id in schools:
            schools[school_id].partner_pending += n
            schools[school_id].partner_visits_undated += visits


def _count_planned_visits(officers, fy: str) -> None:
    """Each person's own counted visits in the year, wherever they are.

    Counted by the person who planned them — the responsible officer, in
    either id space — as My Plan and Team Plan count them, not by who owns the
    school: a CCEO's visit at a colleague's school is still one of the CCEO's
    560 (owner, 2026-09-28: "the PL are seeing exactly the number ... planned
    by the CCEO"). Core or client by the school's type. A Lead's visit counts
    for the Lead; a partner's delivery does not.

    The count is ``staff_plan.visit_tallies``, the one My Plan shows each
    person as their own visits toward the target (owner, 2026-10-02: the
    Lead's figure and the CCEO's are one figure).
    """
    from apps.planning.staff_plan import visit_tallies

    officers = list(officers)
    tallies = visit_tallies({id(officer): officer.ids for officer in officers}, fy)
    for officer in officers:
        tally = tallies[id(officer)]
        officer.planned_core = tally.core
        officer.planned_client = tally.client
        officer.planned_done = tally.delivered


def _count_partner_work(officers, fy: str) -> None:
    """Each person's partner work in the year, as Country Planning Oversight
    counts it.

    * **Schools with a partner** — distinct schools the person has handed to
      a partner: a handover they assigned or monitor that is still waiting,
      or a partner activity they monitor this year.
    * **Scheduled by partners** — of that work, what the PARTNER has dated
      (staff assign a school; the partner sets the date), and of those, the
      delivered ones.
    * **Awaiting the partner's date** — work in the partner's hands with no
      date of the partner's on it yet.
    """
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules

    by_id = {i: officer for officer in officers for i in officer.ids}
    if not by_id:
        return
    ids = list(by_id)
    delivered = _delivered_statuses()
    schools: dict[int, set] = {}

    def owner_of(*candidates):
        """Whoever the record names first: its monitor, then who assigned or
        is responsible for it, then whoever holds the school — the order
        Country Planning Oversight credits Partner work in."""
        for candidate in candidates:
            if candidate:
                return by_id.get(str(candidate))
        return None

    carried = set(
        PartnerAssignment.objects.filter(
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            source_activity_id__isnull=False,
        ).values_list("source_activity_id", flat=True)
    )
    from django.db.models import Case, IntegerField, Value, When

    for activity_id, monitor, responsible, holder, school_id, status, dated in (
        Activity.objects.filter(fy=fy, deleted_at__isnull=True)
        .filter(rules.partner_held_q())
        .filter(rules.not_outside_ssa_q())
        .filter(
            Q(monitored_by_staff_id__in=ids)
            | Q(responsible_staff_id__in=ids)
            | Q(school__account_owner_id__in=ids)
        )
        .annotate(
            dated=Case(
                When(rules.partner_planned_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .values_list(
            "id",
            "monitored_by_staff_id",
            "responsible_staff_id",
            "school__account_owner_id",
            "school_id",
            "status",
            "dated",
        )
    ):
        officer = owner_of(monitor, responsible, holder)
        if officer is None or activity_id in carried:
            continue
        if dated:
            officer.partner_scheduled += 1
            if status in delivered:
                officer.partner_delivered += 1
        else:
            officer.partner_awaiting += 1
        if school_id:
            schools.setdefault(id(officer), set()).add(school_id)

    handovers = PartnerAssignment.objects.filter(
        Q(monitoring_staff_id__in=ids)
        | Q(assigning_staff_id__in=ids)
        | Q(school__account_owner_id__in=ids),
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
    ).filter(rules.not_outside_ssa_q())
    for monitor, assigner, holder, school_id in handovers.values_list(
        "monitoring_staff_id",
        "assigning_staff_id",
        "school__account_owner_id",
        "school_id",
    ):
        officer = owner_of(monitor, assigner, holder)
        if officer is None:
            continue
        officer.partner_awaiting += 1
        if school_id:
            schools.setdefault(id(officer), set()).add(school_id)

    for officer in officers:
        officer.partner_assigned_schools = len(schools.get(id(officer), ()))


def _count_partner_handovers(schools: dict, school_ids) -> None:
    """Handovers a partner has not dated yet: the school is the partner's."""
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules

    for school_id, n in (
        PartnerAssignment.objects.filter(
            school_id__in=school_ids,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        )
        .filter(rules.not_outside_ssa_q())
        .values("school_id")
        .annotate(n=Count("id"))
        .values_list("school_id", "n")
    ):
        if school_id in schools:
            schools[school_id].partner_pending += n


def _count_cluster_sessions(schools: dict, school_ids, fy: str) -> None:
    """Group trainings and cluster meetings each school is invited to.

    By name — ClusterActivityAttendance, written when the session is
    scheduled — never because the school happens to be in the cluster
    (apps.schools.school_status.cluster_training_coverage holds the same
    line). Delivered once the school is marked as having attended a
    delivered session.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    delivered = _delivered_statuses()
    sessions = _planned(Activity.objects.filter(fy=fy, cluster_id__isnull=False))
    meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
    training_types = {str(t) for t in TRAINING_TYPES}
    for school_id, activity_type, status, attended in (
        ClusterActivityAttendance.objects.filter(
            school_id__in=school_ids,
            activity__in=sessions.filter(
                Q(activity_type__in=meeting_types) | Q(activity_type__in=training_types)
            ),
        )
        .filter(Q(invited=True) | Q(attended=True))
        .values_list(
            "school_id", "activity__activity_type", "activity__status", "attended"
        )
    ):
        school = schools.get(school_id)
        if school is None:
            continue
        if activity_type in meeting_types:
            school.meeting = True
        else:
            school.group_training = True
        if attended and status in delivered:
            school.training_done = True


def _count_core_packages(schools: dict, fy: str) -> None:
    """The partner half of each Core school's package.

    Read from the package's own split (apps.core_schools.package_split), the
    count every hand-over door refuses by, so the monitor and the drawers
    cannot disagree about whether a school's partner half is taken. Each kind
    is counted to the two it takes: a package over its half does not cover
    for another school's empty one.
    """
    from types import SimpleNamespace

    from apps.core_schools.package_split import PARTNER, TRAINING, VISIT, package_splits

    core = [
        SimpleNamespace(id=s.id, school_id=s.code, school_type=s.school_type)
        for s in schools.values()
        if s.is_core and s.code
    ]
    if not core:
        return
    for school_id, split in package_splits(core, fy).items():
        school = schools[school_id]
        school.core_partner_visits = min(
            split.used(VISIT, PARTNER), CORE_PARTNER_PER_SCHOOL
        )
        school.core_partner_trainings = min(
            split.used(TRAINING, PARTNER), CORE_PARTNER_PER_SCHOOL
        )
        school.core_staff_trainings = min(
            split.staff_trainings, CORE_STAFF_VISITS_PER_SCHOOL
        )


def _count_project_places(officers) -> None:
    """Each person's project ceilings, put together, and the schools they
    have added to projects (owner, 2026-10-06: "calculate all the schools the
    user added to the project against the project general ceiling (all project
    ceilings put together)").

    Both are read as the Project Capacity page and the person's own "My
    project allocations" table read them (apps.projects.capacity): a ceiling
    is a ``ProjectStaffCapacity`` row, and a place is used by an enrolment
    whose ``assigned_staff`` is the person. So the target here is that
    table's Maximum column added up. A school withdrawn from a project has no
    enrolment, so its place is back the moment it leaves. Two queries,
    whatever the number of people.
    """
    from django.db.models import Sum

    from apps.projects.models import ProjectSchoolAssignment, ProjectStaffCapacity

    by_id: dict[str, OfficerMonitor] = {}
    held: dict[tuple[int, str], SchoolState] = {}
    for officer in officers:
        officer.project_ceiling = officer.project_added = 0
        for staff_id in officer.ids:
            by_id[str(staff_id)] = officer
        for school in (*officer.schools, *officer.outreach_schools):
            school.project_places = 0
            held[(id(officer), school.id)] = school
    if not by_id:
        return
    for staff_id, ceiling in (
        ProjectStaffCapacity.objects.filter(
            staff_id__in=list(by_id), project__deleted_at__isnull=True
        )
        .values_list("staff_id")
        .annotate(ceiling=Sum("max_schools"))
        .order_by()
    ):
        by_id[str(staff_id)].project_ceiling += int(ceiling or 0)
    for staff_id, school_id in ProjectSchoolAssignment.objects.filter(
        assigned_staff_id__in=list(by_id), project__deleted_at__isnull=True
    ).values_list("assigned_staff_id", "school_id"):
        officer = by_id[str(staff_id)]
        officer.project_added += 1
        school = held.get((id(officer), school_id))
        if school is not None:
            school.project_places += 1


def _mark_projects(schools: dict, school_ids) -> None:
    """Schools enrolled in an open Special Project."""
    from apps.projects.models import OPEN_PROJECT_STATUSES, ProjectSchoolAssignment

    open_statuses = [str(getattr(s, "value", s)) for s in OPEN_PROJECT_STATUSES]
    for school_id in (
        ProjectSchoolAssignment.objects.filter(
            school_id__in=school_ids,
            project__deleted_at__isnull=True,
            project__status__in=open_statuses,
        )
        .values_list("school_id", flat=True)
        .distinct()
    ):
        if school_id in schools:
            schools[school_id].in_project = True


__all__ = [
    "CCEO_VISITS_TARGET",
    "CORE_STAFF_VISITS_PER_SCHOOL",
    "DEFAULT_VISITS_TARGET",
    "PL_VISITS_TARGET",
    "PLANNED_VISIT_TYPES",
    "GAPS",
    "GAP_LABELS",
    "LeadMonitor",
    "OfficerMonitor",
    "SchoolState",
    "own_monitor",
    "planning_monitor",
]
