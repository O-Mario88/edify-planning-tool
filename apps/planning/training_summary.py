"""Staff and the summary of all their planned trainings.

Owner, 2026-10-06, with a reference table, and then: "there are so many
trainings on the list. I want all trainings hidden from the summary table and
only appear once it has been planned either through group training, in-school
training or cluster meeting. Each training will fetch the schools inivited to
attend or planned in-schools. The admin IA will set the Country Ceiling and
Leads will set each staff ceiling. The country ceiling will have COuntry
Ceiling column, Planned column, Remaining column then the rest of the staff
columns with their #schools".

    Training Name | Mode of delivery | Country Ceiling | Planned | Remaining
        | # Schools (Staff) …

Owner, 2026-10-09, on the same table: "add 'awaiting partner' numbers to the
staff {name} directly just like you added in-school and group scheduled and
keep the column for awaiting partner schedule, get rid of group scheduled, and
replace country ceiling with total covered out of the set ceiling for the
country (23/1000) ... mode of delivery should be group training, in-school
training, Partner in-school training". So the country's columns are now

    Total Covered / Country Ceiling | Staff Planned | Awaiting Partner
        | Remaining

(Partner Assigned had a column of its own for an hour; the owner, the same
day: "partner assigned and awaiting partner schedule are duplicate remove one
column and leave one".)

and a staff column is that person's in-school schools, the schools on their
group trainings and the schools they have with a Partner, each school once.

A training is a row only once a school has been planned for it in the year:
invited to a group training, invited to a cluster meeting that is a training,
or given an in-school training. Until then it is not on the table, whatever
ceilings have been set for it.

The three country columns are the country's own, the same for every reader:

* **Total Covered / Country Ceiling** — every school the country has
  committed to the training, each once, out of the ceiling Admin or Impact
  Assessment set (``training_ceilings.set_country_ceiling``; "Not set" until
  it is): "23 / 1,000". A school is covered once it is planned by staff for
  an in-school training, assigned to a Partner for one — whether or not the
  Partner has dated it (owner, 2026-10-08: "the training summary should not
  wait for partner scheduling") — or on a group training. Staff Planned
  and Awaiting Partner have their own columns beside it, so a school that
  is *assigned* is never read as *scheduled*; the schools on group trainings
  and those a Partner has dated are in the total and in the staff columns,
  with no column of their own.
* **Remaining** — the ceiling less what is covered, never below zero; what
  is covered past the ceiling shows on Total Covered.

Then one column per staff member: the schools that person has planned, beside
the ceiling their Programme Lead set for them.

Who reads it:

* a **CCEO** — their own column and nobody else's;
* a **Programme Lead** — a column for each officer they supervise, and the
  only role that sets an officer's ceiling;
* the **Country Director, Impact Assessment and Admin** — every officer in
  the country. Admin and Impact Assessment set the Country Ceiling; the
  Country Director sets nothing.

Two kinds of row, and they are never mixed:

* a **training** from the Training Catalogue, planned outside a project
  (``apps.planning.training_ceilings``).
* a **project training**, fetched from Special Projects: a training a live
  project delivers, once a school has been added to the project. A cell is
  the schools that officer has added, beside the capacity its coordinator
  set for them (``apps.projects``); Planned is every school on the project.
  A project's schools are the Project Coordinator's to control, so it has no
  Country Ceiling here and is not counted under a training ceiling.

A training is one or the other, never both (owner, 2026-10-08: "it is
repeating the trainings that are already created as project. Can you read
only project ... so that there are no repeated trainings"). EdTech
Foundations is a Training Catalogue entry and a training the EdTech project
delivers; a session of it scheduled from the catalogue, with no project
named, used to add a second row for the same training above the project's.
A training a live project delivers is read from the project and is not a
training row at all (``training_ceilings.project_training_ids``).

Every figure is schools, each counted once: a school on two sessions of one
training is one school in its officer's cell and one in Planned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q

from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.planning import training_ceilings
from apps.planning.training_ceilings import DELIVERY_LABELS, GROUP, IN_SCHOOL

__all__ = [
    "COUNTRY_READER_ROLES",
    "Cell",
    "Row",
    "Summary",
    "SUMMARY_ROLES",
    "build",
    "country_officers",
    "coverage_profiles",
    "for_reader",
    "may_read_country",
    "own",
    "reader_staff",
]

#: Roles that read every officer in the country. None of them sets an
#: officer's ceiling; Admin and Impact Assessment set the Country Ceiling
#: (``training_ceilings.COUNTRY_CEILING_ROLES``).
COUNTRY_READER_ROLES = frozenset(
    {
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
        EdifyRole.ADMIN.value,
    }
)
#: Roles that hold the summary on Planning Oversight.
SUMMARY_ROLES = COUNTRY_READER_ROLES | {EdifyRole.COUNTRY_PROGRAM_LEAD.value}

#: The summary's Mode of delivery, in the owner's words for this table
#: (2026-10-09): "group training, in-school training, Partner in-school
#: training". The third says who delivers the in-school one.
PARTNER_IN_SCHOOL = "Partner In-School Training"
MODE_LABELS = dict(DELIVERY_LABELS)
#: How a catalogue entry says it is delivered, in the summary's two modes.
_CATALOGUE_MODES = {
    "in_school_training": MODE_LABELS[IN_SCHOOL],
    "school_visit": MODE_LABELS[IN_SCHOOL],
    "cluster_training": MODE_LABELS[GROUP],
    "cluster_meeting": MODE_LABELS[GROUP],
    "group": MODE_LABELS[GROUP],
    "online": "Online",
}


@dataclass(frozen=True)
class Cell:
    """One staff member's schools for one row."""

    staff_id: str
    #: Schools scheduled (a training) or added to the project (a project row).
    schools: int
    #: The training ceiling, or the project capacity; None when none is set.
    limit: int | None
    group: int = 0
    in_school: int = 0
    #: Schools assigned to a Partner for it, and those the Partner has dated.
    partner: int = 0
    partner_scheduled: int = 0
    ceiling_id: str = ""
    #: What the limit is called: a training ceiling, or a project capacity.
    noun: str = "ceiling"

    @property
    def awaiting_partner(self) -> int:
        return max(self.partner - self.partner_scheduled, 0)

    @property
    def breakdown(self) -> str:
        """What the number adds up: in-school, group and with a Partner."""
        dated = (
            f", {self.partner_scheduled} scheduled by the partner"
            if self.partner_scheduled
            else ""
        )
        return (
            f"{self.in_school} staff in-school, {self.group} group scheduled, "
            f"{self.awaiting_partner} awaiting the partner's schedule{dated}"
        )

    @property
    def state(self) -> str:
        if self.limit is None:
            return "unset"
        if self.schools > self.limit:
            return "above"
        if self.schools == self.limit:
            return "reached"
        return "below"

    @property
    def tone(self) -> str:
        return {
            "unset": "",
            "above": "danger",
            "below": "warning",
            "reached": "success",
        }[self.state]

    @property
    def flag(self) -> str:
        if self.state == "above":
            return f"{self.schools - self.limit} above {self.noun}"
        if self.state == "below":
            return f"{self.limit - self.schools} below {self.noun}"
        if self.state == "reached":
            return f"At {self.noun}"
        return f"No {self.noun} set"

    @property
    def blank(self) -> bool:
        return self.limit is None and not self.schools


