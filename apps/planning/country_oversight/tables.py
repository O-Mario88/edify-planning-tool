"""The consolidated tables behind the Country Director's cards, and the ones
Impact Assessment analyses the country's planning from.

Owner, 2026-10-01: every card on Country Planning Oversight is a link to the
table of what it counts — the plans, the schools, the meetings — grouped by
Programme Lead, so a figure can be followed up with the person it belongs to.

Owner, 2026-10-02, for Impact Assessment: one table of every visit staff and
Partners have planned, one of the schools nobody has planned, one of the
schools assigned to Partners, one of the schools in a project, and one of
every activity — each under the Programme Lead, sub-region, district, CCEO or
Programme Lead and cluster of the school, each saying the activity planned
and its SSA intervention, and each exported with every planning detail.

Each table lists the same rows its card counts: the people-first tables read
``people.Reads`` (the queries the cards aggregate), the school tables read the
page's own dataset, and both apply the page's filters. A table that lists
schools carries the School ID.

Every table is an ordinary table, as My Plan and Planning Oversight draw
theirs (owner, 2026-10-02: "a normal table with sub region, cceo, PL, cluster
all in columns"): it opens with the Programme Lead, sub-region, district, CCEO
or Programme Lead and cluster of the school, then the School ID, the school
and the rest. Those five are who HOLDS the school (owner, 2026-10-02), so one
school is under one person in every table; who planned the work there is a
column of its own. The page's Programme Lead and CCEO choice still keeps a
PERSON's plan, as the cards count it.

Every table is one flat list, sorted by those five columns and then by what a
reader scans for: the page shows it a page at a time and the workbook holds
all of it, with the planning details beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

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
#: What a Partner's work says in place of a date until the PARTNER sets one
#: (owner, 2026-10-02: "Partner visit should be scheduled by partner. Date
#: entered by staff should just indicate when the school is assigned").
AWAITING_PARTNER = "Awaiting partner schedule"
AWAITING_COORDINATOR = "Awaiting Project Coordinator"
ASSIGNED = "Assigned to Partner"
UNCLUSTERED = "Unclustered"
#: What a data collection visit is called in a list: shown, never counted
#: (owner, 2026-10-02).
DATA_COLLECTION = "SSA Support"
#: Partner work in these states has not happened yet: without the Partner's
#: own date it is still waiting for one.
_WAITING_STATES = frozenset(
    {"planned", "scheduled", "partner_scheduled", "assigned_to_partner", "rescheduled"}
)


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    numeric: bool = False
    # A date column; the page and the workbook format it.
    is_date: bool = False
    # The school's name: linked to the school on the page.
    is_school: bool = False
    # What a date column says while it has no date. A row may say its own
    # (``<key>_note``): whose turn it is to set one.
    blank: str = ""


@dataclass(frozen=True)
class Extra:
    """The choices only a table offers, beside the page's own filters."""

    sub_region: str = ""
    cluster: str = ""
    project: str = ""

    def params(self) -> dict:
        return {
            name: value
            for name, value in (
                ("sub_region", self.sub_region),
                ("cluster", self.cluster),
                ("project", self.project),
            )
            if value
        }


def read_extra(request) -> Extra:
    def pick(name):
        value = (request.GET.get(name) or "").strip()
        return "" if value in ("all", "All") else value

    return Extra(
        sub_region=pick("sub_region"), cluster=pick("cluster"), project=pick("project")
    )


@dataclass(frozen=True)
class Spec:
    key: str
    title: str
    # What a row is, for the count line ("visit", "school", "meeting").
    unit: str
    description: str
    columns: tuple
    # Columns kept for the workbook and left off the page: the planning
    # details a reader analyses rather than scans.
    export_only: tuple = ()
    # The card this table is the detail of, if any.
    metric: str = ""
    short: str = ""


@dataclass
class Table:
    spec: Spec
    rows: list = field(default_factory=list)
    # A line beside the title: what the rows add up to.
    summary: str = ""

    @property
    def shown_columns(self) -> list:
        hidden = set(self.spec.export_only)
        return [c for c in self.spec.columns if c.key not in hidden]

    def place_of(self, row: dict) -> tuple:
        """The five columns every table opens with, for one row."""
        return tuple(row.get(key) or "" for key in PLACE_GROUPS)


C = Column
LEAD = C("lead", "Programme Lead")
#: Says so on every plan at a school that is planned twice: a duplicate is
#: shown in the list it belongs to, never dropped from it.
FLAG = C("flag", "Planned Twice")
SCHOOL_COLUMNS = (
    C("school_id", "School ID"),
    C("school", "School Name", is_school=True),
    C("type", "School Type"),
    C("district", "District"),
)
#: Where a school sits (owner, 2026-10-02): the Programme Lead, sub-region,
#: district, the CCEO or Programme Lead who holds it, and its cluster.
PLACE = (
    LEAD,
    C("sub_region", "Sub-region"),
    C("district", "District"),
    C("holder", "CCEO / PL"),
    C("cluster", "Cluster"),
)
PLACE_GROUPS = tuple(column.key for column in PLACE)
SCHOOL = SCHOOL_COLUMNS[:3]
INTERVENTION = C("intervention", "SSA Intervention")
COURSE = C("course", "Training")
PLANNED_DATE = C("date", "Planned Date", is_date=True, blank=AWAITING_PARTNER)
#: The planning details a workbook carries for analysis (owner, 2026-10-02:
#: "export all the above with all planning details").
DETAILS = (
    C("purpose", "Purpose"),
    C("project", "Project"),
    C("partner", "Partner"),
    C("assigned_by", "Assigned By"),
    C("facilitator", "Facilitated By"),
    C("monitor", "Monitored By"),
    C("role", "Planner's Role"),
    C("quarter", "Quarter"),
    C("participants", "Participants", numeric=True),
    C("invited", "Schools Invited", numeric=True),
    C("cost", "Planned Cost (UGX)", numeric=True),
    C("salesforce", "Salesforce ID"),
    C("evidence", "Evidence"),
    C("ia", "IA Verification"),
    C("payment", "Payment"),
    C("rescheduled", "Times Rescheduled", numeric=True),
    C("recorded", "Recorded On", is_date=True),
)
DETAIL_KEYS = tuple(column.key for column in DETAILS)
#: The same, for a table of sessions: how many schools one invited and the
#: Partner who facilitates it are on the page too.
SESSION_DETAIL_KEYS = tuple(
    key for key in DETAIL_KEYS if key not in ("invited", "facilitator")
)
#: What a school needs in the year, what is planned and what remains.
SCHOOL_PLAN = (
    C("visits_needed", "Visits Needed", numeric=True),
    # Who the visits are expected from (owner, 2026-10-03): staff and the
    # Partner two each at a Core school; at any other, staff while the
    # holder's capacity reaches it and the Partner past that.
    C("expected_from", "Expected From"),
    C("visits_planned", "Visits Planned", numeric=True),
    C("visits_remaining", "Visits Remaining", numeric=True),
    C("with_partner", "With a Partner"),
    C("trainings_needed", "Trainings Needed", numeric=True),
    C("trainings_planned", "Trainings Planned", numeric=True),
    C("trainings_remaining", "Trainings Remaining", numeric=True),
)


