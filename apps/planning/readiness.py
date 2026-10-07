"""Planned and remaining: one person's year in four parts, and one score.

Owner, 2026-10-07: "280/560 ... are target visits set for PL/CCEO and once
they have planned to that target, the rest they are supposed to assign to the
partners", and, of somebody who holds fewer schools than that: always 280 /
560, "but those with less should be notified to recruit more schools to meet
the target". So a Programme Lead reads against 280 visits and a CCEO against
560 whatever they hold, and a person whose schools cannot supply that many is
told how many more to recruit (``schools_to_recruit``).

This reverses the reading of 2026-10-03, when the target was the ceiling "or,
for a portfolio that asks for fewer, what it asks for": a small portfolio
fully planned read 100% then, and reads its visits of 280 or 560 now.

This module reads the monitor's own rows (apps.planning.planning_monitor), so
it counts nothing a second time, and says for each Programme Lead and CCEO,
each team and the country:

* **Visits** — staff: two at each Core school and one at each Client, Core
  Trained and Core Graduate school, up to the ceiling (280 / 560). What
  counts toward it is every Follow up, In-school Training and SSA Support
  visit staff schedule themselves (a Partner's SSA Support does not). The target
  is the role's 280 or 560, whatever the person holds.
  Partner: the other two at each Core school and one at every school beyond
  that target. A Partner visit is planned once the Partner has dated it.
* **Trainings** — the schools attached to an in-school training or a group
  training, of the schools that take a training (owner, 2026-10-03: "count
  all the schools attached to those"). A cluster meeting is not a training.
  Beside it, the Partner's half of the Core packages: two trainings a school.
* **Partner assignment** — every Core school (for the Partner's half of its
  package) and every school beyond staff capacity, against those in a
  Partner's hands.
* **Project assignment** — the schools the person has added to projects,
  against the ceilings the Project Coordinator set them on their projects,
  put together (owner, 2026-10-06). What remains is what is left to
  reach those ceilings, not every school the person holds that is in no
  project: it used to read 1,102 of 1,147 remaining for somebody whose
  ceilings asked for a few dozen. Somebody with no ceiling is asked nothing.

Each part has a target, what is planned and what remains, and a percentage
that stops at 100: planning past a target is shown as over, never as cover for
another gap. A part that asks nothing (nobody to hand over to a Partner)
is complete. **Readiness** is the plain average of the four.

Staff plan to their target first; the schools beyond it are the Partner's. A
school handed over inside the target is counted with a Partner and is not
asked of the Partner twice.

The target still warns and never refuses (owner, 2026-10-03), and nothing
here assigns a school to anybody: the Partner's share is a target.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from apps.planning.country_oversight import rules

logger = logging.getLogger(__name__)

FULLY, PARTLY, NOT_YET = "fully", "partly", "not_yet"

VISITS, TRAININGS, PARTNER, PROJECT = "visits", "trainings", "partner", "project"
PILLAR_LABELS = {
    VISITS: "Visits",
    TRAININGS: "Trainings",
    PARTNER: "Partner assignment",
    PROJECT: "Project assignment",
}


def _share(part: int, whole: int) -> int:
    """Whole percent, rounded down: 279 of 280 is 99, never 100. Nothing to
    reach is complete."""
    if whole <= 0:
        return 100
    return max(0, min(100, part * 100 // whole))


@dataclass(frozen=True)
class Line:
    """A target, what is planned against it, and what remains."""

    target: int
    planned: int
    # ``planned`` no further than each person's own target, so one person's
    # extra does not close another's gap in a team's or the country's line.
    credited: int

    @property
    def remaining(self) -> int:
        return max(0, self.target - self.credited)

    @property
    def over(self) -> int:
        return max(0, self.planned - self.credited)

    @property
    def percent(self) -> int:
        return _share(self.credited, self.target)

    @property
    def required(self) -> bool:
        return self.target > 0

    @property
    def tone(self) -> str:
        if not self.required:
            return "neutral"
        if self.remaining == 0:
            return "success"
        return "info" if self.percent >= 50 else "warning"


@dataclass
class TypeInventory:
    """One school type: every school is in exactly one of the three states."""

    key: str
    label: str
    total: int = 0
    fully: int = 0
    partly: int = 0
    not_yet: int = 0
    in_project: int = 0

    @property
    def outreach_only(self) -> bool:
        return not rules.requirement_for(self.key).visits

    @property
    def balanced(self) -> bool:
        return self.fully + self.partly + self.not_yet == self.total


_SUMMED = (
    "people",
    "ceiling",
    "staff_visit_target",
    "staff_visits_planned",
    "staff_visits_credited",
    "partner_visit_target",
    "partner_visits_planned",
    "partner_visits_credited",
    "partner_visits_awaiting",
    "staff_training_target",
    "staff_trainings_planned",
    "staff_trainings_credited",
    "partner_training_target",
    "partner_trainings_planned",
    "partner_trainings_credited",
    "partner_required",
    "partner_assigned",
    "partner_credited",
    "partner_core_schools",
    "partner_beyond_staff",
    "portfolio_visits",
    "schools_to_recruit",
    "short_people",
    "schools_staff_scheduled",
    "schools_staff_and_partner",
    "client_staff_and_partner",
    "core_visits_over",
    "project_total",
    "project_assigned",
    "project_ceiling",
    "project_added",
    "project_credited",
    "duplicates",
    "over_ceiling_people",
    "over_ceiling_visits",
    "core_missing_partner_half",
)


@dataclass
class Readiness:
    """One person's figures, or the sum of several people's."""

    people: int = 0
    ceiling: int = 0
    staff_visit_target: int = 0
    staff_visits_planned: int = 0
    staff_visits_credited: int = 0
    partner_visit_target: int = 0
    partner_visits_planned: int = 0
    partner_visits_credited: int = 0
    # Schools in a Partner's hands that the Partner has not dated yet.
    partner_visits_awaiting: int = 0
    staff_training_target: int = 0
    staff_trainings_planned: int = 0
    staff_trainings_credited: int = 0
    partner_training_target: int = 0
    partner_trainings_planned: int = 0
    partner_trainings_credited: int = 0
    partner_required: int = 0
    partner_assigned: int = 0
    partner_credited: int = 0
    partner_core_schools: int = 0
    partner_beyond_staff: int = 0
    # Staff visits the schools held can take (two a Core school, one each of
    # the others), the schools still to recruit for them to take the role's
    # target, and how many people that is (owner, 2026-10-07).
    portfolio_visits: int = 0
    schools_to_recruit: int = 0
    short_people: int = 0
    # Schools held that staff scheduled a visit at themselves, and those of
    # them also in a Partner's hands.
    schools_staff_scheduled: int = 0
    schools_staff_and_partner: int = 0
    # The two visit flags (owner, 2026-10-07). A Client, Core Trained or
    # Core Graduate school takes one visit, so one scheduled by staff that is
    # also with a Partner is booked twice. A Core school takes two visits by
    # staff and two by a Partner, so it is flagged only with more than that.
    client_staff_and_partner: int = 0
    core_visits_over: int = 0
    # Every school held, and those of them enrolled in an open project: the
    # inventory's figures (Schools by type).
    project_total: int = 0
    project_assigned: int = 0
    # The person's project ceilings put together, the schools they added to
    # projects, and those no further than the ceilings.
    project_ceiling: int = 0
    project_added: int = 0
    project_credited: int = 0
    # What Impact Assessment looks into.
    duplicates: int = 0
    over_ceiling_people: int = 0
    over_ceiling_visits: int = 0
    core_missing_partner_half: int = 0
    inventory: dict = field(default_factory=dict)

    # ── The four parts ──
    @property
    def staff_visits(self) -> Line:
        return Line(
            self.staff_visit_target,
            self.staff_visits_planned,
            self.staff_visits_credited,
        )

    @property
    def partner_visits(self) -> Line:
        return Line(
            self.partner_visit_target,
            self.partner_visits_planned,
            self.partner_visits_credited,
        )

    @property
    def staff_trainings(self) -> Line:
        return Line(
            self.staff_training_target,
            self.staff_trainings_planned,
            self.staff_trainings_credited,
        )

    @property
    def partner_trainings(self) -> Line:
        return Line(
            self.partner_training_target,
            self.partner_trainings_planned,
            self.partner_trainings_credited,
        )

    @property
    def partner_assignment(self) -> Line:
        return Line(self.partner_required, self.partner_assigned, self.partner_credited)

    @property
    def project_assignment(self) -> Line:
        return Line(self.project_ceiling, self.project_added, self.project_credited)

    @property
    def net_visits_remaining(self) -> int:
        """Visits nobody has planned yet, staff and Partner together."""
        return self.staff_visits.remaining + self.partner_visits.remaining

    @property
    def pillars(self) -> list[dict]:
        lines = {
            VISITS: self.staff_visits,
            TRAININGS: self.staff_trainings,
            PARTNER: self.partner_assignment,
            PROJECT: self.project_assignment,
        }
        return [
            {"key": key, "label": PILLAR_LABELS[key], "line": line}
            for key, line in lines.items()
        ]

    @property
    def applicable(self) -> bool:
        """Whether there is anything to be ready with: somebody holding no
        school has no score, not a full one. Their visit target stands all
        the same, and the row says how many schools they need to recruit."""
        return bool(
            self.staff_training_target
            or self.partner_required
            or self.project_total
            or self.project_ceiling
        )

    @property
    def score(self) -> int:
        """The plain average of the four parts, rounded down: 100 only when
        every part is."""
        parts = [pillar["line"].percent for pillar in self.pillars]
        return sum(parts) // len(parts)

    @property
    def score_tone(self) -> str:
        if self.score >= 100:
            return "success"
        return "info" if self.score >= 50 else "warning"

    # ── The schools ──
    @property
    def types(self) -> list[TypeInventory]:
        return [self.inventory[key] for key in _type_order(self.inventory)]

    @property
    def schools_total(self) -> int:
        return sum(row.total for row in self.inventory.values())

    @property
    def schools_fully(self) -> int:
        return sum(row.fully for row in self.inventory.values())

    @property
    def schools_partly(self) -> int:
        return sum(row.partly for row in self.inventory.values())

    @property
    def schools_not_yet(self) -> int:
        return sum(row.not_yet for row in self.inventory.values())

    @property
    def flags(self) -> int:
        return (
            self.duplicates + self.over_ceiling_people + self.core_missing_partner_half
        )

    def __add__(self, other: Readiness) -> Readiness:
        total = Readiness(
            **{name: getattr(self, name) + getattr(other, name) for name in _SUMMED}
        )
        for source in (self, other):
            for key, row in source.inventory.items():
                mine = total.inventory.setdefault(
                    key, TypeInventory(key=key, label=row.label)
                )
                for name in ("total", "fully", "partly", "not_yet", "in_project"):
                    setattr(mine, name, getattr(mine, name) + getattr(row, name))
        return total

    def as_dict(self) -> dict:
        """The figures as plain data, for the JSON the pages also serve."""

        def line(value: Line) -> dict:
            return {
                "target": value.target,
                "planned": value.planned,
                "remaining": value.remaining,
                "over": value.over,
                "percent": value.percent,
            }

        return {
            "rules_version": rules.RULES_VERSION,
            "ceiling": self.ceiling,
            "visits": {
                "staff": line(self.staff_visits),
                "schools_held_can_take": self.portfolio_visits,
                "schools_to_recruit": self.schools_to_recruit,
                "schools_scheduled_by_staff": self.schools_staff_scheduled,
                "schools_scheduled_by_staff_and_with_partner": (
                    self.schools_staff_and_partner
                ),
                "client_schools_scheduled_by_staff_and_with_partner": (
                    self.client_staff_and_partner
                ),
                "core_schools_past_two_staff_or_two_partner_visits": (
                    self.core_visits_over
                ),
                "partner": {
                    **line(self.partner_visits),
                    "awaiting_partner_date": self.partner_visits_awaiting,
                },
                "net_remaining": self.net_visits_remaining,
            },
            "trainings": {
                "schools": line(self.staff_trainings),
                "partner_core_package": line(self.partner_trainings),
            },
            "partner_assignment": {
                **line(self.partner_assignment),
                "core_schools": self.partner_core_schools,
                "beyond_staff_capacity": self.partner_beyond_staff,
            },
            "project_assignment": {
                **line(self.project_assignment),
                "schools_held": self.project_total,
                "schools_held_in_a_project": self.project_assigned,
            },
            "completion": {
                "visits": self.staff_visits.percent,
                "trainings": self.staff_trainings.percent,
                "partner_assignment": self.partner_assignment.percent,
                "project_assignment": self.project_assignment.percent,
                "overall": self.score if self.applicable else None,
            },
            "schools": {
                "total": self.schools_total,
                "fully_planned": self.schools_fully,
                "partly_planned": self.schools_partly,
                "not_yet_planned": self.schools_not_yet,
                "by_type": [
                    {
                        "type": row.key,
                        "label": row.label,
                        "total": row.total,
                        "fully_planned": row.fully,
                        "partly_planned": row.partly,
                        "not_yet_planned": row.not_yet,
                        "in_project": row.in_project,
                    }
                    for row in self.types
                ],
            },
            "flags": {
                "duplicate_bookings": self.duplicates,
                "staff_past_ceiling": self.over_ceiling_people,
                "visits_past_ceiling": self.over_ceiling_visits,
                "core_missing_partner_half": self.core_missing_partner_half,
            },
        }


def _type_order(inventory: dict) -> list[str]:
    known = [key for key in rules.TYPE_ORDER if key in inventory]
    return known + sorted(key for key in inventory if key not in rules.TYPE_ORDER)


# ── One school ───────────────────────────────────────────────────────────────
_CORE = rules.REQUIREMENTS["core"]


def school_state(school) -> str:
    """FULLY, PARTLY or NOT_YET for one of the monitor's schools.

    A Core school is fully planned with its two staff and two Partner visits
    and its two staff and two Partner trainings; a Client, Core Trained or
    Core Graduate school with its visit (staff's, or in a Partner's hands)
    and its training. A school that takes neither has nothing left to plan.
    """
    need = rules.requirement_for(school.school_type)
    if not need.visits and not need.trainings:
        return FULLY
    if school.is_core:
        held = (
            min(school.staff_visits, _CORE.staff_visits),
            min(school.core_partner_visits, _CORE.partner_visits),
            min(school.core_staff_trainings, _CORE.staff_trainings),
            min(school.core_partner_trainings, _CORE.partner_trainings),
        )
        if sum(held) >= _CORE.visits + _CORE.trainings:
            return FULLY
        started = sum(held) or school.has_partner or school.has_training
        return PARTLY if started else NOT_YET
    visit = bool(school.staff_visits or school.has_partner)
    if visit and school.has_training:
        return FULLY
    return PARTLY if visit or school.has_training else NOT_YET


def is_duplicate(school) -> bool:
    """A Client, Core Trained or Core Graduate school booked more than once:
    two staff support visits, two staff SSA Support visits, two Partner
    visits, or staff and a Partner both. One support visit and one SSA
    Support visit by staff are two kinds of work, not one booked twice
    (Country Planning Oversight reads them the same way)."""
    if school.is_core:
        return False
    ssa = getattr(school, "staff_ssa_visits", 0)
    return (
        school.staff_visits - ssa > 1
        or ssa > 1
        or school.partner_visits > 1
        or bool(school.staff_visits and school.has_partner)
    )


def core_missing_partner_half(school) -> bool:
    return school.is_core and (
        school.core_partner_visits < _CORE.partner_visits
        or school.core_partner_trainings < _CORE.partner_trainings
    )


# ── One person ───────────────────────────────────────────────────────────────
def person_readiness(officer) -> Readiness:
    """The figures for one of the monitor's people (an OfficerMonitor)."""
    core = [s for s in officer.schools if s.is_core]
    client = [s for s in officer.schools if not s.is_core]
    cap = int(officer.visits_target or 0)
    share = rules.workload(cap, len(core), len(client))
    # The role's 280 or 560, whatever is held; the Client schools beyond it
    # are the Partner's (owner, 2026-10-07).
    staff_visit_target = cap
    partner_client = share.partner_client_visits
    partner_visit_target = share.partner_core_visits + partner_client
    partner_visits = sum(
        min(s.partner_visits, _CORE.partner_visits) for s in core
    ) + sum(min(s.partner_visits, 1) for s in client)

    # Schools attached to an in-school or a group training, of those that
    # take one; the Partner's line is its half of the Core packages.
    staff_training_target = sum(1 for s in officer.schools if s.needs_training)
    staff_trainings = sum(
        1 for s in officer.schools if s.needs_training and s.has_training
    )
    partner_training_target = share.partner_core_trainings
    partner_trainings = sum(s.core_partner_trainings for s in core)

    core_assigned = sum(
        1
        for s in core
        if s.core_partner_visits or s.core_partner_trainings or s.has_partner
    )
    client_assigned = sum(1 for s in client if s.has_partner)
    held = [*officer.schools, *officer.outreach_schools]
    project_ceiling = int(getattr(officer, "project_ceiling", 0) or 0)
    project_added = int(getattr(officer, "project_added", 0) or 0)

    inventory: dict[str, TypeInventory] = {}
    for school in held:
        key = school.school_type or ""
        row = inventory.setdefault(
            key, TypeInventory(key=key, label=rules.type_label(key))
        )
        row.total += 1
        setattr(row, school_state(school), getattr(row, school_state(school)) + 1)
        row.in_project += 1 if school.in_project else 0

    return Readiness(
        people=1,
        ceiling=cap,
        staff_visit_target=staff_visit_target,
        staff_visits_planned=officer.staff_visits,
        staff_visits_credited=min(officer.staff_visits, staff_visit_target),
        partner_visit_target=partner_visit_target,
        partner_visits_planned=partner_visits,
        partner_visits_credited=min(partner_visits, partner_visit_target),
        partner_visits_awaiting=sum(
            1 for s in officer.schools if s.partner_pending and not s.partner_visits
        ),
        staff_training_target=staff_training_target,
        staff_trainings_planned=staff_trainings,
        staff_trainings_credited=min(staff_trainings, staff_training_target),
        partner_training_target=partner_training_target,
        partner_trainings_planned=partner_trainings,
        partner_trainings_credited=min(partner_trainings, partner_training_target),
        partner_required=len(core) + partner_client,
        partner_assigned=core_assigned + client_assigned,
        partner_credited=core_assigned + min(client_assigned, partner_client),
        partner_core_schools=len(core),
        partner_beyond_staff=partner_client,
        portfolio_visits=share.portfolio_visits,
        schools_to_recruit=share.short_of_target,
        short_people=1 if share.short_of_target else 0,
        schools_staff_scheduled=officer.schools_staff_scheduled,
        schools_staff_and_partner=officer.schools_staff_and_partner,
        client_staff_and_partner=officer.client_staff_and_partner,
        core_visits_over=officer.core_visits_over,
        project_total=len(held),
        project_assigned=sum(1 for s in held if s.in_project),
        project_ceiling=project_ceiling,
        project_added=project_added,
        project_credited=min(project_added, project_ceiling),
        duplicates=sum(1 for s in client if is_duplicate(s)),
        over_ceiling_people=1 if officer.over_ceiling else 0,
        over_ceiling_visits=officer.over_ceiling,
        core_missing_partner_half=sum(1 for s in core if core_missing_partner_half(s)),
        inventory=inventory,
    )


