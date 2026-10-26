"""My Plan's tables as an export, a sheet each (owner, 2026-10-26).

"If the IA select all then it should group those activities in different
sheets in the excel exported sheet not everything in one table ... tables are
exported exactly the way they are in My Plan tables. I REPEAT the export should
be exact no inventing new columns or removing columns."

The rows are My Plan's own: ``get_frontend_context`` draws its tables from the
activities an export chose, by the rules it draws the reader's plan by. The
columns are each table's headings in the page's order (the Actions column and
the switched-off Evidence column are not data), and each cell is what the
page's template writes in it: the same fallbacks ("—", "Unscheduled", "Not in
SF") and the same words joined into one cell. A date is a date and a cost a
number, formatted as the page shows them, so a reader can sort and add them.
The guard is ``apps.frontend.test_export_my_plan_tables``: the headings are
read from the templates, and every row the page draws is found in the export.

One sheet is not a My Plan table: the schools invited to each cluster meeting,
one row a school, in the Trainings table's columns (asked, the owner chose
it, 2026-10-26). The page lists a meeting once, under its cluster.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.core import export_kinds

#: How the page writes a date: "5 Oct 2026", and on the Core School
#: Trainings and Programme Activities tables "Oct 5, Mon".
DAY = "d mmm yyyy"
SHORT_DAY = "mmm d, ddd"
#: "UGX 40,000".
MONEY = '"UGX "#,##0'
DASH = "—"


# ── What a template writes ────────────────────────────────────────────────────
def _or(value, fallback=DASH):
    """``{{ value|default:fallback }}``."""
    return value if value not in (None, "", 0, False) else fallback


def _plain(value) -> str:
    """``{{ value }}``: Django writes None as "None"."""
    return "None" if value is None else str(value)


def _joined(*parts) -> str:
    """Words a cell writes one after another, as the page reads them."""
    return " ".join(str(p) for p in parts if p not in (None, ""))


def _day(value):
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value


def _planned(row, unset="Unscheduled"):
    return _day(row.get("planned_before") or row.get("planned_date")) or unset


def _completed(row):
    return _day(row.get("completed_on")) or DASH


def _intervention(row):
    value = row.get("focus_intervention")
    return value if value and value != DASH else DASH


def _cost(row, *, note=True):
    amount = row.get("budget_total") or 0
    if note and row.get("cost_note"):
        return f"UGX {amount:,} {row['cost_note']}"
    return amount


def _salesforce(row):
    return row.get("salesforce_id") or "Not in SF"


def _school_name(row):
    return _or(row.get("school_name"))


def _real_school(row) -> str:
    name = row.get("school_name")
    return name if name and name != "Unknown School" else ""


def _school_or_cluster(row):
    """The Trainings table's School / Cluster cell."""
    if row.get("place_url"):
        return _real_school(row) or row.get("cluster_name") or row.get("school_id")
    if row.get("school_id"):
        return _real_school(row) or row["school_id"]
    return _real_school(row) or row.get("cluster_name") or DASH


def _planned_from(row):
    """The Trainings table's Cluster Planned From cell."""
    if row.get("is_cluster_invited"):
        return _joined(row.get("cluster_name") or DASH, "Invited")
    if row.get("delivery_type") == "in-school" or "in_school" in (
        row.get("activity_type") or ""
    ):
        return "School Visit"
    return row.get("cluster_name") or DASH


def _meeting_topic(row):
    """The Cluster Meetings table's Purpose (Meeting Topic) cell."""
    if row.get("meeting_kind"):
        text = row["meeting_kind"]
        if row.get("meeting_training"):
            text += f": {row['meeting_training']}"
        purpose = row.get("purpose")
        if purpose and purpose != row.get("activity_type_label"):
            text += f" · {purpose}"
        return text
    return row.get("purpose") or "Cluster Meeting"


def _core_activity(row):
    label = row.get("activity_type_label") or "Core Visit"
    if not row.get("visit_number"):
        return label
    return _joined(label, row["visit_number"], row.get("core_progress"))