def _without(columns, *keys) -> tuple:
    return tuple(column for column in columns if column.key not in keys)


SPECS: dict[str, Spec] = {
    spec.key: spec
    for spec in (
        Spec(
            "visits",
            "Staff Visit Plans",
            "visit",
            "Every Follow up and In-school Training visit staff "
            "have planned, with who planned it. These are the visits counted "
            "against each CCEO's 560 and each Programme Lead's 280.",
            (
                *PLACE,
                *SCHOOL,
                C("activity", "Visit"),
                INTERVENTION,
                C("staff", "Planned By"),
                C("date", "Planned Date", is_date=True),
                C("status", "Status"),
                FLAG,
                *_without(DETAILS, "partner", "assigned_by", "invited"),
            ),
            export_only=DETAIL_KEYS,
            metric="cpo_staff_visit_planning",
            short="Staff Visits",
        ),
        Spec(
            "all-visits",
            "All Visit Plans",
            "visit",
            "Every visit planned for the year, by staff and by Partners. A "
            "Partner's visit is listed once the Partner has set its date; "
            "until then it is in Schools Assigned to Partners. SSA Support, "
            "donor, story, social and invitation visits are listed and "
            "marked as not counted toward a person's target.",
            (
                *PLACE,
                *SCHOOL,
                C("activity", "Visit"),
                INTERVENTION,
                C("channel", "By"),
                C("by_name", "Planned By"),
                PLANNED_DATE,
                C("status", "Status"),
                C("counted", "Counts Toward Target"),
                FLAG,
                *_without(DETAILS, "invited"),
            ),
            export_only=DETAIL_KEYS,
            short="All Visits",
        ),
        Spec(
            "partners",
            "Schools Assigned to Partners",
            "assignment",
            "Every piece of work staff put in a Partner's hands, with the "
            "Partner who holds it. The Planned Date is the date the Partner "
            "has set — until the Partner sets one it reads Awaiting partner "
            "schedule, whatever day staff entered. Partner planning counts "
            "only what a Partner dated.",
            (
                *PLACE,
                C("partner", "Partner"),
                *SCHOOL,
                C("activity", "Activity"),
                INTERVENTION,
                C("staff", "Assigned By"),
                C("assigned_on", "Assigned On", is_date=True),
                PLANNED_DATE,
                C("status", "Status"),
                FLAG,
                C("state", "Partner Planning"),
                C("staff_date", "Date Entered by Staff", is_date=True),
                COURSE,
                *_without(DETAILS, "partner", "assigned_by", "invited"),
            ),
            export_only=(
                "state",
                "staff_date",
                "course",
                *(key for key in DETAIL_KEYS if key != "partner"),
            ),
            metric="cpo_partner_planning",
            short="Partners",
        ),
        Spec(
            "projects",
            "Project Schools",
            "school",
            "Every school in a live project, read from the Project "
            "Coordinators' own records: the project it is in, who added it, "
            "who holds the work, the activity planned, its SSA intervention "
            "and the planned date — or whose turn it is to set one.",
            (
                *PLACE,
                C("project", "Project"),
                *SCHOOL,
                C("activity", "Activity"),
                INTERVENTION,
                C("coordinator", "Project Coordinator"),
                C("added_by", "Added By"),
                C("channel", "By"),
                C("by_name", "Planned By"),
                PLANNED_DATE,
                C("status", "Status"),
                C("purpose", "Purpose"),
                C("enrolled_on", "Enrolled On", is_date=True),
                C("planned_n", "Activities Planned", numeric=True),
                C("delivered_n", "Activities Delivered", numeric=True),
                C("verified_n", "Activities Verified", numeric=True),
                C("last_delivered", "Last Delivered", is_date=True),
                C("movement", "SSA Movement"),
            ),
            export_only=(
                "purpose",
                "enrolled_on",
                "planned_n",
                "delivered_n",
                "verified_n",
                "last_delivered",
                "movement",
            ),
            short="Projects",
        ),
        Spec(
            "project-partners",
            "Project Schools With Partners",
            "assignment",
            "Every piece of project work a Project Coordinator has put in a "
            "Partner's hands: the project, the Partner, the school, the "
            "activity and its SSA intervention, who assigned it and when. "
            "The Planned Date is the date the Partner has set; until then it "
            "reads Awaiting partner schedule.",
            (
                *PLACE,
                C("project", "Project"),
                C("partner", "Partner"),
                *SCHOOL,
                C("activity", "Activity"),
                INTERVENTION,
                C("staff", "Assigned By"),
                C("assigned_on", "Assigned On", is_date=True),
                PLANNED_DATE,
                C("status", "Status"),
                C("state", "Partner Planning"),
                C("staff_date", "Date Entered by Staff", is_date=True),
                COURSE,
                *_without(DETAILS, "project", "partner", "assigned_by", "invited"),
            ),
            export_only=(
                "state",
                "staff_date",
                "course",
                *(key for key in DETAIL_KEYS if key not in ("project", "partner")),
            ),
            short="Project Partners",
        ),
        Spec(
            "project-activities",
            "Project Activities Scheduled",
            "activity",
            "Every project activity with a date on it: scheduled by a Project "
            "Coordinator or other staff, or by the Partner it was assigned "
            "to. One row an activity, so a school with three project "
            "activities is three rows. Work a Partner has not dated yet is in "
            "Project Schools With Partners.",
            (
                *PLACE,
                C("project", "Project"),
                *SCHOOL,
                C("activity", "Activity"),
                COURSE,
                INTERVENTION,
                C("channel", "By"),
                C("by_name", "Scheduled By"),
                C("date", "Planned Date", is_date=True),
                C("status", "Status"),
                *_without(DETAILS, "project"),
            ),
            export_only=tuple(key for key in DETAIL_KEYS if key != "project"),
            short="Project Activities",
        ),
        Spec(
            "plans",
            "All Activities",
            "activity",
            "Every activity planned for the year — visits, trainings, cluster "
            "meetings and other work, by staff and with Partners — with its "
            "SSA intervention. The workbook carries every planning detail, "
            "for analysis. SSA Support, donor, story, social and invitation "
            "visits are marked as not counted toward a person's target.",
            (
                *PLACE,
                *SCHOOL,
                C("activity", "Activity"),
                COURSE,
                INTERVENTION,
                C("channel", "By"),
                C("by_name", "Planned By"),
                PLANNED_DATE,
                C("status", "Status"),
                C("counted", "Counts Toward Target"),
                FLAG,
                *DETAILS,
            ),
            export_only=("counted", *DETAIL_KEYS),
            metric="cpo_total_visit_coverage",
            short="All Activities",
        ),
        Spec(
            "trainings",
            "Training Plans",
            "training",
            "Every training planned for the year: at a school, for a cluster, "
            "by staff and by Partners. A cluster training reaches the schools "
            "on its planned roster.",
            (
                *PLACE,
                *SCHOOL,
                C("activity", "Training"),
                C("course", "Course"),
                INTERVENTION,
                C("channel", "By"),
                C("by_name", "Planned By"),
                C("invited", "Schools Invited", numeric=True),
                PLANNED_DATE,
                C("status", "Status"),
                *_without(DETAILS, "invited"),
            ),
            export_only=SESSION_DETAIL_KEYS,
            metric="cpo_training_planning",
            short="Trainings",
        ),
        Spec(
            "clusters",
            "Clustered Schools",
            "school",
            "Every school in an active cluster, with the CCEO responsible for "
            "the cluster and that CCEO's Programme Lead.",
            (*PLACE, *SCHOOL),
            metric="cpo_cluster_membership",
            short="Clusters",
        ),
        Spec(
            "meetings",
            "Cluster Meeting Plans",
            "meeting",
            "Every cluster meeting staff have planned, with the CCEO "
            "responsible for the cluster, the staff member who planned the "
            "meeting and the schools on its roster.",
            (
                *PLACE,
                C("activity", "Meeting"),
                INTERVENTION,
                C("staff", "Planned By"),
                C("date", "Planned Date", is_date=True),
                C("status", "Status"),
                C("invited", "Schools Invited", numeric=True),
                *_without(DETAILS, "partner", "assigned_by", "invited"),
            ),
            export_only=SESSION_DETAIL_KEYS,
            metric="cpo_cluster_meeting_planning",
            short="Meetings",
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
                *PLACE,
                *SCHOOL,
                C("why", "Why"),
                C("channel", "By"),
                C("staff", "Responsible"),
                C("activity", "Plan"),
                INTERVENTION,
                PLANNED_DATE,
                C("status", "Status"),
            ),
            short="Planned Twice",
        ),
        Spec(
            "not-planned",
            "Unplanned Schools",
            "school",
            "Schools that need a visit this year and have none planned and "
            "none in a Partner's hands. A school assigned to a Partner is the "
            "Partner's to plan: it is in Schools Assigned to Partners.",
            (*PLACE, *SCHOOL, *SCHOOL_PLAN),
            export_only=("visits_planned", "with_partner"),
            short="Unplanned",
        ),
        Spec(
            "partly-planned",
            "Schools Partly Planned",
            "school",
            "Schools with some of the year's visits planned and some still to "
            "plan: what each needs, what is planned and what remains.",
            (*PLACE, *SCHOOL, *SCHOOL_PLAN),
            short="Partly Planned",
        ),
        Spec(
            "no-training",
            "Schools With No Training Planned",
            "school",
            "Schools that need a training this year and have none planned.",
            (*PLACE, *SCHOOL, *SCHOOL_PLAN),
            export_only=("trainings_planned",),
            short="No Training",
        ),
        Spec(
            "unclustered",
            "Unclustered Schools",
            "school",
            "Schools that are in no active cluster. A school has to be in a "
            "cluster before a cluster meeting or a cluster training can "
            "reach it.",
            (*PLACE, *SCHOOL, *SCHOOL_PLAN),
            short="Unclustered",
        ),
    )
}