def total(parts) -> Readiness:
    result = Readiness()
    for part in parts:
        result = result + part
    return result


# ── The checks made before a page is given its figures ───────────────────────
class ReadinessMismatch(AssertionError):
    """A figure that cannot be true. Raised in development; logged at error
    level everywhere else, where the page still renders."""


def problems(figures: Readiness, *, expected_schools: int | None = None) -> list[str]:
    """Why these figures cannot all be true; nothing when they can.

    * every school of a type is fully planned, partly planned or not yet
      planned, and the three add up to the type's schools;
    * the schools counted are the schools the reader's scope holds
      (``expected_schools``, counted apart from the rows): none is dropped
      for having no holder, no project, no Partner or no plan;
    * what is planned by Partners and in Partners' hands is inside the
      Partner's target, never beside a target of nothing.
    """
    found = []
    for row in figures.inventory.values():
        if not row.balanced:
            found.append(
                f"{row.label}: {row.fully} fully + {row.partly} partly + "
                f"{row.not_yet} not yet planned is not its {row.total} schools"
            )
    if figures.schools_total != figures.project_total:
        found.append(
            f"{figures.schools_total} schools by type, {figures.project_total} "
            "schools read for projects"
        )
    if expected_schools is not None and figures.schools_total != expected_schools:
        found.append(
            f"{expected_schools} operating schools in scope, "
            f"{figures.schools_total} on the rows"
        )
    if figures.client_staff_and_partner > figures.schools_staff_and_partner:
        found.append(
            f"{figures.client_staff_and_partner} Client schools scheduled by "
            f"staff and also with a Partner, of {figures.schools_staff_and_partner} "
            "schools of every type"
        )
    if figures.partner_visits_credited and not figures.partner_visit_target:
        found.append("Partner visits planned against a Partner target of nothing")
    if figures.partner_credited > figures.partner_required:
        found.append(
            f"{figures.partner_credited} schools counted with a Partner, "
            f"{figures.partner_required} required"
        )
    return found


