"""The consolidated tables behind the Country Director's cards.

Owner, 2026-10-01: every card on Country Planning Oversight is a link to the
table of what it counts — the plans, the schools, the meetings — grouped by
Programme Lead, so a figure can be followed up with the person it belongs to.

Each table lists the same rows its card counts: the people-first tables read
``people.Reads`` (the queries the cards aggregate), the school tables read the
page's own dataset, and both apply the page's filters. A table that lists
schools carries the School ID.

Every table is one flat list, sorted by its groups and then by what a reader
scans for, so the page shows a slice of it under its group headings and the
workbook holds all of it with the groups as columns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from apps.planning.country_oversight import people, rules
from apps.planning.country_oversight import service as svc
from apps.planning.country_oversight.coverage import (
    _day,
    _Handover,
    duplicate_reasons,
    handover_kind,
)
from apps.planning.country_oversight.hierarchy import IDX

ROWS_PER_PAGE = 50
NOBODY = "No responsible person recorded"
PARTNER_PLANNED = "Planned by the Partner"


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    numeric: bool = False
    # A date column; the page and the workbook format it.
    is_date: bool = False
    # The school's name: linked to the school on the page.
    is_school: bool = False
    # A date that may honestly be absent (a delivery date before delivery):
    # the page shows a dash, not "Not yet scheduled".
    optional: bool = False


@dataclass(frozen=True)
class Spec:
    key: str
    title: str
    # What a row is, for the count line ("visit", "school", "meeting").
    unit: str
    description: str
    columns: tuple
    # Row keys whose values make a group heading, outermost first. Those that
    # are columns are columns in the workbook and headings on the page.
    groups: tuple = ("lead",)
    # How many of ``groups`` each heading spells out. (n,) is one heading
    # naming the whole path; (1, 2) is a Programme Lead heading and, under
    # it, one for each person — each with its own balance.
    headings: tuple = ()
    # Columns kept for the workbook and left off the page, where a heading
    # already says them.
    export_only: tuple = ()
    # The card this table is the detail of, if any.
    metric: str = ""
    short: str = ""


@dataclass
class Table:
    spec: Spec
    rows: list = field(default_factory=list)
    # A line under the title: what the rows add up to.
    summary: str = ""
    # Group path → the balance its heading states: planned of expected, and
    # what remains (owner, 2026-10-01: "planned AND remaining" at each level).
    notes: dict = field(default_factory=dict)

    @property
    def shown_columns(self) -> list:
        hidden = set(self.spec.groups) | set(self.spec.export_only)
        return [c for c in self.spec.columns if c.key not in hidden]

    @property
    def heading_levels(self) -> tuple:
        return self.spec.headings or (len(self.spec.groups),)

    @property
    def group_columns(self) -> list:
        by_key = {c.key: c for c in self.spec.columns}
        return [by_key[key] for key in self.spec.groups]

    def group_of(self, row: dict) -> tuple:
        return tuple(row.get(key) or "—" for key in self.spec.groups)

    def group_counts(self) -> dict:
        """Rows under each heading: every path a heading names."""
        counts: dict[tuple, int] = {}
        for row in self.rows:
            group = self.group_of(row)
            for level in self.heading_levels:
                counts[group[:level]] = counts.get(group[:level], 0) + 1
        return counts


C = Column
LEAD = C("lead", "Programme Lead")
#: Says so on every plan at a school that is planned twice: a duplicate is
#: shown in the list it belongs to, never dropped from it.
FLAG = C("flag", "Planned Twice")
SCHOOL_COLUMNS = (
    C("school_id", "School ID"),
    C("school", "School", is_school=True),
    C("type", "School Type"),
    C("district", "District"),
)

SPECS: dict[str, Spec] = {
    spec.key: spec
    for spec in (
        Spec(
            "visits",
            "Staff Visit Plans",
            "visit",
            "Every Follow up, In-school Training and SSA Support visit staff "
            "have planned, under the person who planned it. These are the "
            "visits counted against each CCEO's 560 and each Programme Lead's "
            "280.",
            (
                LEAD,
                C("staff", "Planned By"),
                C("role", "Role"),
                *SCHOOL_COLUMNS,
                C("activity", "Visit"),
                C("date", "Date", is_date=True),
                C("status", "Status"),
                FLAG,
            ),
            groups=("lead", "staff"),
            headings=(1, 2),
            export_only=("role",),
            metric="cpo_staff_visit_planning",
            short="Visits",
        ),
        Spec(
            "partners",
            "Schools Assigned to Partners",
            "assignment",
            "Every piece of work staff put in a Partner's hands, under the "
            "person who assigned it, with the date the Partner has set — or "
            "that it has not set one yet. Partner planning counts only what a "
            "Partner dated.",
            (
                LEAD,
                C("staff", "Assigned By"),
                C("partner", "Partner"),
                *SCHOOL_COLUMNS,
                C("activity", "Work"),
                C("assigned_on", "Assigned On", is_date=True),
                C("date", "Partner's Date", is_date=True),
                C("state", "Partner Planning"),
                C("status", "Status"),
                FLAG,
            ),
            groups=("lead", "staff"),
            headings=(1, 2),
            metric="cpo_partner_planning",
            short="Partners",
        ),
        Spec(
            "plans",
            "All Plans",
            "plan",
            "Every visit, training and cluster meeting planned for the year, by "
            "staff and by Partners. Donor, story, social and invitation visits "
            "are listed and marked as not counted toward a person's target.",
            (
                LEAD,
                C("staff", "Planned By"),
                C("channel", "By"),
                C("activity", "Activity"),
                C("counted", "Counts Toward Target"),
                *SCHOOL_COLUMNS,
                C("invited", "Schools Invited", numeric=True),
                C("date", "Date", is_date=True),
                C("status", "Status"),
                FLAG,
            ),
            metric="cpo_total_visit_coverage",
            short="All Plans",
        ),
        Spec(
            "trainings",
            "Training Plans",
            "training",
            "Every training planned for the year: at a school, for a cluster, "
            "by staff and by Partners. A cluster training reaches the schools "
            "on its planned roster.",
            (
                LEAD,
                C("staff", "Planned By"),
                C("channel", "By"),
                C("activity", "Training"),
                *SCHOOL_COLUMNS,
                C("invited", "Schools Invited", numeric=True),
                C("date", "Date", is_date=True),
                C("status", "Status"),
            ),
            metric="cpo_training_planning",
            short="Trainings",
        ),
        Spec(
            "clusters",
            "Clustered Schools",
            "school",
            "Every school in an active cluster, under the Programme Lead, "
            "sub-region, district and cluster it belongs to, with the CCEO "
            "responsible for the cluster.",
            (
                LEAD,
                C("sub_region", "Sub-region"),
                C("district", "District"),
                C("cluster", "Cluster"),
                C("school_id", "School ID"),
                C("school", "School", is_school=True),
                C("type", "School Type"),
                C("staff", "CCEO Responsible"),
            ),
            groups=("lead", "sub_region", "district", "cluster"),
            metric="cpo_cluster_membership",
            short="Clusters",
        ),
        Spec(
            "meetings",
            "Cluster Meeting Plans",
            "meeting",
            "Every cluster meeting staff have planned, under the Programme "
            "Lead, sub-region, district and cluster, with the staff member "
            "who planned it and the schools on its roster.",
            (
                LEAD,
                C("sub_region", "Sub-region"),
                C("district", "District"),
                C("cluster", "Cluster"),
                C("staff", "Staff"),
                C("date", "Date", is_date=True),
                C("status", "Status"),
                C("invited", "Schools Invited", numeric=True),
            ),
            groups=("lead", "sub_region", "district", "cluster"),
            metric="cpo_cluster_meeting_planning",
            short="Meetings",
        ),
        Spec(
            "unclustered",
            "Unclustered Schools",
            "school",
            "Schools that are in no active cluster, under the person who holds "
            "them. A school has to be in a cluster before a cluster meeting or "
            "a cluster training can reach it.",
            (
                LEAD,
                C("staff", "CCEO / Holder"),
                *SCHOOL_COLUMNS,
                C("visit", "Visit Planned"),
                C("training", "Training Planned"),
            ),
            short="Unclustered",
        ),
        Spec(
            "duplicates",
            "Schools Planned Twice",
            "plan",
            "Every plan at a school that is planned more often than it should "
            "be: a Client, Core Trained or Core Graduate school planned by "
            "staff and held by a Partner, or with the same kind of visit "
            "twice; a Core school with more than two staff or two Partner "
            "visits. One school, however many plans: each is counted once as "
            "coverage, and nothing is removed.",
            (
                LEAD,
                C("holder", "CCEO / Holder"),
                *SCHOOL_COLUMNS,
                C("why", "Why"),
                C("channel", "By"),
                C("staff", "Responsible"),
                C("activity", "Plan"),
                C("date", "Date", is_date=True),
                C("status", "Status"),
            ),
            groups=("lead", "school_label"),
            headings=(1, 2),
            # The school's heading states why; the workbook keeps the column.
            export_only=("why",),
            short="Planned Twice",
        ),
        Spec(
            "not-planned",
            "Schools Not Yet Planned",
            "school",
            "Schools that need a visit this year and have none planned, by "
            "staff or by a Partner, under the person who holds them.",
            (
                LEAD,
                C("staff", "CCEO / Holder"),
                *SCHOOL_COLUMNS,
                C("cluster", "Cluster"),
                C("with_partner", "With a Partner"),
                C("training", "Training Planned"),
            ),
            short="Not Yet Planned",
        ),
        Spec(
            "no-training",
            "Schools With No Training Planned",
            "school",
            "Schools that need a training this year and have none planned, "
            "under the person who holds them.",
            (
                LEAD,
                C("staff", "CCEO / Holder"),
                *SCHOOL_COLUMNS,
                C("cluster", "Cluster"),
                C("with_partner", "With a Partner"),
                C("visit", "Visit Planned"),
            ),
            short="No Training",
        ),
    )
}

#: The table each card opens.
METRIC_TABLES = {spec.metric: spec.key for spec in SPECS.values() if spec.metric}
#: The tables offered side by side on the table page, in the cards' order.
TAB_ORDER = (
    "visits",
    "partners",
    "plans",
    "trainings",
    "clusters",
    "meetings",
    "duplicates",
    "not-planned",
    "no-training",
    "unclustered",
)


def table_url(key: str, query: str = "") -> str:
    return f"{svc.PAGE_PATH}table/{key}" + (f"?{query}" if query else "")


# ── Shared lookups ───────────────────────────────────────────────────────────
class _Staff:
    """Who a raw staff id is, and which Lead's team they sit in."""

    def __init__(self, country: str = ""):
        self.people = people._People(country)

    def learn(self, raw_ids) -> None:
        self.people.note(raw_ids)
        self.people.resolve()

    def get(self, *raw_ids):
        return self.people.first(*raw_ids)

    def rank(self, team_name: str) -> int:
        names = [team.name for team in self.people.teams.values()]
        return names.index(team_name) if team_name in names else len(names)