#: The table each card opens.
METRIC_TABLES = {spec.metric: spec.key for spec in SPECS.values() if spec.metric}
#: The tables offered side by side on the table page: every activity first,
#: then the visits, the Partners' and the projects' schools, the rest of the
#: cards' tables, and the schools still to plan.
TAB_ORDER = (
    "plans",
    "all-visits",
    "visits",
    "partners",
    "projects",
    "project-partners",
    "project-activities",
    "trainings",
    "clusters",
    "meetings",
    "not-planned",
    "partly-planned",
    "no-training",
    "unclustered",
    "duplicates",
)
#: The workbook "Export all" downloads: the tables Impact Assessment asked
#: for, a sheet each.
WORKBOOK = (
    "plans",
    "all-visits",
    "partners",
    "projects",
    "project-partners",
    "project-activities",
    "not-planned",
)
#: The three tables Impact Assessment follows the projects from (owner,
#: 2026-10-02: "all the schools assigned to project, assigned by project
#: coordinators to partners and scheduled").
PROJECT_TABLES = ("projects", "project-partners", "project-activities")


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


def _labels(choices) -> dict:
    return {str(value): str(label) for value, label in choices}


def _status_labels() -> dict:
    from apps.core.enums import ActivityStatus

    return _labels(ActivityStatus.choices)


def _type_labels() -> dict:
    from apps.core.enums import ActivityType

    return _labels(ActivityType.choices)


def _field_labels(name: str) -> dict:
    from apps.activities.models import Activity

    return _labels(Activity._meta.get_field(name).choices or ())


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


def _sortable(value):
    if value is None:
        return (1, "")
    if isinstance(value, date):
        return (0, value.isoformat())
    return (0, str(value).casefold())


def _local(moment):
    """A stored moment as the local day it fell on."""
    from apps.planning.country_oversight.coverage import _local_day

    return _local_day(moment) if moment is not None else None