@dataclass
class Row:
    kind: str  # "training" | "project"
    key: str
    name: str
    mode: str
    training_id: str = ""
    project_id: str = ""
    project_name: str = ""
    #: The country's ceiling for the training; None when none is set, and
    #: always None for a project training.
    country_ceiling: int | None = None
    country_ceiling_id: str = ""
    #: Every school the country has covered for it (a training) — planned by
    #: staff, assigned to a Partner or on a group training, each once — or
    #: every school on the project (a project training).
    planned: int = 0
    #: The country's schools by route (a training only): planned by staff,
    #: assigned to a Partner, of those dated by the Partner, on a group
    #: training.
    staff_planned: int = 0
    partner: int = 0
    partner_scheduled: int = 0
    group: int = 0
    cells: list[Cell] = field(default_factory=list)

    @property
    def awaiting_partner(self) -> int:
        """Schools assigned to a Partner that the Partner has not dated."""
        return max(self.partner - self.partner_scheduled, 0)

    @property
    def partner_hint(self) -> str:
        """Assigned is the whole commitment; how much of it is on a day."""
        return (
            f"{self.partner_scheduled} scheduled by the partner · "
            f"{self.awaiting_partner} awaiting the partner's date"
        )

    @property
    def total(self) -> int:
        return sum(cell.schools for cell in self.cells)

    @property
    def has_anything(self) -> bool:
        return any(not cell.blank for cell in self.cells)

    @property
    def remaining(self) -> int | None:
        """The ceiling less what is planned, never below zero."""
        if self.country_ceiling is None:
            return None
        return max(self.country_ceiling - self.planned, 0)

    @property
    def over(self) -> int:
        """Schools planned past the Country Ceiling."""
        if self.country_ceiling is None:
            return 0
        return max(self.planned - self.country_ceiling, 0)

    @property
    def country_state(self) -> str:
        if self.country_ceiling is None:
            return "unset"
        if self.planned > self.country_ceiling:
            return "above"
        if self.planned == self.country_ceiling:
            return "reached"
        return "below"

    @property
    def country_tone(self) -> str:
        return {"unset": "", "above": "danger", "below": "", "reached": "success"}[
            self.country_state
        ]

    @property
    def country_flag(self) -> str:
        if self.country_state == "above":
            return f"{self.over} above the Country Ceiling"
        if self.country_state == "reached":
            return "At the Country Ceiling"
        if self.country_state == "below":
            return f"{self.remaining} remaining under the Country Ceiling"
        return "No Country Ceiling set"