def _labels(choices) -> dict:
    return {str(value): str(label) for value, label in choices}


def _status_labels() -> dict:
    from apps.core.enums import ActivityStatus

    return _labels(ActivityStatus.choices)


def _type_labels() -> dict:
    from apps.core.enums import ActivityType

    return _labels(ActivityType.choices)


def _reads(user, filters) -> people.Reads:
    """The page's own selection, as the people-first read takes it."""
    from apps.core.scoping import resolve_user_scope

    window = filters.window
    school_ids = None
    if filters.planning_status or filters.partner:
        dataset = svc.dataset_for(user, window)
        school_ids = tuple(svc.fold(dataset, filters, placement=True).placement)
    return people.Reads(
        None,
        filters.fy,
        window=svc._people_window(window),
        scope=resolve_user_scope(user),
        narrow=svc._narrow(filters, school_ids),
    )


def _keeps_person(filters, person) -> bool:
    """Does the page's Programme Lead / CCEO choice keep this person's rows?"""
    if filters.program_lead and (
        person is None or person.team_key != filters.program_lead
    ):
        return False
    if filters.cceo and (person is None or person.key != filters.cceo):
        return False
    return True


def _who(person) -> tuple[str, str, str]:
    """(Programme Lead, name, role) for a row."""
    if person is None:
        return rules.NO_LEAD_LABEL, NOBODY, ""
    lead = person.team_name
    if person.team_key == people.OTHER_TEAM_KEY:
        lead = rules.NO_LEAD_LABEL
    return lead, person.name, person.role_label or person.role_in_use