# ── Where a school sits ──────────────────────────────────────────────────────
class _Places:
    """Who holds a school and their Programme Lead, and its sub-region,
    district and cluster — read from the page's own dataset, so a school is
    under the same person in every table."""

    def __init__(self, user, filters):
        self.dataset = svc.dataset_for(user, filters.window)
        self.lead_order = {
            lead.name: index for index, lead in enumerate(self.dataset.leads)
        }

    @cached_property
    def districts(self) -> dict:
        """district id → (name, sub-region id, sub-region name)."""
        from apps.geography.models import District

        return {
            pk: (name or "", sub_id or "", sub_name or "")
            for pk, name, sub_id, sub_name in District.objects.values_list(
                "id", "name", "sub_region_id", "sub_region__name"
            )
        }

    @cached_property
    def clusters(self) -> dict:
        """cluster id → (name, district id, responsible staff id)."""
        from apps.clusters.models import Cluster

        return {
            pk: (name or "", district_id, responsible)
            for pk, name, district_id, responsible in Cluster.objects.values_list(
                "id", "name", "district_id", "responsible_staff_id"
            )
        }

    def of_record(self, record) -> dict:
        owner = self.dataset.owners.get(record.owner_key)
        district, sub_id, sub_region = self.districts.get(
            record.district_id, ("", "", "")
        )
        cluster = self.clusters.get(record.raw_cluster_id) if record.clustered else None
        return {
            "holder_lead": owner.lead_name if owner else svc.NO_LEAD_LABEL,
            "holder": owner.name if owner else svc.NO_OWNER_LABEL,
            "sub_region": sub_region,
            "district": district,
            "cluster": (cluster[0] or "Cluster") if cluster else UNCLUSTERED,
            "school_id": record.code or "",
            "school": record.name or "",
            "type": rules.type_label(record.school_type) if record.school_type else "",
            "_sub_region": sub_id,
            "_cluster": record.raw_cluster_id if cluster else "",
            "_school": record.id,
        }

    def of_school(self, school) -> dict | None:
        """A School row's place; its own columns where the dataset, read a
        moment earlier, does not hold it yet."""
        if school is None:
            return None
        record = self.dataset.facts.get(school.id)
        if record is not None:
            return self.of_record(record)
        district, sub_id, sub_region = self.districts.get(
            school.district_id, ("", "", "")
        )
        cluster = self.clusters.get(school.cluster_id)
        return {
            "holder_lead": svc.NO_LEAD_LABEL,
            "holder": svc.NO_OWNER_LABEL,
            "sub_region": sub_region,
            "district": district,
            "cluster": (cluster[0] or "Cluster") if cluster else UNCLUSTERED,
            "school_id": school.school_id or "",
            "school": school.name or "",
            "type": rules.type_label(school.school_type) if school.school_type else "",
            "_sub_region": sub_id,
            "_cluster": school.cluster_id if cluster else "",
            "_school": school.id,
        }

    def of_cluster(self, cluster_id, person) -> dict:
        """A cluster session's place: the cluster's own district, under the
        person responsible for the cluster."""
        name, district_id, _responsible = self.clusters.get(
            cluster_id, ("", None, None)
        )
        district, sub_id, sub_region = self.districts.get(district_id, ("", "", ""))
        lead, who, _role = _who(person)
        return {
            "holder_lead": lead,
            "holder": who,
            "sub_region": sub_region,
            "district": district,
            "cluster": name or "Cluster",
            "school_id": "",
            "school": f"{name or 'Cluster'} (cluster)",
            "type": "",
            "_sub_region": sub_id,
            "_cluster": cluster_id or "",
            "_school": "",
        }

    def responsible(self, cluster_id):
        return self.clusters.get(cluster_id, ("", None, None))[2]

    def sort(self, rows: list, *keys) -> list:
        """Rows by Programme Lead (the page's order), then place, then
        ``keys``."""
        order = self.lead_order

        def sort_key(row):
            return (
                order.get(row["lead"], len(order)),
                row["lead"].casefold(),
                *(
                    _sortable(row.get(key))
                    for key in ("sub_region", "district", "holder", "cluster", *keys)
                ),
            )

        return sorted(rows, key=sort_key)


# ── The rows behind the people-first tables ──────────────────────────────────
#: What a listed activity is read with: one query a set, whatever its size.
_ACTIVITY_ONLY = (
    "id",
    "school",
    "cluster",
    "training_course",
    "catalogue_item",
    "project_id",
    "responsible_staff_id",
    "monitored_by_staff_id",
    "assigned_partner_id",
    "facilitating_partner_id",
    "delivery_type",
    "activity_type",
    "purpose_type",
    "focus_intervention",
    "purpose_intervention",
    "activity_name_snapshot",
    "status",
    "evidence_status",
    "ia_verification_status",
    "payment_status",
    "salesforce_activity_id",
    "quarter",
    "expected_participants",
    "participants_per_school",
    "reschedule_count",
    "created_at",
    "training_course__display_name",
    "training_course__source_name",
    "catalogue_item__display_name",
    "catalogue_item__source_name",
    "school__school_id",
    "school__name",
    "school__school_type",
    "school__district_id",
    "school__cluster_id",
    "school__account_owner_id",
)


def _read(queryset) -> list:
    return list(
        queryset.annotate(on=_day())
        .select_related("training_course", "catalogue_item", "school")
        .only(*_ACTIVITY_ONLY)
    )


class _Book:
    """One table's reading of the year: the page's selection, who everybody
    is, where every school sits, and the names the rows spell out."""

    def __init__(self, user, filters, extra: Extra | None = None, *, reads=None):
        from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
        from apps.core.enums import SsaIntervention

        self.user = user
        self.filters = filters
        self.extra = extra or Extra()
        self.reads = reads or _reads(user, filters)
        self.staff = _Staff(self.reads.country)
        self.places = _Places(user, filters)
        self.statuses = _status_labels()
        self.types = _type_labels()
        self.interventions = _labels(SsaIntervention.choices)
        self.evidence = _field_labels("evidence_status")
        self.verification = _field_labels("ia_verification_status")
        self.payment = _field_labels("payment_status")
        self.training_types = {str(t) for t in TRAINING_TYPES}
        self.meeting_types = {str(t) for t in CLUSTER_MEETING_TYPES}
        self.partners: dict = {}
        self.projects: dict = {}
        self.costs: dict = {}
        self.invited: dict = {}

    @property
    def staff_side(self) -> bool:
        return self.reads.schools is not None and self.reads.narrow.staff_side

    @property
    def partner_side(self) -> bool:
        return self.reads.schools is not None and self.reads.narrow.partner_side

    @cached_property
    def fixed(self) -> dict:
        from apps.activity_catalogue.training_intervention import fixed_interventions

        return fixed_interventions()

    def learn(self, activities, *, staff_ids=(), partner_ids=(), project_ids=()):
        """Look up, in one query each, what these rows name."""
        from django.db.models import Count

        from apps.activities.models import ClusterActivityAttendance
        from apps.planning.oversight_service import _cost_by_activity

        ids = set(staff_ids)
        partners = set(partner_ids)
        projects = set(project_ids)
        sessions = []
        for a in activities:
            ids.update((a.responsible_staff_id, a.monitored_by_staff_id))
            partners.update((a.assigned_partner_id, a.facilitating_partner_id))
            projects.add(a.project_id)
            if a.school_id is None:
                ids.add(self.places.responsible(a.cluster_id))
                sessions.append(a.id)
            else:
                ids.add(a.school.account_owner_id)
        self.staff.learn(ids)
        self.partners.update(
            svc._names("partners.Partner", partners - set(self.partners))
        )
        self.projects.update(
            svc._names("projects.Project", projects - set(self.projects))
        )
        self.costs.update(_cost_by_activity([a.id for a in activities]))
        if sessions:
            self.invited.update(
                ClusterActivityAttendance.objects.filter(
                    activity_id__in=sessions, invited=True
                )
                .values_list("activity_id")
                .annotate(n=Count("id"))
                .order_by()
            )

    def keeps(self, person, place, project_id) -> bool:
        if not _keeps_person(self.filters, person):
            return False
        extra = self.extra
        if extra.sub_region and place["_sub_region"] != extra.sub_region:
            return False
        if extra.cluster and place["_cluster"] != extra.cluster:
            return False
        if extra.project and (project_id or "") != extra.project:
            return False
        return True

    def type_label(self, activity_type) -> str:
        code = str(activity_type or "")
        return self.types.get(code) or code.replace("_", " ").title()

    def describe(self, activity) -> tuple[str, str, str]:
        """(course, purpose, SSA intervention), in the words Partner and
        Project Monitoring use for the same work."""
        from apps.planning.partner_oversight_service import describe_work

        course, purpose, intervention = describe_work(
            activity=activity, catalogue_item=activity.catalogue_item
        )
        if not intervention and activity.activity_type in self.training_types:
            # A training saved before its course's intervention was stamped
            # on it (owner, 2026-09-29: every training carries one).
            code = self.fixed.get(activity.training_course_id) or self.fixed.get(
                activity.catalogue_item_id
            )
            intervention = self.interventions.get(code or "", "")
        return course, purpose, intervention

    def row(self, activity, person, *, channel, label="", counted="", holder=None):
        """One listed activity, or None where the page's selection drops it.
        ``person`` is whose plan it is; ``holder`` whose cluster a session
        belongs to (the person who planned it, where nobody is named)."""
        if activity.school_id is None:
            place = self.places.of_cluster(activity.cluster_id, holder or person)
        else:
            place = self.places.of_school(activity.school)
        if place is None or not self.keeps(person, place, activity.project_id):
            return None
        lead, who, role = _who(person)
        course, purpose, intervention = self.describe(activity)
        partner = self.partners.get(activity.assigned_partner_id, "")
        monitor = self.staff.get(activity.monitored_by_staff_id)
        row = {
            **place,
            "planner_lead": lead,
            "lead": place["holder_lead"],
            "staff": who,
            "role": role,
            "channel": channel,
            "by_name": who,
            "activity": label or self.type_label(activity.activity_type),
            "course": course,
            "purpose": purpose,
            "intervention": intervention,
            "date": activity.on,
            "status": self.statuses.get(activity.status, activity.status),
            "counted": counted,
            "project": self.projects.get(activity.project_id, ""),
            "_project": activity.project_id or "",
            "partner": partner if channel == "Partner" else "",
            "assigned_by": "",
            "facilitator": self.partners.get(activity.facilitating_partner_id, ""),
            "monitor": monitor.name if monitor is not None else "",
            "quarter": activity.quarter or "",
            "participants": activity.participants_per_school
            or activity.expected_participants
            or "",
            "cost": self.costs.get(activity.id, 0),
            "salesforce": activity.salesforce_activity_id or "",
            "evidence": self.evidence.get(activity.evidence_status, ""),
            "ia": self.verification.get(activity.ia_verification_status, ""),
            "payment": self.payment.get(activity.payment_status, ""),
            "rescheduled": activity.reschedule_count or 0,
            "recorded": _local(activity.created_at),
            "is_training": activity.activity_type in self.training_types,
            # A Follow up or an In-school Training: the two visits that count
            # (an in-school training is a training too).
            "is_visit": rules.visit_kind(
                activity.activity_type, activity.purpose_type, activity.project_id
            )
            is not None,
        }
        if activity.school_id is None:
            row["invited"] = self.invited.get(activity.id, 0)
        return row