def verify(figures: Readiness, *, where: str, expected_schools: int | None = None):
    found = problems(figures, expected_schools=expected_schools)
    if not found:
        return figures
    message = f"Planning readiness ({where}): " + "; ".join(found)
    from django.conf import settings

    if settings.DEBUG:
        raise ReadinessMismatch(message)
    logger.error(message)
    return figures


# ── Every planned activity, and where it is counted ──────────────────────────
#: Where a planned activity goes, in the order the page lists them. The last
#: two are the ones nobody's row holds: they are what to look into.
LEDGER = (
    ("staff_visit", "Staff visits on a person's row", False),
    ("partner_visit", "Partner visits at a school on the rows", False),
    (
        "partner_no_visit_school",
        "Partner visits at a school that takes none, such as a Champion (not counted)",
        False,
    ),
    ("cluster", "Group trainings and cluster meetings (schools with training)", False),
    ("training", "In-school trainings (schools with training)", False),
    ("companion", "The visit an in-school training writes beside itself", False),
    ("data_collection", "SSA Support assigned to a Partner (not counted)", False),
    ("outreach", "Donor, story, social and invitation visits (not counted)", False),
    ("outside_ssa", "Work under a project no SSA intervention measures", False),
    ("other", "Other work with no visit or training to count", False),
    ("off_roster", "Counted staff visits planned by somebody on no row", True),
    ("off_schools", "Partner visits at a school on no row", True),
)