def _sorted(rows: list, staff: _Staff, *keys) -> list:
    """Rows by Programme Lead (the roster's order), then by ``keys``."""

    def sort_key(row):
        return (
            staff.rank(row["lead"]),
            row["lead"].casefold(),
            *(_sortable(row.get(key)) for key in keys),
        )

    return sorted(rows, key=sort_key)


def _sortable(value):
    if value is None:
        return (1, "")
    if isinstance(value, date):
        return (0, value.isoformat())
    return (0, str(value).casefold())


def _school_cells(code, name, school_type, district) -> dict:
    return {
        "school_id": code or "",
        "school": name or "",
        "type": rules.type_label(school_type) if school_type else "",
        "district": district or "",
    }


_SCHOOL_FIELDS = (
    "school__school_id",
    "school__name",
    "school__school_type",
    "school__district__name",
)


# ── People-first tables ──────────────────────────────────────────────────────
def _visit_rows(reads, staff, filters) -> list:
    if reads.schools is None or not reads.narrow.staff_side:
        return []
    found = list(
        reads.counted_visits()
        .annotate(on=_day())
        .values_list("responsible_staff_id", *_SCHOOL_FIELDS, "kind", "on", "status")
    )
    staff.learn(row[0] for row in found)
    statuses = _status_labels()
    rows = []
    for staff_id, code, name, school_type, district, kind, on, status in found:
        person = staff.get(staff_id)
        if not _keeps_person(filters, person):
            continue
        lead, who, role = _who(person)
        rows.append(
            {
                "lead": lead,
                "staff": who,
                "role": role,
                **_school_cells(code, name, school_type, district),
                "activity": rules.KIND_LABELS.get(kind, kind),
                "date": on,
                "status": statuses.get(status, status),
                "counted": "Yes",
                "channel": "Staff",
            }
        )
    return rows