def _kept(rows) -> list:
    return [row for row in rows if row is not None]


def _visit_rows(book: _Book) -> list:
    if not book.staff_side:
        return []
    found = _read(book.reads.counted_visits())
    book.learn(found)
    return _kept(
        book.row(
            a,
            book.staff.get(a.responsible_staff_id),
            channel="Staff",
            label=rules.KIND_LABELS.get(a.kind, a.kind),
            counted="Yes",
        )
        for a in found
    )


def _outreach_rows(book: _Book) -> list:
    if not book.staff_side:
        return []
    found = _read(book.reads.outreach())
    book.learn(found)
    return _kept(
        book.row(
            a,
            book.staff.get(a.responsible_staff_id),
            channel="Staff",
            counted="No",
            label=DATA_COLLECTION
            if rules.is_data_collection(a.activity_type, a.purpose_type)
            else "",
        )
        for a in found
    )


def _training_rows(book: _Book, *, skip_counted_visits=False) -> list:
    """Staff trainings at a school. ``skip_counted_visits`` leaves out the
    in-school trainings a visit list already holds."""
    if not book.staff_side:
        return []
    found = [
        a
        for a in _read(book.reads.school_trainings())
        # An Alumni training is on no visit list, so it stays on this one.
        if not (
            skip_counted_visits
            and rules.visit_kind(a.activity_type, a.purpose_type, a.project_id)
        )
    ]
    book.learn(found)
    return _kept(
        book.row(a, book.staff.get(a.responsible_staff_id), channel="Staff")
        for a in found
    )


def _other_rows(book: _Book) -> list:
    """Staff work at a school that is neither a visit nor a training."""
    if not book.staff_side:
        return []
    found = _read(book.reads.other_work())
    book.learn(found)
    return _kept(
        book.row(a, book.staff.get(a.responsible_staff_id), channel="Staff")
        for a in found
    )


def _of_kind(queryset, book: _Book, meetings: bool | None):
    if meetings is True:
        return queryset.filter(activity_type__in=book.meeting_types)
    if meetings is False:
        return queryset.exclude(activity_type__in=book.meeting_types)
    return queryset


def _session_rows(book: _Book, *, meetings: bool | None = None) -> list:
    """Staff cluster sessions: ``meetings`` True for cluster meetings only,
    False for cluster trainings only, None for both."""
    if not book.staff_side:
        return []
    found = _read(_of_kind(book.reads.sessions(), book, meetings))
    book.learn(found)
    rows = []
    for a in found:
        person = book.staff.get(a.responsible_staff_id)
        rows.append(
            book.row(
                a,
                person,
                channel="Staff",
                holder=book.staff.get(book.places.responsible(a.cluster_id)) or person,
            )
        )
    return _kept(rows)


def _partner_state(activity) -> dict:
    """What a Partner activity's row says of its date: the Partner's own, or
    that the Partner has not set one — whatever day staff entered."""
    if activity.partner_planned:
        return {"state": PARTNER_PLANNED, "staff_date": None}
    waiting = activity.status in _WAITING_STATES
    return {
        "state": AWAITING_PARTNER,
        # Delivered on a day staff chose: the day it happened is its date,
        # and it still is not the Partner's plan.
        "date": None if waiting else activity.on,
        "staff_date": activity.on,
        **({"status": ASSIGNED} if waiting else {}),
    }


def _partner_session_rows(book: _Book, *, meetings: bool | None = None) -> list:
    """Cluster trainings and meetings a Partner delivers."""
    if not book.partner_side:
        return []
    found = _read(_of_kind(book.reads.partner_sessions(), book, meetings))
    book.learn(found)
    rows = []
    for a in found:
        responsible = book.staff.get(book.places.responsible(a.cluster_id))
        person = (
            book.staff.get(a.monitored_by_staff_id, a.responsible_staff_id)
            or responsible
        )
        row = book.row(a, person, channel="Partner", holder=responsible or person)
        if row is None:
            continue
        row.update(_partner_state(a))
        row["assigned_by"] = row["staff"]
        row["by_name"] = row["partner"] or "Unrecorded Partner"
        rows.append(row)
    return rows