def _outside_ssa(project_id) -> bool:
    if not project_id:
        return False
    from apps.projects.models import is_outside_ssa

    return is_outside_ssa(project_id)


def _ledger_key(row, people: set, schools: set, counted: set | None = None) -> str:
    """Where one planned activity goes. ``schools`` are the schools on the
    rows; ``counted`` those of them that take a visit (every one, when it is
    not given): a Partner's visit at a Champion school is on nobody's
    figures, and was filed with the Partner visits that are."""
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES

    activity_type, purpose = row["activity_type"], row["purpose_type"]
    if row["cluster_id"]:
        return "cluster"
    if purpose == rules.COMPANION_PURPOSE:
        return "companion"
    delivery = row["delivery_type"] or "staff"
    shaped = row["school_id"] and str(activity_type or "") in rules.VISIT_SHAPE_TYPES
    kind = rules.visit_kind(
        activity_type, purpose, row["project_id"], delivery_type=delivery
    )
    if shaped and kind and delivery == "partner":
        if row["school_id"] in (schools if counted is None else counted):
            return "partner_visit"
        return (
            "partner_no_visit_school" if row["school_id"] in schools else "off_schools"
        )
    if shaped and kind:
        on_row = str(row["responsible_staff_id"] or "") in people
        return "staff_visit" if on_row else "off_roster"
    if rules.is_data_collection(activity_type, purpose):
        return "data_collection"
    if rules.is_uncounted_visit(activity_type, purpose, delivery_type=delivery):
        return "outreach"
    if shaped and _outside_ssa(row["project_id"]):
        return "outside_ssa"
    if str(activity_type or "") in {str(t) for t in SCHOOL_TRAINING_TYPES}:
        return "training"
    return "other"