@dataclass
class Summary:
    fy: str
    staff: list  # StaffProfile, one per column
    rows: list[Row]
    #: A Programme Lead: sets the ceilings of the officers in the columns.
    may_set: bool = False
    #: Admin and Impact Assessment: set the Country Ceiling.
    may_set_country: bool = False
    leads: list = field(default_factory=list)  # (staff id, name)
    lead: str = ""
    #: The columns that are a Programme Lead's own (owner, 2026-10-06: the
    #: Leads are on the list beside their officers).
    lead_ids: frozenset = frozenset()
    #: The reader follows the whole country, so each country figure opens the
    #: schools it counts. A Programme Lead reads the country's figures and
    #: opens their own team's.
    country_links: bool = False

    @property
    def columns(self) -> list[dict]:
        return [
            {
                "id": profile.id,
                "name": profile.user.name or profile.user.email,
                "is_lead": profile.id in self.lead_ids,
            }
            for profile in self.staff
        ]

    @property
    def flags(self) -> dict:
        counts = {"above": 0, "below": 0, "reached": 0}
        for row in self.rows:
            for cell in row.cells:
                if cell.state in counts:
                    counts[cell.state] += 1
        return counts

    @property
    def any_flag(self) -> bool:
        return any(self.flags.values())


# ── Who is in the table ─────────────────────────────────────────────────────
def may_read_country(principal) -> bool:
    return (getattr(principal, "active_role", "") or "") in COUNTRY_READER_ROLES


def _reader_country(principal) -> str:
    return training_ceilings.country_of(principal)