def _partner_rows(book: _Book, *, every: bool = False) -> list:
    """Every piece of work in a Partner's hands, under who assigned it.

    A school handed to a Partner for data collection is assigned to that
    Partner like any other and reads SSA Support (owner, 2026-10-02: "it
    should show SSA support"); the work is marked as not counted, because it
    is no visit of the school's. ``every`` adds the work the rulebook does
    not count at all — Alumni, a project no SSA intervention measures — for
    the list of every activity."""
    from apps.planning.partner_oversight_service import describe_work

    if not book.partner_side:
        return []
    reads = book.reads
    handovers = list(
        reads.handovers(every=every).select_related(
            "school",
            "training_course",
            "catalogue_item",
            "source_activity__training_course",
        )
    )
    work = _read(reads.partner_work(every=every))
    book.learn(
        work,
        staff_ids={
            i
            for h in handovers
            for i in (
                h.monitoring_staff_id,
                h.assigning_staff_id,
                h.school.account_owner_id if h.school_id else None,
            )
        },
        partner_ids={h.partner_id for h in handovers},
        project_ids={h.project_id for h in handovers},
    )
    rows = []
    handed_by: dict[str, tuple] = {}
    carried: set[str] = set()
    for h in handovers:
        origin = (h.monitoring_staff_id, h.assigning_staff_id, h.created_at)
        if h.scheduled_activity_id:
            handed_by[h.scheduled_activity_id] = origin
            continue
        if not reads.waiting(h.status, h.created_at):
            continue
        if h.source_activity_id:
            carried.add(h.source_activity_id)
            handed_by[h.source_activity_id] = origin
        if not reads.reads_handovers or h.school_id is None:
            continue
        person = book.staff.get(
            h.monitoring_staff_id, h.assigning_staff_id, h.school.account_owner_id
        )
        place = book.places.of_school(h.school)
        if not book.keeps(person, place, h.project_id):
            continue
        school_type = h.school.school_type or ""
        is_visit = (
            handover_kind(
                school_type,
                _Handover(
                    h.support_type,
                    h.visit_number,
                    h.training_number,
                    h.project_id,
                    h.expected_activity_type,
                    h.purpose_of_visit,
                ),
            )
            == "visit"
        )
        expected = h.expected_activity_type or ""
        kind = rules.visit_kind(expected or "school_visit", h.purpose_of_visit)
        data_collection = rules.is_data_collection(expected, h.purpose_of_visit)
        course, purpose, intervention = describe_work(
            purpose_code=h.purpose_of_visit or "",
            activity_type=expected,
            course=h.training_course,
            catalogue_item=h.catalogue_item,
            source_activity=h.source_activity,
            focus=h.focus_intervention or "",
        )
        lead, who, role = _who(person)
        partner = book.partners.get(h.partner_id) or "Unrecorded Partner"
        rows.append(
            {
                **place,
                "planner_lead": lead,
                "lead": place["holder_lead"],
                "staff": who,
                "role": role,
                "channel": "Partner",
                "by_name": partner,
                "partner": partner,
                "assigned_by": who,
                "activity": (
                    DATA_COLLECTION
                    if data_collection
                    else rules.KIND_LABELS.get(kind, "Visit")
                    if is_visit
                    else (book.type_label(expected) or "Training")
                ),
                "course": course,
                "purpose": purpose,
                "intervention": intervention,
                "is_training": not is_visit and not data_collection,
                "is_visit": is_visit,
                "assigned_on": _local(h.created_at),
                "date": None,
                "staff_date": None,
                "state": AWAITING_PARTNER,
                "status": ASSIGNED,
                "counted": "No" if data_collection else "",
                "project": book.projects.get(h.project_id, ""),
                "_project": h.project_id or "",
                "facilitator": "",
                "monitor": who if h.monitoring_staff_id else "",
                "quarter": "",
                "participants": "",
                "cost": 0,
                "salesforce": "",
                "evidence": "",
                "ia": "",
                "payment": "",
                "rescheduled": 0,
                "recorded": _local(h.created_at),
            }
        )
    for a in work:
        if a.id in carried:
            continue  # listed once, as the hand-over that carries it
        origin = handed_by.get(a.id, ())
        person = book.staff.get(
            *origin[:2],
            a.monitored_by_staff_id,
            a.responsible_staff_id,
            a.school.account_owner_id,
        )
        kind = rules.visit_kind(a.activity_type, a.purpose_type)
        data_collection = rules.is_data_collection(a.activity_type, a.purpose_type)
        label = DATA_COLLECTION if data_collection else rules.KIND_LABELS.get(kind, "")
        row = book.row(
            a,
            person,
            channel="Partner",
            label=label,
            counted="No" if data_collection else "",
        )
        if row is None:
            continue
        row.update(_partner_state(a))
        row["partner"] = row["partner"] or "Unrecorded Partner"
        row["by_name"] = row["partner"]
        row["assigned_by"] = row["staff"]
        row["assigned_on"] = _local(origin[2] if origin else a.created_at)
        rows.append(row)
    return rows


def _cluster_rows(book: _Book) -> list:
    reads, staff, places = book.reads, book.staff, book.places
    if reads.schools is None:
        return []
    from apps.clusters.models import Cluster

    active = set(Cluster.objects.filter(status="active").values_list("id", flat=True))
    found = list(
        reads.schools.filter(cluster_id__in=active).values_list(
            "school_id", "name", "school_type", "cluster_id", "account_owner_id"
        )
    )
    staff.learn(places.responsible(cluster_id) for cluster_id in active)
    staff.learn(row[4] for row in found)
    rows = []
    for code, name, school_type, cluster_id, holder in found:
        # The CCEO responsible for the cluster; the school's own holder where
        # the cluster names nobody.
        person = staff.get(places.responsible(cluster_id), holder)
        place = places.of_cluster(cluster_id, person)
        if not book.keeps(person, place, None):
            continue
        rows.append(
            {
                "lead": place["holder_lead"],
                "sub_region": place["sub_region"],
                "district": place["district"],
                "holder": place["holder"] if person is not None else "Nobody recorded",
                "cluster": place["cluster"],
                "school_id": code or "",
                "school": name or "",
                "type": rules.type_label(school_type),
            }
        )
    return rows


# ── School tables (the page's own dataset) ───────────────────────────────────
def _project_schools(project_id: str) -> set | None:
    """The schools enrolled in a project, for a table narrowed to one."""
    if not project_id:
        return None
    from apps.projects.models import ProjectSchoolAssignment

    return set(
        ProjectSchoolAssignment.objects.filter(project_id=project_id).values_list(
            "school_id", flat=True
        )
    )


def _school_rows(user, filters, wanted, extra: Extra | None = None) -> list:
    """Schools the page's selection keeps for which ``wanted(school, vector)``
    holds, under whoever holds each."""
    extra = extra or Extra()
    places = _Places(user, filters)
    dataset = places.dataset
    enrolled = _project_schools(extra.project)
    rows = []
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
        if enrolled is not None and school.id not in enrolled:
            continue
        if not wanted(school, values):
            continue
        place = places.of_record(school)
        if extra.sub_region and place["_sub_region"] != extra.sub_region:
            continue
        if extra.cluster and place["_cluster"] != extra.cluster:
            continue
        partners = sorted(
            dataset.partner_names.get(pid, "Unrecorded Partner")
            for pid in (school.partners or {})
        )
        visits = values[IDX["cum_staff"]] + values[IDX["cum_partner_scheduled"]]
        rows.append(
            {
                **place,
                "lead": place["holder_lead"],
                "staff": place["holder"],
                "visits_needed": values[IDX["visit_slots"]],
                "expected_from": _expected_from(
                    values[IDX["staff_expected"]], values[IDX["partner_expected"]]
                ),
                "visits_planned": visits,
                "visits_remaining": max(0, values[IDX["visit_slots"]] - visits),
                "trainings_needed": values[IDX["training_slots"]],
                "trainings_planned": values[IDX["cum_training"]],
                "trainings_remaining": values[IDX["training_gap"]],
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
                "_record": school,
            }
        )
    return places.sort(rows, "school")