def _outreach_rows(reads, staff, filters) -> list:
    if reads.schools is None or not reads.narrow.staff_side:
        return []
    found = list(
        reads.outreach()
        .annotate(on=_day())
        .values_list(
            "responsible_staff_id", *_SCHOOL_FIELDS, "activity_type", "on", "status"
        )
    )
    staff.learn(row[0] for row in found)
    statuses, types = _status_labels(), _type_labels()
    rows = []
    for staff_id, code, name, school_type, district, activity, on, status in found:
        person = staff.get(staff_id)
        if not _keeps_person(filters, person):
            continue
        lead, who, role = _who(person)
        rows.append(
            {
                "lead": lead,
                "staff": who,
                "role": role,
                **_school_cells(code, name, school_type, district),
                "activity": types.get(activity, activity),
                "date": on,
                "status": statuses.get(status, status),
                "counted": "No",
                "channel": "Staff",
            }
        )
    return rows


def _training_rows(reads, staff, filters, *, skip_counted_visits=False) -> list:
    """Staff trainings at a school. ``skip_counted_visits`` leaves out the
    in-school trainings a visit list already holds."""
    if reads.schools is None or not reads.narrow.staff_side:
        return []
    found = list(
        reads.school_trainings()
        .annotate(on=_day())
        .values_list(
            "responsible_staff_id",
            *_SCHOOL_FIELDS,
            "activity_type",
            "purpose_type",
            "on",
            "status",
        )
    )
    staff.learn(row[0] for row in found)
    statuses, types = _status_labels(), _type_labels()
    rows = []
    for (
        staff_id,
        code,
        name,
        school_type,
        district,
        activity,
        purpose,
        on,
        status,
    ) in found:
        if skip_counted_visits and rules.visit_kind(activity, purpose):
            continue
        person = staff.get(staff_id)
        if not _keeps_person(filters, person):
            continue
        lead, who, role = _who(person)
        rows.append(
            {
                "lead": lead,
                "staff": who,
                "role": role,
                **_school_cells(code, name, school_type, district),
                "activity": types.get(activity, activity),
                "date": on,
                "status": statuses.get(status, status),
                "counted": "",
                "channel": "Staff",
            }
        )
    return rows