def country_officers(country: str) -> list:
    """Everybody who schedules trainings in the country: the people who hold
    the CCEO or the Programme Lead role and have not left. The Leads were
    missing (owner, 2026-10-06: "make sure they are included on the list"):
    they hold schools and schedule trainings, and a ceiling can be set for
    them."""
    from apps.accounts.models import StaffProfile
    from apps.core.role_holding import holds_role_q

    officers = StaffProfile.objects.filter(
        holds_role_q(EdifyRole.CCEO) | holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD),
        deleted_at__isnull=True,
        user__deleted_at__isnull=True,
        user__is_active=True,
    ).select_related("user")
    if country:
        officers = officers.filter(Q(country=country) | Q(country=""))
    return sorted(officers, key=lambda p: (p.user.name or p.user.email).casefold())


def _leads_of(officers) -> tuple[dict, list]:
    """{officer id: lead id} and the Programme Leads, by name: everybody who
    holds the role, whether or not an officer reports to them yet."""
    from apps.accounts.models import StaffSupervisorAssignment
    from apps.core.role_holding import holds_role_q

    links = StaffSupervisorAssignment.objects.filter(
        holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD, prefix="supervisor__user"),
        supervisee_id__in=[p.id for p in officers],
        supervisor__deleted_at__isnull=True,
    ).values_list("supervisee_id", "supervisor_id", "supervisor__user__name")
    lead_of: dict[str, str] = {}
    names: dict[str, str] = {}
    lead_role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    for profile in officers:
        user = profile.user
        if lead_role in (user.roles or []) or user.active_role == lead_role:
            names[profile.id] = user.name or user.email or "Programme Lead"
    for officer_id, lead_id, lead_name in links:
        if officer_id == lead_id or officer_id in names:
            # A Lead is filed under themselves, never under another Lead.
            continue
        lead_of.setdefault(officer_id, lead_id)
        names.setdefault(lead_id, lead_name or "Programme Lead")
    return lead_of, sorted(names.items(), key=lambda pair: pair[1].casefold())


def _teams_in_order(officers, lead_of: dict, lead_ids: list) -> list:
    """Each Programme Lead followed by the officers who report to them, then
    anybody with no Lead: the columns read as teams."""
    by_id = {profile.id: profile for profile in officers}
    ordered, placed = [], set()
    for lead_id in lead_ids:
        team = [lead_id] if lead_id in by_id else []
        team += [p.id for p in officers if lead_of.get(p.id) == lead_id]
        for staff_id in team:
            if staff_id not in placed:
                placed.add(staff_id)
                ordered.append(by_id[staff_id])
    ordered += [p for p in officers if p.id not in placed]
    return ordered


# ── Rows ────────────────────────────────────────────────────────────────────
def _training_rows(profiles, fy: str, *, country: str) -> list[Row]:
    """One row per training the country has planned a school for, in the
    year: nothing else is listed (owner, 2026-10-06)."""
    from apps.activity_catalogue.models import ActivityCatalogueItem

    planned = training_ceilings.country_scheduled(fy, country)
    if not planned:
        return []
    ceilings = training_ceilings.country_ceilings(fy, country)
    figures = {
        (row.staff_id, row.training_id): row
        for row in training_ceilings.summary_for_staff(profiles, fy)
    }
    items = ActivityCatalogueItem.objects.filter(id__in=list(planned)).order_by(
        "display_name", "stable_code"
    )
    rows = []
    for item in items:
        cells = []
        for profile in profiles:
            figure = figures.get((profile.id, item.id))
            cells.append(
                Cell(
                    staff_id=profile.id,
                    schools=figure.total if figure else 0,
                    limit=figure.ceiling if figure else None,
                    group=figure.group if figure else 0,
                    in_school=figure.in_school if figure else 0,
                    partner=figure.partner if figure else 0,
                    partner_scheduled=figure.partner_scheduled if figure else 0,
                    ceiling_id=figure.ceiling_id if figure else "",
                )
            )
        # How the country is delivering it: every way it is planned.
        country_row = planned[item.id]
        mode = " · ".join(
            label
            for label, schools in (
                (MODE_LABELS[GROUP], country_row["group"]),
                (MODE_LABELS[IN_SCHOOL], country_row["in_school"]),
                (PARTNER_IN_SCHOOL, country_row["partner"]),
            )
            if schools
        )
        ceiling = ceilings.get(item.id) or {}
        rows.append(
            Row(
                kind="training",
                key=f"training:{item.id}",
                name=item.display_name,
                mode=mode,
                training_id=item.id,
                country_ceiling=ceiling.get("ceiling"),
                country_ceiling_id=ceiling.get("id", ""),
                planned=country_row["total"],
                staff_planned=country_row["in_school"],
                partner=country_row["partner"],
                partner_scheduled=country_row["partner_scheduled"],
                group=country_row["group"],
                cells=cells,
            )
        )
    return rows