def _expected_from(staff: int, partner: int) -> str:
    """Who a school's visits are expected from, in the page's words. No
    Partner is named: any Partner may take the work."""
    if staff and partner:
        return f"Staff {staff} · Partner {partner}"
    if partner:
        return "Partner"
    return "Staff" if staff else ""


# ── The tables ───────────────────────────────────────────────────────────────
SCHOOL_TABLES = {
    "not-planned": "unplanned",
    "partly-planned": "partially_planned",
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


def _balance(planned: int, expected: int) -> str:
    """ "6 of 560 · 554 to plan" — a plan against its target."""
    if not expected:
        return "no target"
    return f"{planned:,} of {expected:,} · {max(0, expected - planned):,} to plan"


def _partner_balance(rows: list) -> str:
    dated = sum(1 for row in rows if row["state"] == PARTNER_PLANNED)
    return (
        f"{dated:,} of {len(rows):,} planned by the Partner · "
        f"{len(rows) - dated:,} awaiting partner schedule"
    )


def _duplicate_table(user, filters, table: Table, extra: Extra) -> Table:
    """Every plan at every school planned twice: one school, N plans."""
    from dataclasses import replace

    from apps.core.scoping import resolve_user_scope

    schools = {}
    for row in _school_rows(
        user, filters, lambda school, values: values[IDX["duplicates"]], extra
    ):
        schools[row["school_id"]] = row
    if not schools:
        table.summary = "No school is planned twice"
        return table

    # Every plan at those schools, whoever made it: the page's Lead and CCEO
    # choice picked the SCHOOLS (by who holds them), not the planners.
    everyone = replace(filters, program_lead="", cceo="")
    reads = people.Reads(
        None,
        filters.fy,
        window=svc._people_window(filters.window),
        scope=resolve_user_scope(user),
        narrow=people.Narrow(
            school_ids=tuple(row["_record"].id for row in schools.values())
        ),
    )
    book = _Book(user, everyone, reads=reads)
    plans = _visit_rows(book) + [row for row in _partner_rows(book) if row["is_visit"]]
    rows = []
    for plan in plans:
        school = schools.get(plan["school_id"])
        if school is None:
            continue
        responsible = plan["staff"]
        if plan["channel"] == "Partner":
            responsible = f"{plan['partner']} (assigned by {plan['staff']})"
        rows.append({**plan, "why": school["why"], "staff": responsible})
    # A school's plans stay together, earliest first.
    table.rows = book.places.sort(rows, "school", "school_id", "date")
    count = len({row["school_id"] for row in rows})
    table.summary = (
        f"{count:,} school{'' if count == 1 else 's'} planned twice · "
        f"{_count_line(len(rows), 'plan')} between them"
    )
    return table


def _project_table(user, filters, table: Table, extra: Extra) -> Table:
    """Every enrolment in a live project, from the coordinators' own records
    (apps.projects.monitoring), under where its school sits."""
    from apps.projects import monitoring

    places = _Places(user, filters)
    dataset = places.dataset
    rows = []
    for project, coordinator, school in monitoring.enrolled_schools(
        user, fy=filters.fy
    ):
        if extra.project and project.id != extra.project:
            continue
        record = dataset.facts.get(school.school_pk)
        if record is None:
            continue  # outside this reader's schools
        owner = dataset.owners.get(record.owner_key)
        if not svc._keeps(record, owner, filters):
            continue
        place = places.of_record(record)
        if extra.sub_region and place["_sub_region"] != extra.sub_region:
            continue
        if extra.cluster and place["_cluster"] != extra.cluster:
            continue
        with_partner = bool(school.partner_name)
        note = ""
        if school.awaiting_date:
            note = AWAITING_PARTNER
        elif school.status_key == monitoring.STATUS_AWAITING_COORDINATOR:
            note = AWAITING_COORDINATOR
        rows.append(
            {
                **place,
                "lead": place["holder_lead"],
                "project": project.name,
                "activity": school.training_name
                or (school.purpose_label if school.is_planned else ""),
                "purpose": school.purpose_label,
                "intervention": school.intervention_label,
                "coordinator": coordinator,
                "added_by": "" if school.added_by == "—" else school.added_by,
                "channel": "Partner"
                if with_partner
                else ("Staff" if school.is_planned else ""),
                "by_name": school.partner_name or school.planned_by,
                "date": None if note else school.activity_date,
                "date_note": note,
                "status": school.status_label,
                "enrolled_on": school.enrolled_on,
                "planned_n": school.planned,
                "delivered_n": school.delivered,
                "verified_n": school.verified,
                "last_delivered": school.last_delivered_on,
                "movement": school.impact_label,
                "_planned": school.is_planned,
            }
        )
    table.rows = places.sort(rows, "project", "school")
    planned = sum(1 for row in rows if row["_planned"])
    projects = len({row["project"] for row in rows})
    table.summary = (
        f"{_count_line(len(rows), table.spec.unit)} in {projects:,} "
        f"project{'' if projects == 1 else 's'} · {planned:,} planned · "
        f"{len(rows) - planned:,} awaiting a plan"
    )
    return table


def build(user, filters, key: str, extra: Extra | None = None) -> Table:
    """The whole table for the page's selection, sorted, unpaged."""
    spec = SPECS[key]
    extra = extra or Extra()
    table = Table(spec=spec)
    if key == "duplicates":
        return _duplicate_table(user, filters, table, extra)
    if key == "projects":
        return _project_table(user, filters, table, extra)
    if key in SCHOOL_TABLES:
        index = IDX[SCHOOL_TABLES[key]]
        rows = _school_rows(user, filters, lambda school, values: values[index], extra)
        for row in rows:
            row.pop("_record")
        table.rows = rows
        table.summary = _count_line(len(rows), spec.unit)
        if key == "partly-planned":
            remaining = sum(row["visits_remaining"] for row in rows)
            table.summary += f" · {remaining:,} visits still to plan"
        return table

    book = _Book(user, filters, extra)
    places = book.places
    twice = _twice_codes(user, filters)
    if key == "visits":
        rows = _flag(_visit_rows(book), twice)
        table.rows = places.sort(rows, "date", "school")
        target = svc.snapshot_for(user, filters).tree.country.target
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} planned · "
            f"{_balance(len(rows), target)}"
        )
    elif key == "all-visits":
        rows = _flag(
            _visit_rows(book)
            + _outreach_rows(book)
            + [
                row
                for row in _partner_rows(book)
                if (row["is_visit"] or not row["is_training"])
                and row["state"] == PARTNER_PLANNED
            ],
            twice,
        )
        table.rows = places.sort(rows, "date", "school")
        by_staff = sum(1 for row in rows if row["channel"] == "Staff")
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} planned · {by_staff:,} by staff · "
            f"{len(rows) - by_staff:,} by Partners"
        )
    elif key == "partners":
        rows = _flag(_partner_rows(book), twice)
        table.rows = places.sort(rows, "partner", "school", "date")
        schools = len({row["school_id"] for row in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} at {schools:,} "
            f"school{'' if schools == 1 else 's'} · {_partner_balance(rows)}"
        )
    elif key == "project-partners":
        # Every project's, whether the rulebook counts its work or not:
        # Alumni's are a coordinator's assignments too.
        rows = [row for row in _partner_rows(book, every=True) if row["_project"]]
        table.rows = places.sort(rows, "project", "partner", "school", "date")
        schools = len({row["school_id"] for row in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} at {schools:,} "
            f"school{'' if schools == 1 else 's'} · {_partner_balance(rows)}"
        )
    elif key == "project-activities":
        rows = [
            row
            for row in (
                _visit_rows(book)
                + _outreach_rows(book)
                + _training_rows(book, skip_counted_visits=True)
                + _other_rows(book)
                + _session_rows(book)
                + [
                    row
                    for row in _partner_rows(book, every=True)
                    + _partner_session_rows(book)
                    if row["state"] == PARTNER_PLANNED
                ]
            )
            if row["_project"]
        ]
        table.rows = places.sort(rows, "project", "date", "school", "activity")
        by_staff = sum(1 for row in rows if row["channel"] == "Staff")
        projects = len({row["_project"] for row in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} in {projects:,} "
            f"project{'' if projects == 1 else 's'} · {by_staff:,} by staff · "
            f"{len(rows) - by_staff:,} by Partners"
        )
    elif key == "plans":
        rows = _flag(
            _visit_rows(book)
            + _outreach_rows(book)
            + _training_rows(book, skip_counted_visits=True)
            + _other_rows(book)
            + _session_rows(book)
            # Listed, counted nowhere: Alumni work in a Partner's hands too.
            + _partner_rows(book, every=True)
            + _partner_session_rows(book),
            twice,
        )
        table.rows = places.sort(rows, "date", "school", "activity")
        by_staff = sum(1 for row in rows if row["channel"] == "Staff")
        table.summary = (
            f"{_count_line(len(rows), 'activity')} · {by_staff:,} by staff · "
            f"{len(rows) - by_staff:,} with Partners"
        )
    elif key == "trainings":
        rows = (
            _training_rows(book)
            + _session_rows(book, meetings=False)
            + [row for row in _partner_rows(book) if row["is_training"]]
            + _partner_session_rows(book, meetings=False)
        )
        table.rows = places.sort(rows, "date", "school")
        table.summary = _count_line(len(rows), spec.unit) + " planned"
    elif key == "clusters":
        rows = _cluster_rows(book)
        table.rows = places.sort(rows, "school")
        clusters = len({(r["district"], r["cluster"]) for r in rows})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} in {clusters:,} "
            f"cluster{'' if clusters == 1 else 's'}"
        )
    elif key == "meetings":
        rows = _session_rows(book, meetings=True)
        table.rows = places.sort(rows, "date")
        invited = sum(row["invited"] for row in rows)
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} planned · {invited:,} school "
            f"invitation{'' if invited == 1 else 's'}"
        )
    return table