def _session_rows(reads, staff, filters, *, meetings: bool | None = None) -> list:
    """Staff cluster sessions: ``meetings`` True for cluster meetings only,
    False for cluster trainings only, None for both."""
    from django.db.models import Count

    from apps.activities.models import ClusterActivityAttendance
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    if reads.schools is None or not reads.narrow.staff_side:
        return []
    meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
    sessions = reads.sessions()
    if meetings is True:
        sessions = sessions.filter(activity_type__in=meeting_types)
    elif meetings is False:
        sessions = sessions.exclude(activity_type__in=meeting_types)
    found = list(
        sessions.annotate(on=_day()).values_list(
            "id",
            "responsible_staff_id",
            "cluster__name",
            "cluster__district__name",
            "cluster__district__sub_region__name",
            "activity_type",
            "on",
            "status",
        )
    )
    staff.learn(row[1] for row in found)
    invited = dict(
        ClusterActivityAttendance.objects.filter(
            activity_id__in=[row[0] for row in found], invited=True
        )
        .values_list("activity_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    statuses, types = _status_labels(), _type_labels()
    rows = []
    for (
        activity_id,
        staff_id,
        cluster,
        district,
        sub_region,
        activity,
        on,
        status,
    ) in found:
        person = staff.get(staff_id)
        if not _keeps_person(filters, person):
            continue
        lead, who, role = _who(person)
        rows.append(
            {
                "lead": lead,
                "staff": who,
                "role": role,
                "school_id": "",
                "school": f"{cluster or 'Cluster'} (cluster)",
                "type": "",
                "district": district or "",
                "sub_region": sub_region or "",
                "cluster": cluster or "",
                "activity": types.get(activity, activity),
                "invited": invited.get(activity_id, 0),
                "date": on,
                "status": statuses.get(status, status),
                "counted": "",
                "channel": "Staff",
            }
        )
    return rows


def _partner_rows(reads, staff, filters) -> list:
    """Every piece of work in a Partner's hands, under who assigned it."""
    from apps.core.activity_types import TRAINING_TYPES
    from apps.partners.models import Partner

    if reads.schools is None or not reads.narrow.partner_side:
        return []
    handovers = list(
        reads.handovers().values_list(
            "partner_id",
            "status",
            "monitoring_staff_id",
            "assigning_staff_id",
            "scheduled_activity_id",
            "source_activity_id",
            "school__account_owner_id",
            "created_at",
            *_SCHOOL_FIELDS,
            "support_type",
            "visit_number",
            "training_number",
            "project_id",
            "expected_activity_type",
            "purpose_of_visit",
        )
    )
    work = list(
        reads.partner_work()
        .annotate(on=_day())
        .values_list(
            "id",
            "assigned_partner_id",
            "monitored_by_staff_id",
            "responsible_staff_id",
            "school__account_owner_id",
            "partner_planned",
            *_SCHOOL_FIELDS,
            "activity_type",
            "purpose_type",
            "on",
            "status",
            "created_at",
        )
    )
    staff.learn(i for row in handovers for i in (row[2], row[3], row[6]))
    staff.learn(i for row in work for i in (row[2], row[3], row[4]))
    partner_names = dict(
        Partner.objects.filter(
            id__in={row[0] for row in handovers} | {row[1] for row in work}
        ).values_list("id", "name")
    )
    statuses, types = _status_labels(), _type_labels()
    training_types = {str(t) for t in TRAINING_TYPES}
    rows = []

    def add(
        person,
        partner_id,
        school,
        *,
        activity,
        training,
        assigned_on,
        on,
        state,
        status,
    ):
        if not _keeps_person(filters, person):
            return
        lead, who, role = _who(person)
        rows.append(
            {
                "lead": lead,
                "staff": who,
                "role": role,
                "partner": partner_names.get(partner_id) or "Unrecorded Partner",
                **_school_cells(*school),
                "activity": activity,
                "is_training": training,
                "assigned_on": assigned_on,
                "date": on,
                "state": state,
                "status": status,
                "counted": "",
                "channel": "Partner",
            }
        )

    handed_by: dict[str, tuple] = {}
    carried: set[str] = set()
    for (
        partner_id,
        status,
        monitor,
        assigner,
        scheduled_activity_id,
        source_activity_id,
        holder,
        created_at,
        code,
        name,
        school_type,
        district,
        *kind_fields,
    ) in handovers:
        if scheduled_activity_id:
            handed_by[scheduled_activity_id] = (monitor, assigner, created_at)
            continue
        if not reads.waiting(status, created_at):
            continue
        if source_activity_id:
            carried.add(source_activity_id)
            handed_by[source_activity_id] = (monitor, assigner, created_at)
        if not reads.reads_handovers:
            continue
        handover = _Handover(*kind_fields)
        is_visit = handover_kind(school_type or "", handover) == "visit"
        expected = handover.expected_activity_type or ""
        kind = rules.visit_kind(expected or "school_visit", handover.purpose_of_visit)
        add(
            staff.get(monitor, assigner, holder),
            partner_id,
            (code, name, school_type, district),
            activity=(
                rules.KIND_LABELS.get(kind, "Visit")
                if is_visit
                else types.get(expected, "Training")
            ),
            training=not is_visit,
            assigned_on=_local(created_at),
            on=None,
            state="Awaiting the Partner's date",
            status="Waiting for the Partner to schedule",
        )
    for (
        activity_id,
        partner_id,
        monitor,
        responsible,
        holder,
        planned,
        code,
        name,
        school_type,
        district,
        activity,
        purpose,
        on,
        status,
        created_at,
    ) in work:
        if activity_id in carried:
            continue  # listed once, as the hand-over that carries it
        origin = handed_by.get(activity_id, ())
        kind = rules.visit_kind(activity, purpose)
        if planned:
            state = PARTNER_PLANNED
        elif on:
            state = "Dated by staff, not by the Partner"
        else:
            state = "Awaiting the Partner's date"
        add(
            staff.get(*origin[:2], monitor, responsible, holder),
            partner_id,
            (code, name, school_type, district),
            activity=rules.KIND_LABELS.get(kind) or types.get(activity, activity),
            training=activity in training_types,
            assigned_on=_local(origin[2] if origin else created_at),
            on=on,
            state=state,
            status=statuses.get(status, status),
        )
    return rows


def _local(moment):
    """A stored moment as the local day it fell on."""
    from apps.planning.country_oversight.coverage import _local_day

    return _local_day(moment) if moment is not None else None


def _cluster_rows(reads, staff, filters) -> list:
    from apps.clusters.models import Cluster

    if reads.schools is None:
        return []
    clusters = {
        row[0]: row
        for row in Cluster.objects.filter(status="active").values_list(
            "id",
            "name",
            "responsible_staff_id",
            "district__name",
            "district__sub_region__name",
        )
    }
    found = list(
        reads.schools.filter(cluster_id__in=list(clusters)).values_list(
            "school_id", "name", "school_type", "cluster_id", "account_owner_id"
        )
    )
    staff.learn(row[2] for row in clusters.values())
    staff.learn(row[4] for row in found)
    rows = []
    for code, name, school_type, cluster_id, holder in found:
        _id, cluster, responsible, district, sub_region = clusters[cluster_id]
        # The CCEO responsible for the cluster; the school's own holder where
        # the cluster names nobody.
        person = staff.get(responsible, holder)
        if not _keeps_person(filters, person):
            continue
        lead, who, _role = _who(person)
        rows.append(
            {
                "lead": lead,
                "sub_region": sub_region or "",
                "district": district or "",
                "cluster": cluster or "",
                "school_id": code or "",
                "school": name or "",
                "type": rules.type_label(school_type),
                "staff": who if person is not None else "Nobody recorded",
            }
        )
    return rows


# ── School tables (the page's own dataset) ───────────────────────────────────
def _school_rows(user, filters, wanted) -> list:
    """Schools the page's selection keeps for which ``wanted(school, vector)``
    holds, under whoever holds each."""
    dataset = svc.dataset_for(user, filters.window)
    rows = []
    kept = []
    for school in dataset.facts.values():
        values = school.vector
        if not values:
            continue
        owner = dataset.owners.get(school.owner_key)
        if not svc._keeps(school, owner, filters):
            continue
        if filters.planning_status and not svc._state_matches(
            filters, svc.state_of(values), values[svc.I_AWAITING]
        ):
            continue
        if wanted(school, values):
            kept.append((school, owner, values))
    cluster_names = svc._names(
        "clusters.Cluster", {school.raw_cluster_id for school, _o, _v in kept}
    )
    for school, owner, values in kept:
        partners = sorted(
            dataset.partner_names.get(pid, "Unrecorded Partner")
            for pid in (school.partners or {})
        )
        rows.append(
            {
                "lead": owner.lead_name if owner else svc.NO_LEAD_LABEL,
                "staff": owner.name if owner else svc.NO_OWNER_LABEL,
                **_school_cells(
                    school.code,
                    school.name,
                    school.school_type,
                    dataset.district_names.get(school.district_id, ""),
                ),
                "cluster": cluster_names.get(school.raw_cluster_id, "")
                if school.clustered
                else "Unclustered",
                "with_partner": ", ".join(partners)
                or ("Yes" if school.with_partner else "No"),
                "training": "Yes" if values[IDX["any_training"]] else "No",
                "visit": "Yes" if values[IDX["any_visit"]] else "No",
                "why": "; ".join(
                    rules.DUPLICATE_LABELS[reason]
                    for reason in duplicate_reasons(school)
                ),
                "staff_visits": school.staff[2],
                "partner": ", ".join(partners),
                "_school": school,
            }
        )
    return rows


def _lead_rank(user, filters):
    """A sort for school rows: the Leads in the page's own order."""
    dataset = svc.dataset_for(user, filters.window)
    order = {lead.name: index for index, lead in enumerate(dataset.leads)}
    return lambda row: (
        order.get(row["lead"], len(order)),
        row["lead"].casefold(),
        row["staff"].casefold(),
        row["school"].casefold(),
    )


# ── The tables ───────────────────────────────────────────────────────────────
SCHOOL_TABLES = {
    "not-planned": "no_visit",
    "no-training": "no_training",
    "unclustered": "unclustered",
}


def _twice_codes(user, filters) -> set:
    """The School IDs of every school planned twice in the year."""
    dataset = svc.dataset_for(user, filters.window)
    index = IDX["duplicates"]
    return {
        school.code
        for school in dataset.facts.values()
        if school.vector and school.vector[index]
    }


def _flag(rows: list, codes: set) -> list:
    for row in rows:
        row["flag"] = "Planned twice" if row.get("school_id") in codes else ""
    return rows


def _balance(planned: int, expected: int, unit: str = "planned") -> str:
    """ "6 of 560 planned · 554 to plan" — the balance a heading states."""
    if not expected:
        return f"{planned:,} {unit} · no target"
    return (
        f"{planned:,} of {expected:,} {unit} · "
        f"{max(0, expected - planned):,} to plan"
    )


def _people_notes(user, filters, text) -> dict:
    """Group path → balance, for a table grouped by Lead and then person.
    ``text(tally)`` words the balance from the dashboard's own row."""
    snapshot = svc.snapshot_for(user, filters)
    notes = {}
    for lead in snapshot.tree.leads:
        name = rules.NO_LEAD_LABEL if lead.is_no_lead else lead.name
        notes[(name,)] = text(lead.tally)
        for owner in lead.owners:
            notes[(name, owner.name)] = text(owner.tally)
    return notes


def _duplicate_table(user, filters, table: Table) -> Table:
    """Every plan at every school planned twice: one school, N plans."""
    from dataclasses import replace

    dataset = svc.dataset_for(user, filters.window)
    schools = {}
    for row in _school_rows(
        user, filters, lambda school, values: values[IDX["duplicates"]]
    ):
        school = row.pop("_school")
        schools[school.code] = (school.id, row)
    if not schools:
        table.summary = "No school is planned twice"
        return table
    from apps.core.scoping import resolve_user_scope

    # Every plan at those schools, whoever made it: the page's Lead and CCEO
    # choice picked the SCHOOLS (by who holds them), not the planners.
    everyone = replace(filters, program_lead="", cceo="")
    reads = people.Reads(
        None,
        filters.fy,
        window=svc._people_window(filters.window),
        scope=resolve_user_scope(user),
        narrow=people.Narrow(school_ids=tuple(pk for pk, _ in schools.values())),
    )
    staff = _Staff(reads.country)
    plans = _visit_rows(reads, staff, everyone) + [
        row for row in _partner_rows(reads, staff, everyone) if not row["is_training"]
    ]
    order = {lead.name: index for index, lead in enumerate(dataset.leads)}
    rows = []
    for plan in plans:
        _pk, school = schools.get(plan["school_id"], (None, None))
        if school is None:
            continue
        responsible = plan["staff"]
        if plan["channel"] == "Partner":
            responsible = f"{plan['partner']} (assigned by {plan['staff']})"
        rows.append(
            {
                **plan,
                "lead": school["lead"],
                "holder": school["staff"],
                "why": school["why"],
                "staff": responsible,
                "school_label": f"{plan['school_id']} · {plan['school']}",
            }
        )
    rows.sort(
        key=lambda row: (
            order.get(row["lead"], len(order)),
            row["lead"].casefold(),
            row["school"].casefold(),
            row["school_id"],
            _sortable(row.get("date")),
        )
    )
    table.rows = rows
    for row in rows:
        table.notes[(row["lead"], row["school_label"])] = row["why"]
    count = len({row["school_id"] for row in rows})
    table.summary = (
        f"{count:,} school{'' if count == 1 else 's'} planned twice · "
        f"{_count_line(len(rows), 'plan')} between them"
    )
    return table


def build(user, filters, key: str) -> Table:
    """The whole table for the page's selection, sorted, unpaged."""
    spec = SPECS[key]
    table = Table(spec=spec)
    if key == "duplicates":
        return _duplicate_table(user, filters, table)
    if key in SCHOOL_TABLES:
        index = IDX[SCHOOL_TABLES[key]]
        rows = _school_rows(user, filters, lambda school, values: values[index])
        for row in rows:
            row.pop("_school")
        table.rows = sorted(rows, key=_lead_rank(user, filters))
        table.summary = _count_line(len(rows), spec.unit)
        return table

    reads = _reads(user, filters)
    staff = _Staff(reads.country)
    twice = _twice_codes(user, filters)
    if key == "visits":
        rows = _flag(_visit_rows(reads, staff, filters), twice)
        table.rows = _sorted(rows, staff, "staff", "date", "school")
        table.summary = _count_line(len(rows), spec.unit) + " planned"
        table.notes = _people_notes(
            user, filters, lambda t: _balance(t.p_visits, t.target)
        )
    elif key == "partners":
        rows = _flag(_partner_rows(reads, staff, filters), twice)
        table.rows = _sorted(rows, staff, "staff", "partner", "school")
        dated = sum(1 for row in rows if row["state"] == PARTNER_PLANNED)
        schools = len({row["school_id"] for row in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} at {schools:,} "
            f"school{'' if schools == 1 else 's'} · {dated:,} planned by the Partner "
            f"· {len(rows) - dated:,} awaiting the Partner's date"
        )
        table.notes = _people_notes(
            user,
            filters,
            lambda t: (
                f"{t.pp_work:,} of {t.pa_work:,} planned by the Partner · "
                f"{t.partner_waiting:,} awaiting the Partner's date"
            ),
        )
    elif key == "plans":
        rows = _flag(
            _visit_rows(reads, staff, filters)
            + _outreach_rows(reads, staff, filters)
            + _training_rows(reads, staff, filters, skip_counted_visits=True)
            + _session_rows(reads, staff, filters)
            + _partner_rows(reads, staff, filters),
            twice,
        )
        for row in rows:
            if row["channel"] == "Partner":
                row["staff"] = f"{row['partner']} (assigned by {row['staff']})"
        table.rows = _sorted(rows, staff, "channel", "staff", "date", "school")
        by_staff = sum(1 for row in rows if row["channel"] == "Staff")
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} · {by_staff:,} by staff · "
            f"{len(rows) - by_staff:,} with Partners"
        )
    elif key == "trainings":
        rows = (
            _training_rows(reads, staff, filters)
            + _session_rows(reads, staff, filters, meetings=False)
            + [
                row
                for row in _partner_rows(reads, staff, filters)
                if row["is_training"]
            ]
        )
        for row in rows:
            if row["channel"] == "Partner":
                row["staff"] = f"{row['partner']} (assigned by {row['staff']})"
        table.rows = _sorted(rows, staff, "channel", "staff", "date", "school")
        table.summary = _count_line(len(rows), spec.unit) + " planned"
    elif key == "clusters":
        rows = _cluster_rows(reads, staff, filters)
        table.rows = _sorted(rows, staff, "sub_region", "district", "cluster", "school")
        clusters = len({(r["district"], r["cluster"]) for r in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} in {clusters:,} "
            f"cluster{'' if clusters == 1 else 's'}"
        )
    elif key == "meetings":
        rows = _session_rows(reads, staff, filters, meetings=True)
        table.rows = _sorted(rows, staff, "sub_region", "district", "cluster", "date")
        invited = sum(row["invited"] for row in rows)
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} planned · {invited:,} school "
            f"invitation{'' if invited == 1 else 's'}"
        )
    return table