def _project_rows(profiles) -> list[Row]:
    """The trainings live Special Projects deliver, with each person's number
    read from the schools they added to the project (owner, 2026-10-06: "all
    training under project should be fetched from special project and their
    numbers added there based on how people have added the schools to
    projects"). A project training is a row once the project has a school."""
    from apps.projects.models import ProjectSchoolAssignment, ProjectStaffCapacity

    mappings = list(
        training_ceilings.project_training_mappings()
        .select_related("project", "catalogue_item")
        .order_by("project__name", "catalogue_item__display_name")
    )
    if not mappings:
        return []
    project_ids = {mapping.project_id for mapping in mappings}
    staff_ids = [profile.id for profile in profiles]
    by_user = {profile.user_id: profile.id for profile in profiles}

    added: dict[tuple[str, str], int] = {}
    for row in (
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .filter(
            Q(assigned_staff_id__in=staff_ids)
            | Q(assigned_staff__isnull=True, assigned_by__in=list(by_user))
        )
        .values("project_id", "assigned_staff_id", "assigned_by")
        .annotate(n=Count("id"))
    ):
        # The staff member who added the school; for an older row that names
        # nobody's allocation, the person recorded as having added it.
        staff_id = row["assigned_staff_id"] or by_user.get(row["assigned_by"])
        if staff_id:
            key = (row["project_id"], staff_id)
            added[key] = added.get(key, 0) + row["n"]
    capacity = {
        (project_id, staff_id): maximum
        for project_id, staff_id, maximum in ProjectStaffCapacity.objects.filter(
            project_id__in=project_ids, staff_id__in=staff_ids
        ).values_list("project_id", "staff_id", "max_schools")
    }
    #: Every school on each project, whoever added it.
    on_project = dict(
        ProjectSchoolAssignment.objects.filter(project_id__in=project_ids)
        .values_list("project_id")
        .annotate(n=Count("id"))
    )

    rows = []
    for mapping in mappings:
        project, item = mapping.project, mapping.catalogue_item
        cells = [
            Cell(
                staff_id=profile.id,
                schools=added.get((project.id, profile.id), 0),
                limit=capacity.get((project.id, profile.id)),
                noun="capacity",
            )
            for profile in profiles
        ]
        row = Row(
            kind="project",
            key=f"project:{project.id}:{item.id}",
            name=f"{item.display_name} ({project.name})",
            mode=_CATALOGUE_MODES.get(
                item.delivery_method, item.get_delivery_method_display()
            ),
            training_id=item.id,
            project_id=project.id,
            project_name=project.name,
            planned=on_project.get(project.id, 0),
            cells=cells,
        )
        if row.planned:
            rows.append(row)
    return rows


def build(profiles, fy: str, *, country: str) -> list[Row]:
    """The rows for these staff columns: every training the country has
    planned a school for in the year, then every project training whose
    project has a school. A training nobody has planned is not listed."""
    profiles = list(profiles)
    return [
        *_training_rows(profiles, str(fy), country=country),
        *_project_rows(profiles),
    ]