def _count_line(count: int, unit: str) -> str:
    plural = f"{unit[:-1]}ies" if unit.endswith("y") else f"{unit}s"
    return f"{count:,} {unit if count == 1 else plural}"


def page_of(table: Table, page: int) -> dict:
    """One page of a table: the shared pager, and each row's cells in the
    order of the columns the page shows."""
    from apps.core.pagination import paginate_rows

    pager = paginate_rows(table.rows, page=page, page_size=ROWS_PER_PAGE)
    shown = table.shown_columns
    return {
        "pager": pager,
        "columns": shown,
        "lines": [
            {
                "cells": [
                    (column, row.get(column.key), _blank(column, row))
                    for column in shown
                ],
                "school_id": row.get("school_id") or "",
            }
            for row in pager["rows"]
        ],
    }


def _blank(column: Column, row: dict) -> str:
    """What a date column says for a row with no date."""
    if not column.is_date:
        return ""
    return row.get(f"{column.key}_note") or column.blank


def sheet(table: Table) -> dict:
    """The whole table as one workbook sheet: every column, details included."""
    columns = table.spec.columns

    def cell(row, column):
        value = row.get(column.key)
        if value is None:
            return _blank(column, row)
        return value

    return {
        "title": table.spec.title,
        "headers": [column.label for column in columns],
        "number_formats": {
            index: "d mmm yyyy"
            for index, column in enumerate(columns, start=1)
            if column.is_date
        },
        "rows": [[cell(row, column) for column in columns] for row in table.rows],
    }


# ── What a table can be narrowed to ──────────────────────────────────────────
def filter_options(user, filters) -> dict:
    """The sub-regions, districts, people, Partners, clusters and projects a
    table can be narrowed to: the ones the reader's own schools name."""
    from apps.clusters.models import Cluster
    from apps.partners.models import Partner
    from apps.projects import monitoring

    places = _Places(user, filters)
    dataset = places.dataset
    district_ids = {school.district_id for school in dataset.facts.values()}
    district_ids.discard(None)
    districts = sorted(
        (
            (pk, places.districts[pk][0], places.districts[pk][1])
            for pk in district_ids
            if pk in places.districts
        ),
        key=lambda item: item[1].casefold(),
    )
    sub_regions = sorted(
        {
            (places.districts[pk][1], places.districts[pk][2])
            for pk in district_ids
            if pk in places.districts and places.districts[pk][1]
        },
        key=lambda item: item[1].casefold(),
    )
    clusters = Cluster.objects.filter(status="active", district_id__in=district_ids)
    if filters.district:
        clusters = clusters.filter(district_id=filters.district)
    return {
        "sub_regions": [{"key": pk, "name": name} for pk, name in sub_regions],
        "districts": [{"key": pk, "name": name} for pk, name, _sub in districts],
        "holders": sorted(
            (
                {"key": owner.key, "name": owner.name}
                for owner in dataset.owners.values()
                if owner.kind != "unassigned"
            ),
            key=lambda option: option["name"].casefold(),
        ),
        "partners": [
            {"key": pk, "name": name}
            for pk, name in Partner.objects.order_by("name").values_list("id", "name")
        ],
        "clusters": [
            {"key": pk, "name": f"{name} · {district}" if district else name}
            for pk, name, district in clusters.order_by("name").values_list(
                "id", "name", "district__name"
            )
        ],
        "projects": [
            {"key": project.id, "name": project.name}
            for project in monitoring.watched_projects(user)
        ],
    }