def _count_line(count: int, unit: str) -> str:
    if count == 1:
        return f"1 {unit}"
    plural = f"{unit[:-1]}ies" if unit.endswith("y") else f"{unit}s"
    return f"{count:,} {plural}"


def page_of(table: Table, page: int) -> dict:
    """One page of a table: the shared pager, and its rows under their group
    headings. A heading says how many rows the whole group holds and, where
    the table has one, the group's balance: planned of expected, and what
    remains."""
    from apps.core.pagination import paginate_rows

    pager = paginate_rows(table.rows, page=page, page_size=ROWS_PER_PAGE)
    counts = table.group_counts()
    levels = table.heading_levels
    shown = table.shown_columns
    lines = []
    last: tuple = ()
    for row in pager["rows"]:
        group = table.group_of(row)
        for depth, level in enumerate(levels):
            path = group[:level]
            if last[:level] == path:
                continue
            # A nested heading names its own level; a lone one, the path.
            label = group[level - 1] if len(levels) > 1 else " · ".join(path)
            lines.append(
                {
                    "heading": label,
                    "depth": depth,
                    "count": _count_line(counts[path], table.spec.unit),
                    "note": table.notes.get(path, ""),
                }
            )
        last = group
        lines.append(
            {
                "cells": [(column, row.get(column.key)) for column in shown],
                "school_id": row.get("school_id") or "",
            }
        )
    return {"pager": pager, "lines": lines, "columns": shown}


def sheet(table: Table) -> dict:
    """The whole table as one workbook sheet: every column, groups included."""
    columns = table.spec.columns
    return {
        "title": table.spec.title,
        "headers": [column.label for column in columns],
        "number_formats": {
            index: "d mmm yyyy"
            for index, column in enumerate(columns, start=1)
            if column.is_date
        },
        "rows": [
            [
                "" if row.get(column.key) is None else row.get(column.key)
                for column in columns
            ]
            for row in table.rows
        ],
    }