# ── For a reader ────────────────────────────────────────────────────────────
def own(principal, fy: str) -> Summary:
    """A staff member's own table: their column and nobody else's."""
    profile = training_ceilings._own_profile(principal)
    if profile is None:
        return Summary(fy=str(fy), staff=[], rows=[])
    # Their own table lists what they have planned themselves.
    rows = [
        row
        for row in build([profile], str(fy), country=_reader_country(principal))
        if row.has_anything
    ]
    return Summary(fy=str(fy), staff=[profile], rows=rows)


def reader_staff(principal, *, lead: str = "") -> list:
    """The staff whose trainings this reader follows on Planning Oversight:
    a Programme Lead's own column and their officers', or — for the Country
    Director, Impact Assessment and Admin — every officer in the country,
    narrowed to one Programme Lead's team on request."""
    role = getattr(principal, "active_role", "") or ""
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return training_ceilings.ceiling_staff_options(principal)
    if role not in COUNTRY_READER_ROLES:
        raise Forbidden(
            "The training summary is read by a Programme Lead for their "
            "officers, and by the Country Director, Impact Assessment and Admin."
        )
    officers = country_officers(_reader_country(principal))
    lead_of, leads = _leads_of(officers)
    if lead and any(lead == lead_id for lead_id, _name in leads):
        officers = [p for p in officers if p.id == lead or lead_of.get(p.id) == lead]
    return _teams_in_order(officers, lead_of, [i for i, _name in leads])


def coverage_profiles(principal, summary: Summary) -> list:
    """The staff whose schools the coverage table lists for this reader: the
    people in the summary's columns — and, for a reader of the whole country
    with no one team chosen, everybody the country's figures count, so the
    list behind a country figure is as long as the figure. That includes
    staff who have left and whose plans are still the country's."""
    if not summary.country_links or summary.lead:
        return list(summary.staff)
    from apps.accounts.models import StaffProfile

    country = _reader_country(principal)
    staff = StaffProfile.objects.select_related("user")
    if country:
        staff = staff.filter(Q(country=country) | Q(country=""))
    return list(staff)


def for_reader(
    principal, fy: str, *, lead: str = "", with_rows: bool = True
) -> Summary:
    """The Planning Oversight table: a Programme Lead's officers, or — for the
    Country Director, Impact Assessment and Admin — every officer in the
    country, narrowed to one Programme Lead's team on request. Only a
    Programme Lead sets an officer's ceiling; Admin and Impact Assessment set
    the Country Ceiling. ``with_rows`` false gives the readers and columns
    alone, for a tab that draws another table of the same people."""
    role = getattr(principal, "active_role", "") or ""
    country = _reader_country(principal)
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        # The Lead's own column first, then their officers'.
        staff = training_ceilings.ceiling_staff_options(principal)
        own_id = getattr(principal, "staff_profile_id", None)
        return Summary(
            fy=str(fy),
            staff=staff,
            rows=build(staff, str(fy), country=country) if with_rows else [],
            may_set=bool(staff),
            lead_ids=frozenset({own_id} if own_id else ()),
        )
    if role not in COUNTRY_READER_ROLES:
        raise Forbidden(
            "The training summary is read by a Programme Lead for their "
            "officers, and by the Country Director, Impact Assessment and Admin."
        )
    officers = country_officers(country)
    lead_of, leads = _leads_of(officers)
    lead = lead if any(lead == lead_id for lead_id, _name in leads) else ""
    if lead:
        # A Lead's team is the Lead and the officers who report to them.
        officers = [p for p in officers if p.id == lead or lead_of.get(p.id) == lead]
    lead_ids = frozenset(lead_id for lead_id, _name in leads)
    officers = _teams_in_order(officers, lead_of, [i for i, _name in leads])
    return Summary(
        fy=str(fy),
        staff=officers,
        rows=build(officers, str(fy), country=country) if with_rows else [],
        may_set=False,
        may_set_country=training_ceilings.may_set_country_ceiling(principal),
        leads=leads,
        lead=lead,
        lead_ids=lead_ids,
        country_links=True,
    )