def _core_district(row):
    district = row.get("school_district")
    return district if district and district != DASH else DASH


_BUDGET: tuple = (
    ("Budget status", lambda r: _or(r.get("budget_status"))),
    ("Verification", lambda r: _or(r.get("verification_status"))),
    ("Salesforce ID", _salesforce),
    ("Status", lambda r: _or(r.get("status_label"))),
)


@dataclass(frozen=True)
class Table:
    key: str  # the context list it is drawn from
    title: str  # the sheet: the table's own heading
    template: str  # partials/my_plan/<template>.html
    columns: tuple  # (heading, cell)
    short_days: bool = False


SCHOOL_VISITS = Table(
    "school_visits",
    "School Visits",
    "school_visits",
    (
        ("School ID", lambda r: _or(r.get("school_id"))),
        ("School Name", _school_name),
        ("District", lambda r: _or(r.get("district"))),
        ("District Type", lambda r: _or(r.get("district_type"))),
        ("Activity", lambda r: _or(r.get("activity_type_label"), "School Visit")),
        ("Planned Date", _planned),
        ("Completed Date", _completed),
        ("Executor", lambda r: _or(r.get("owner"), "Staff")),
        ("Purpose of Visit", lambda r: _or(r.get("purpose"))),
        ("Focus Intervention", _intervention),
        ("Cost", _cost),
        *_BUDGET,
    ),
)
TRAININGS_COLUMNS = (
    ("School ID", lambda r: _or(r.get("school_id"))),
    ("School / Cluster", _school_or_cluster),
    ("District", lambda r: _or(r.get("district"))),
    ("District Type", lambda r: _or(r.get("district_type"))),
    ("Cluster Planned From", _planned_from),
    ("Executor", lambda r: _or(r.get("owner"), "Staff")),
    ("Training Name", lambda r: r.get("training_name") or "Not yet named"),
    ("Planned Date", _planned),
    ("Completed Date", _completed),
    ("SSA Intervention", _intervention),
    ("Participants", lambda r: _or(r.get("expected_participants"))),
    ("Mode of Delivery", lambda r: _or(r.get("training_mode"))),
    ("Cost", _cost),
    *_BUDGET,
)
TRAININGS = Table(
    "cluster_trainings", "Trainings", "cluster_trainings", TRAININGS_COLUMNS
)
GROUP_TRAININGS = Table(
    "group_trainings",
    "Group Trainings",
    "group_trainings",
    (
        ("Cluster Name", lambda r: _plain(r.get("cluster_name"))),
        ("District", lambda r: _or(r.get("cluster_district"))),
        ("District Type", lambda r: _or(r.get("district_type"))),
        ("Planned Date", _planned),
        ("Completed Date", _completed),
        ("Executor", lambda r: _or(r.get("owner"), "Staff")),
        (
            "Training",
            lambda r: r.get("training_name")
            or r.get("activity_name")
            or r.get("purpose")
            or "Group Training",
        ),
        ("SSA Intervention", _intervention),
        ("Participants", lambda r: _or(r.get("expected_participants"))),
        ("Cost", lambda r: _cost(r, note=False)),
        *_BUDGET,
    ),
)
CLUSTER_MEETINGS = Table(
    "cluster_meetings",
    "Cluster Meetings",
    "cluster_meetings",
    (
        ("Cluster Name", lambda r: _plain(r.get("cluster_name"))),
        ("District", lambda r: _or(r.get("cluster_district"))),
        ("District Type", lambda r: _or(r.get("district_type"))),
        ("Planned Date", _planned),
        ("Completed Date", _completed),
        ("Executor", lambda r: _or(r.get("owner"), "Staff")),
        ("Purpose (Meeting Topic)", _meeting_topic),
        ("SSA Intervention", _intervention),
        ("Participants", lambda r: _or(r.get("expected_participants"))),
        ("Cost", lambda r: _cost(r, note=False)),
        *_BUDGET,
    ),
)
CORE_SCHOOL_VISITS = Table(
    "core_school_visits",
    "Core School Visits",
    "core_school_visits",
    (
        ("School ID", lambda r: _or(r.get("school_id"))),
        ("School Name", _school_name),
        ("District", lambda r: _or(r.get("school_district"))),
        ("District Type", lambda r: _or(r.get("district_type"))),
        ("Activity", _core_activity),
        ("Planned Date", _planned),
        ("Completed Date", _completed),
        ("Executor", lambda r: _or(r.get("owner"), "Staff")),
        ("Purpose of Visit", lambda r: _or(r.get("purpose"))),
        ("SSA Intervention", _intervention),
        ("Cost", _cost),
        *_BUDGET,
    ),
)
CORE_SCHOOL_TRAININGS = Table(
    "core_school_trainings",
    "Core School Trainings",
    "core_school_trainings",
    (
        ("School ID", lambda r: _or(r.get("school_id"))),
        (
            "School Name",
            lambda r: _joined(_school_name(r), r.get("activity_type_label")),
        ),
        (
            "Package",
            lambda r: _joined(r.get("training_number") or DASH, r.get("core_progress")),
        ),
        ("Training", lambda r: r.get("training_name") or "Not yet named"),
        ("District", _core_district),
        ("District Type", lambda r: _or(r.get("district_type"))),
        ("Planned Date", _planned),
        ("Completed Date", _completed),
        ("Focus Intervention", lambda r: _plain(r.get("focus_intervention"))),
        ("Expected Participants", lambda r: _or(r.get("expected_participants"))),
        ("Assigned Partner", lambda r: _plain(r.get("owner"))),
        *_BUDGET,
    ),
    short_days=True,
)
PROGRAMME_COLUMNS = (
    ("School ID", lambda r: _plain(r.get("school_id"))),
    ("School name", lambda r: _plain(r.get("school_name"))),
    ("District", lambda r: _or(r.get("district"))),
    ("District Type", lambda r: _or(r.get("district_type"))),
    ("Activity", lambda r: _plain(r.get("activity_type_label"))),
    ("Planned date", lambda r: _planned(r, "Awaiting schedule")),
    ("Completed date", _completed),
    ("Salesforce ID", _salesforce),
    ("Status", lambda r: _plain(r.get("status_label"))),
)
PROGRAMME_ACTIVITIES = Table(
    "programme_activities",
    "Programme Activities",
    "programme_activities",
    (
        ("Venue ID", lambda r: _or(r.get("school_id"))),
        (
            "School / Venue Name",
            lambda r: _school_name(r)
            if r.get("school_id")
            else (r.get("venue_name") or DASH),
        ),
        ("District", lambda r: _or(r.get("district"))),
        ("District Type", lambda r: _or(r.get("district_type"))),
        (
            "Activity",
            lambda r: r.get("activity_type_label") or r.get("purpose") or DASH,
        ),
        ("Date", lambda r: _day(r.get("planned_date")) or "Unscheduled"),
        *_BUDGET,
    ),
    short_days=True,
)