def ledger(monitor: dict, fy: str, *, whole_country: bool) -> dict:
    """Every planned activity of the year in the reader's scope, each in one
    line: where it is counted, or why it is not.

    The answer to "is everything that was planned on the page?": the lines
    add up to the planned activities, and the two flagged lines are planned
    work no row holds — a counted visit by somebody who is neither a Lead nor
    a CCEO on the rows, or a Partner visit at a school outside them. The
    country reads every activity; a team, those of its people and schools.
    One query.
    """
    from django.db.models import Q

    from apps.activities.models import Activity

    officers = monitor["totals"].officers
    people = {str(i) for officer in officers for i in officer.ids}
    schools = {
        s.id
        for officer in officers
        for s in (*officer.schools, *officer.outreach_schools)
    }
    counted = {s.id for officer in officers for s in officer.schools}
    planned = Activity.objects.filter(fy=str(fy), deleted_at__isnull=True).filter(
        rules.planned_q()
    )
    if not whole_country:
        planned = planned.filter(
            Q(responsible_staff_id__in=list(people)) | Q(school_id__in=list(schools))
        )
    counts = dict.fromkeys((key for key, _, _ in LEDGER), 0)
    for row in planned.values(
        "activity_type",
        "purpose_type",
        "delivery_type",
        "school_id",
        "cluster_id",
        "responsible_staff_id",
        "project_id",
    ):
        counts[_ledger_key(row, people, schools, counted)] += 1
    lines = [
        {"key": key, "label": label, "count": counts[key], "flagged": flagged}
        for key, label, flagged in LEDGER
        if counts[key] or flagged
    ]
    return {
        "total": sum(counts.values()),
        "lines": lines,
        "unaccounted": sum(counts[key] for key, _, flagged in LEDGER if flagged),
        "staff_visits": counts["staff_visit"],
    }


# ── For the pages ────────────────────────────────────────────────────────────
def for_monitor(monitor: dict, *, expected_schools: int | None = None) -> Readiness:
    """Put ``readiness`` on every person, team and total of a Planning
    Monitor, and return the country's (or the team's) total.

    ``monitor["totals"]`` covers everybody the reader follows even when the
    page is narrowed to one Lead, and so does the total checked here.
    """
    everyone = monitor["totals"]
    for officer in everyone.officers:
        officer.readiness = person_readiness(officer)
    for lead in monitor["leads"]:
        lead.readiness = total(officer.readiness for officer in lead.officers)
    everyone.readiness = total(officer.readiness for officer in everyone.officers)
    return verify(
        everyone.readiness, where="monitor", expected_schools=expected_schools
    )


def own(principal, fy: str) -> Readiness | None:
    """A Programme Lead's or CCEO's own figures; None for any other role."""
    from apps.planning.planning_monitor import own_monitor

    officer = own_monitor(principal, str(fy))
    if officer is None:
        return None
    return verify(person_readiness(officer), where="own plan")


__all__ = [
    "Line",
    "Readiness",
    "ReadinessMismatch",
    "TypeInventory",
    "for_monitor",
    "ledger",
    "own",
    "person_readiness",
    "problems",
    "school_state",
    "total",
    "verify",
]