#: My Plan's tables, in the page's order (partials/my_plan/workspace.html).
TABLES = (
    SCHOOL_VISITS,
    TRAININGS,
    GROUP_TRAININGS,
    CLUSTER_MEETINGS,
    CORE_SCHOOL_VISITS,
    CORE_SCHOOL_TRAININGS,
    PROGRAMME_ACTIVITIES,
)
MEETING_SCHOOLS_TITLE = "Schools in Cluster Meetings"
#: The programme-school cards are one table a school type, as on the page;
#: Excel names a sheet in 31 characters, so each is "<type> School Plans",
#: the name the page gives the table itself.
PROGRAMME_TITLE = "{label} School Plans"

#: "All": every table, a sheet each, in the page's order.
ALL_SHEETS = (
    "school_visits",
    "cluster_trainings",
    "group_trainings",
    "cluster_meetings",
    "meeting_schools",
    "core_school_visits",
    "core_school_trainings",
    "programme_school_work",
    "programme_activities",
)
_TITLES = {table.key: table.title for table in TABLES}
_TITLES["meeting_schools"] = MEETING_SCHOOLS_TITLE
#: The sheets "All" always holds (the programme cards only when they have
#: rows, as on the page).
FIXED_TITLES = tuple(_TITLES[key] for key in ALL_SHEETS if key in _TITLES)

#: The tables each Activity Type gives.
KIND_TABLES = {
    export_kinds.ALL: ALL_SHEETS,
    export_kinds.PLANNED: tuple(k for k in ALL_SHEETS if k != "programme_activities"),
    export_kinds.VISITS_TRAININGS: (
        "school_visits",
        "cluster_trainings",
        "group_trainings",
        "core_school_visits",
        "core_school_trainings",
        "programme_school_work",
    ),
    export_kinds.VISITS: (
        "school_visits",
        "core_school_visits",
        "programme_school_work",
    ),
    export_kinds.GROUP_TRAININGS: (
        "cluster_trainings",
        "group_trainings",
        "core_school_trainings",
    ),
    export_kinds.TRAININGS: (
        "cluster_trainings",
        "group_trainings",
        "core_school_trainings",
        "programme_school_work",
    ),
    export_kinds.MEETINGS: ("cluster_meetings", "meeting_schools"),
    export_kinds.ONLINE: (
        "cluster_trainings",
        "group_trainings",
        "core_school_trainings",
    ),
    export_kinds.TRAINING_SCHOOLS: ("cluster_trainings",),
    export_kinds.MEETING_SCHOOLS: ("meeting_schools",),
    export_kinds.CORE_VISITS: ("core_school_visits",),
    export_kinds.CLIENT_VISITS: ("school_visits",),
    export_kinds.CORE_TRAININGS: ("core_school_trainings",),
}


# ── The rows ──────────────────────────────────────────────────────────────────
def context_for(principal, activity_ids, fy) -> dict:
    """My Plan's tables for exactly these activities."""
    from apps.activities.models import Activity
    from apps.core.scoping import id_list
    from apps.my_plan.services import get_frontend_context

    # One array parameter, not a placeholder per id: a country's export
    # chose 23,000 activities, and every statement My Plan reads through
    # this queryset carried all of them.
    chosen = Activity.objects.filter(
        id__in=id_list(i for i in set(activity_ids) if i), deleted_at__isnull=True
    )
    return get_frontend_context(
        principal,
        {"fy": str(fy), "period": "fy"},
        with_readiness=False,
        activities=chosen,
    )


def _sheet(title: str, columns, rows, *, short_days: bool = False) -> dict:
    day = SHORT_DAY if short_days else DAY
    formats = {}
    for index, (heading, _cell) in enumerate(columns, start=1):
        if heading.lower().endswith("date"):
            formats[index] = day
        elif heading == "Cost":
            formats[index] = MONEY
    return {
        "title": title,
        "headers": [heading for heading, _cell in columns],
        "rows": [[cell(row) for _heading, cell in columns] for row in rows],
        "number_formats": formats,
    }


def _rosters(ids: list, meetings: list[dict]) -> tuple[dict, dict, dict, set]:
    """Who each meeting invited, by name; the people an invitation names;
    and, for a meeting with no invitation recorded, its cluster's schools."""
    from collections import defaultdict

    from apps.activities.models import ClusterActivityAttendance
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    recorded = set(
        ClusterActivityAttendance.objects.filter(activity_id__in=ids).values_list(
            "activity_id", flat=True
        )
    )
    on_roster: dict = defaultdict(list)
    people: dict = {}
    for act, school, teachers, leaders, other in (
        ClusterActivityAttendance.objects.filter(activity_id__in=ids, invited=True)
        .values_list("activity_id", "school_id", "teachers", "leaders", "other")
        .order_by("school__name")
    ):
        if school not in on_roster[act]:
            on_roster[act].append(school)
        if any(v is not None for v in (teachers, leaders, other)):
            people[(act, school)] = (teachers or 0) + (leaders or 0) + (other or 0)
    clusters = {row.get("cluster_id") for row in meetings if row.get("cluster_id")}
    members: dict = defaultdict(list)
    for school in School.objects.filter(
        cluster_id__in=clusters, deleted_at__isnull=True
    ).order_by("name"):
        confirmed = school.cluster_status == "clustered" and (
            not school.operational_status
            or school.operational_status in OPERATING_STATUSES
        )
        members[(school.cluster_id, confirmed)].append(school.id)
    by_cluster = {
        cluster: members.get((cluster, True)) or members.get((cluster, False), [])
        for cluster in clusters
    }
    rosters = {
        row["id"]: on_roster.get(row["id"])
        or ([] if row["id"] in recorded else by_cluster.get(row.get("cluster_id"), []))
        for row in meetings
    }
    return rosters, people, by_cluster, recorded


def meeting_school_rows(meetings: list[dict]) -> list[dict]:
    """Each cluster meeting once a school on its roster, as the Trainings
    table lists a group training: the schools invited, else, for a meeting
    scheduled before invitations were recorded by name, the cluster's
    confirmed member schools. A school's people are its invitation's when it
    names them, else the meeting's per school; its cost is those people at
    the meeting's meal rate."""
    from apps.activities.models import Activity
    from apps.budget.costing import CLUSTER_MEALS_RATE_KEY
    from apps.budget.costing_service import planned_meal_rates
    from apps.schools.models import School

    meetings = [row for row in meetings if row.get("id")]
    ids = [row["id"] for row in meetings]
    if not ids:
        return []
    rosters, people, _clusters, _recorded = _rosters(ids, meetings)
    schools = {
        s.id: s
        for s in School.objects.filter(
            id__in={pk for roster in rosters.values() for pk in roster}
        )
    }
    sessions = {a.id: a for a in Activity.objects.filter(id__in=ids)}
    rates = planned_meal_rates(list(sessions.values()), CLUSTER_MEALS_RATE_KEY)

    rows = []
    for row in meetings:
        act = row["id"]
        roster = rosters.get(act, [])
        session = sessions.get(act)
        each = (
            session.participants_per_school or session.teachers_per_school
            if session is not None
            else None
        )
        if not each and row.get("expected_participants") and roster:
            each = max(1, row["expected_participants"] // len(roster))
        rate = rates.get(act)
        for school_pk in roster:
            school = schools.get(school_pk)
            if school is None:
                continue
            heads = people.get((act, school_pk), each or None)
            rows.append(
                {
                    **row,
                    "school_id": school.school_id or str(school.id),
                    "school_name": school.name,
                    "place_url": f"/schools/{school.school_id or school.id}",
                    "is_cluster_invited": True,
                    "expected_participants": heads,
                    "budget_total": heads * rate
                    if heads is not None and rate is not None
                    else None,
                    "cost_note": "",
                    "training_mode": "Cluster Meeting",
                    "training_name": _meeting_topic(row),
                }
            )
    return rows


def _session_figures(rows: list[dict], kind: str) -> list[dict]:
    """A group training's people and Cost, as every export has written them
    since the owner set it (2026-10-15:
    "The Exported group training should export the actual number of
    participants (Number of schools x number of Participants) as planned. and
    it should reflect the actual (cost of participant * 12000)+venue Fee+
    Facilitation Fee"): ``plan_export.session_figures``, the one rule."""
    from apps.core import plan_export

    figures = plan_export.session_figures(
        [
            {
                "kind": kind,
                "activity_id": row.get("id"),
                "participants": row.get("expected_participants"),
                "cost": row.get("budget_total"),
            }
            for row in rows
        ]
    )
    return [
        {**row, "expected_participants": f["participants"], "budget_total": f["cost"]}
        for row, f in zip(rows, figures)
    ]


def sheets(context: dict, kind: str = export_kinds.ALL) -> list[dict]:
    """The sheets ``kind`` gives, from My Plan's ``context``, in the page's
    order. "All" holds every table, an empty one too, so a reader sees the
    whole plan's shape; a programme card is there only when it has rows, as
    on the page."""
    by_key = {table.key: table for table in TABLES}
    out = []
    for key in KIND_TABLES.get(kind, ALL_SHEETS):
        if key == "programme_school_work":
            out.extend(
                _sheet(
                    PROGRAMME_TITLE.format(label=section["label"]),
                    PROGRAMME_COLUMNS,
                    section["rows"],
                )
                for section in context.get("programme_school_work") or []
            )
        elif key == "meeting_schools":
            out.append(
                _sheet(
                    MEETING_SCHOOLS_TITLE,
                    TRAININGS_COLUMNS,
                    meeting_school_rows(context.get("cluster_meetings") or []),
                )
            )
        else:
            from apps.core import plan_export

            table = by_key[key]
            rows = context.get(table.key) or []
            if key == "group_trainings":
                rows = _session_figures(rows, plan_export.TRAINING)
            out.append(
                _sheet(table.title, table.columns, rows, short_days=table.short_days)
            )
    return out


def workbook(principal, activity_ids, fy, kind: str = export_kinds.ALL) -> list[dict]:
    """The sheets of My Plan's tables for these activities."""
    return sheets(context_for(principal, activity_ids, fy), kind)


def csv_rows(sheet_list: list[dict]):
    """The same sheets as one CSV: each sheet's name, its headings and its
    rows, a blank line between."""
    for sheet in sheet_list:
        yield [sheet["title"]]
        yield sheet["headers"]
        for row in sheet["rows"]:
            yield [
                f"{value.day} {value:%b %Y}" if isinstance(value, date) else value
                for value in row
            ]
        yield []


# ── Core School Oversight (owner, 2026-10-26) ─────────────────────────────────
# "Core schools oversight should have Core school Visits plans, Core schools
# with trainings planned Should have the following columns (School ID, School
# Name, Planned from (In-school Visit, Cluster Name), Executor (Staff Name or
# Partner Name), Training Name, SSA Intervention, Planned Date, Completed
# Date, Core Training Package (e.g. T1, T2, T3, T4), Participants, Delivery
# Type, Cost, Salesforce ID, Status)". The rows are My Plan's Core School
# Trainings rows; Delivery Type is "Group Training, Cluster Meeting, In-school
# and Online" (owner, asked). The visits are My Plan's Core School Visits table.
def _delivery_type(row) -> str:
    from apps.activities.training_names import ONLINE_TRAINING_LABEL
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    if row.get("training_mode") == ONLINE_TRAINING_LABEL:
        return "Online"
    if row.get("activity_type") in CLUSTER_MEETING_TYPES:
        return "Cluster Meeting"
    if row.get("is_cluster_invited") or (
        row.get("cluster_id") and not row.get("school_id")
    ):
        return "Group Training"
    return "In-school"


def _core_planned_from(row) -> str:
    if row.get("is_cluster_invited"):
        return row.get("cluster_name") or DASH
    return "In-school Visit"


CORE_TRAINING_PLAN_COLUMNS = (
    ("School ID", lambda r: _or(r.get("school_id"))),
    ("School Name", _school_name),
    ("Planned From", _core_planned_from),
    ("Executor", lambda r: _or(r.get("owner"), "Staff")),
    ("Training Name", lambda r: r.get("training_name") or "Not yet named"),
    ("SSA Intervention", _intervention),
    ("Planned Date", _planned),
    ("Completed Date", _completed),
    ("Core Training Package", lambda r: r.get("training_number") or DASH),
    ("Participants", lambda r: _or(r.get("expected_participants"))),
    ("Delivery Type", _delivery_type),
    ("Cost", lambda r: _cost(r, note=False)),
    ("Salesforce ID", _salesforce),
    ("Status", lambda r: _or(r.get("status_label"))),
)
CORE_VISITS_TITLE = "Core School Visits"
CORE_TRAININGS_TITLE = "Core School Trainings"


def core_school_activity_ids(school_pks, fy) -> list:
    """Every activity of ``fy`` planned for these schools: the work at each
    school, and the group sessions it is invited to (or that, scheduled
    before invitations were recorded by name, its cluster holds). Work set
    aside (cancelled, rejected, deferred, not planned, awaiting approval)
    is not a plan."""
    from django.db.models import Q

    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.core.activity_types import TRAINING_TYPES
    from apps.my_plan.services import ACTIVE_MY_PLAN_EXCLUDED_STATUSES
    from apps.schools.models import School

    pks = list(school_pks)
    aside = [s for s in ACTIVE_MY_PLAN_EXCLUDED_STATUSES if s != "closed"]
    live = Activity.objects.filter(fy=str(fy), deleted_at__isnull=True).exclude(
        status__in=aside
    )
    at_schools = live.filter(school_id__in=pks).values_list("id", flat=True)
    invited = ClusterActivityAttendance.objects.filter(school_id__in=pks).filter(
        Q(invited=True) | Q(attended=True)
    )
    sessions = live.filter(id__in=invited.values("activity_id")).values_list(
        "id", flat=True
    )
    clusters = School.objects.filter(id__in=pks, cluster_id__isnull=False).values(
        "cluster_id"
    )
    unrecorded = (
        live.filter(
            cluster_id__in=clusters,
            school_id__isnull=True,
            activity_type__in=TRAINING_TYPES,
        )
        .exclude(id__in=ClusterActivityAttendance.objects.values("activity_id"))
        .values_list("id", flat=True)
    )
    return list({*at_schools, *sessions, *unrecorded})


def core_school_plans(principal, schools, fy) -> tuple[dict, dict]:
    """The Core School Visits and Core School Trainings sheets for these
    schools, read from My Plan's tables of their year's work."""
    codes = {s.code if hasattr(s, "code") else s.school_id for s in schools}
    pks = [s.id for s in schools]
    context = context_for(principal, core_school_activity_ids(pks, fy), fy)

    def mine(rows):
        return [row for row in rows if row.get("school_id") in codes]

    visits = _sheet(
        CORE_VISITS_TITLE,
        CORE_SCHOOL_VISITS.columns,
        mine(context.get("core_school_visits") or []),
    )
    trainings = _sheet(
        CORE_TRAININGS_TITLE,
        CORE_TRAINING_PLAN_COLUMNS,
        mine(context.get("core_school_trainings") or []),
    )
    return visits, trainings


def shown(sheet: dict) -> list[list[str]]:
    """A sheet's rows as the page writes them: "5 Oct 2026", "UGX 40,000"."""
    formats = sheet.get("number_formats") or {}
    out = []
    for row in sheet["rows"]:
        cells = []
        for index, value in enumerate(row, start=1):
            if isinstance(value, date):
                cells.append(
                    f"{value:%b} {value.day}, {value:%a}"
                    if formats.get(index) == SHORT_DAY
                    else f"{value.day} {value:%b %Y}"
                )
            elif isinstance(value, int) and formats.get(index) == MONEY:
                cells.append(f"UGX {value:,}")
            else:
                cells.append("" if value is None else str(value))
        out.append(cells)
    return out


def tables_from_csv(lines) -> dict[str, list[dict]]:
    """``csv_rows`` read back: ``{sheet title: [{heading: cell}]}``."""
    tables: dict[str, list[dict]] = {}
    lines = list(lines)
    index = 0
    while index < len(lines):
        line = lines[index]
        if len(line) == 1 and line[0] and index + 1 < len(lines):
            title, headers = line[0], lines[index + 1]
            rows = []
            index += 2
            while index < len(lines) and lines[index]:
                rows.append(dict(zip(headers, lines[index])))
                index += 1
            tables[title] = rows
        index += 1
    return tables
