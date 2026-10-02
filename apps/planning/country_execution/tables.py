"""The consolidated tables behind the Execution & Completion figures.

Owner, 2026-10-02: what was done for the planning tab, for execution — every
card is a link to the table of what it counts, grouped by Programme Lead, so a
figure can be followed up with the person it belongs to, and every table that
lists schools carries the School ID.

Each table lists the same records its card counts: the period's classified
activities (``dataset``) under the page's filters, kept by the same test the
card's number is counted with (``service.STAGE_FILTERS``). A card's number IS
its table's row count. The tables are drawn by the page the planning tables
are drawn by (apps.planning.country_oversight.tables), with one more thing a
row can say: whether the visit is one of those counted toward its person's 280
or 560.
"""

from __future__ import annotations

from apps.planning.country_execution import service as svc
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight import rules
from apps.planning.country_oversight.requirements import (
    NO_LEAD_KEY,
    NO_LEAD_LABEL,
    NO_OWNER_KEY,
)
from apps.planning.country_oversight.tables import (
    SCHOOL_COLUMNS,
    Column,
    Spec,
    Table,
    _count_line,
    _sortable,
)

NOBODY = "No responsible person recorded"
COUNTED = "Yes"
NOT_COUNTED = "No — donor, story or social"

C = Column
LEAD = C("lead", "Programme Lead")
PLACE_COLUMNS = (
    SCHOOL_COLUMNS[0],
    C("school", "School / Cluster", is_school=True),
    *SCHOOL_COLUMNS[2:],
)
RECORD_COLUMNS = (
    LEAD,
    C("staff", "Responsible"),
    C("role", "Role"),
    C("by", "Delivered By"),
    C("activity", "Activity"),
    C("counted", "Counts Toward Target"),
    *PLACE_COLUMNS,
    C("due", "Due", is_date=True),
    C("delivered", "Delivered On", is_date=True, optional=True),
    C("stage", "Stage"),
    C("age", "Days Overdue", numeric=True),
    C("waiting", "Waiting On"),
    C("last", "Last Action", is_date=True, optional=True),
)


def _records(key: str, title: str, description: str, *, metric: str, short: str):
    return Spec(
        key,
        title,
        "activity",
        description,
        RECORD_COLUMNS,
        groups=("lead", "staff"),
        headings=(1, 2),
        export_only=("role", "last"),
        metric=metric,
        short=short,
    )


SPECS: dict[str, Spec] = {
    spec.key: spec
    for spec in (
        _records(
            "due",
            "Activities Planned",
            "Every activity whose approved date falls in the period, under the "
            "person responsible for it: staff work under whoever delivers it, "
            "Partner work under whoever handed it over or monitors it.",
            metric="cxo_activities_due",
            short="Planned",
        ),
        _records(
            "started",
            "Activities Started",
            "The period's activities that have been started in the field.",
            metric="cxo_started",
            short="Started",
        ),
        _records(
            "executed",
            "Execution Completed",
            "The period's activities delivered and submitted for review: "
            "waiting on a Programme Lead or Impact Assessment, or verified.",
            metric="cxo_execution_completed",
            short="Completed",
        ),
        _records(
            "verified",
            "Verified Activities",
            "The period's activities verified: by the Programme Lead for a "
            "CCEO's work, by Impact Assessment for Partner work and a Lead's own.",
            metric="cxo_ia_verified",
            short="Verified",
        ),
        _records(
            "closed",
            "Fully Closed Activities",
            "The period's activities through the governed closure: evidence, "
            "Salesforce ID, verification and — where money moved — accounts.",
            metric="cxo_fully_closed",
            short="Closed",
        ),
        _records(
            "overdue",
            "Overdue Activities",
            "The period's activities past their approved date and not yet "
            "verified, with the stage each is stuck at and who holds the next "
            "action. The oldest first under each person.",
            metric="cxo_overdue",
            short="Overdue",
        ),
        Spec(
            "visits",
            "Visits Against Target",
            "visit",
            "Every Follow up, In-school Training and SSA Support visit staff "
            "have on the plan for the period, and how far each has got. These "
            "are the visits counted against each CCEO's 560 and each Programme "
            "Lead's 280.",
            (
                LEAD,
                C("staff", "Planned By"),
                C("role", "Role"),
                *SCHOOL_COLUMNS,
                C("activity", "Visit"),
                C("due", "Due", is_date=True),
                C("delivered", "Delivered On", is_date=True, optional=True),
                C("state", "Delivery"),
                C("stage", "Stage"),
            ),
            groups=("lead", "staff"),
            headings=(1, 2),
            export_only=("role",),
            short="Visits",
        ),
    )
}
TAB_ORDER = ("due", "started", "executed", "verified", "closed", "overdue", "visits")
METRIC_TABLES = {spec.metric: spec.key for spec in SPECS.values() if spec.metric}

#: How far a counted visit has got, in the words the visits chart uses.
STATE_VERIFIED = "Verified"
STATE_DELIVERED = "Delivered, in review"
STATE_PLANNED = "Planned, not yet delivered"


def _places(records) -> tuple[dict, dict]:
    """School id → (School ID, name, district) and cluster id → (name,
    district), for the records listed."""
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    school_ids = {r.school_id for r in records if r.school_id}
    cluster_ids = {r.cluster_id for r in records if r.cluster_id and not r.school_id}
    schools, clusters = {}, {}
    if school_ids:
        manager = getattr(School, "all_objects", School.objects)
        for pk, code, name, district in manager.filter(id__in=school_ids).values_list(
            "id", "school_id", "name", "district__name"
        ):
            schools[pk] = (code or "", name or "", district or "")
    if cluster_ids:
        manager = getattr(Cluster, "all_objects", Cluster.objects)
        for pk, name, district in manager.filter(id__in=cluster_ids).values_list(
            "id", "name", "district__name"
        ):
            clusters[pk] = (name or "", district or "")
    return schools, clusters


def _who(dataset, record) -> tuple[str, str, str]:
    """(Programme Lead, person, role) a record is credited to."""
    info = dataset.owners.get(record.owner_key)
    if info is None or record.owner_key == NO_OWNER_KEY:
        return NO_LEAD_LABEL, NOBODY, ""
    lead = info.lead_name if info.lead_key != NO_LEAD_KEY else NO_LEAD_LABEL
    return lead, info.name, rules.ROLE_LABELS.get(info.role, "")


def _state(record) -> str:
    if record.verified:
        return STATE_VERIFIED
    if record.executed:
        return STATE_DELIVERED
    return STATE_PLANNED


def _row(dataset, record, schools, clusters) -> dict:
    lead, staff, role = _who(dataset, record)
    code, name, district = schools.get(record.school_id, ("", "", ""))
    if not record.school_id:
        name, district = clusters.get(record.cluster_id, ("", ""))
    partner = dataset.partner_names.get(record.partner_key, "Partner")
    counted = ""
    if record.counted:
        counted = COUNTED
    elif record.outreach:
        counted = NOT_COUNTED
    stage = st.STAGE_LABELS.get(record.stage, record.stage)
    if record.overdue:
        stage = f"{stage} · {st.OVERDUE_LABELS.get(record.overdue, '')}"
    return {
        "lead": lead,
        "staff": staff,
        "role": role,
        "by": "Staff" if record.channel == "staff" else f"Partner · {partner}",
        "activity": rules.KIND_LABELS.get(record.kind)
        if record.counted
        else dataset.type_labels.get(
            record.activity_type, record.activity_type.replace("_", " ").title()
        ),
        "counted": counted,
        "school_id": code,
        "school": name,
        "type": rules.type_label(record.school_type) if record.school_type else "",
        "district": district,
        "due": record.due,
        "delivered": record.delivered_day if record.started else None,
        "stage": stage,
        "state": _state(record),
        "age": record.age if record.overdue else None,
        "waiting": st.OWNER_LABELS.get(record.owner, ""),
        "last": record.last_action,
        "_age": record.age if record.overdue else 0,
    }


def _keeps(key: str):
    if key == "visits":
        # On the plan as the planning tab reads "planned" (dataset v_planned).
        from apps.planning.country_oversight import policy

        return lambda r: r.counted and r.status in policy.PLANNED_STATES
    return svc.STAGE_FILTERS[key]


def _notes(snapshot, key: str) -> dict:
    """Group path → the balance its heading states, from the fold the cards
    read: delivered of what is due, and what is left (owner, 2026-10-01:
    "planned AND remaining" at each level)."""
    notes: dict[tuple, str] = {}

    def balance(tally, target) -> str:
        if key == "visits":
            text = f"{tally.v_delivered:,} delivered of {tally.v_planned:,} planned"
            if target:
                text += (
                    f" · target {target:,} · "
                    f"{max(0, target - tally.v_delivered):,} still to deliver"
                )
            return text
        return (
            f"{tally.executed:,} of {tally.due:,} planned delivered · "
            f"{tally.verified:,} verified · {tally.overdue:,} overdue"
        )

    f = snapshot.filters
    targeted = not (f.activity_type or f.channel)
    for lead in snapshot.tree.leads:
        name = NO_LEAD_LABEL if lead.is_no_lead else lead.name
        target = snapshot.targets.get(("lead", lead.key)) if targeted else None
        notes[(name,)] = balance(lead.tally, target)
        for owner in lead.owners:
            person = NOBODY if owner.key == NO_OWNER_KEY else owner.name
            target = snapshot.targets.get(("owner", owner.key)) if targeted else None
            notes[(name, person)] = balance(owner.tally, target)
    return notes


def build(snapshot, key: str) -> Table:
    """The whole table for the page's selection, sorted, unpaged."""
    spec = SPECS[key]
    table = Table(spec=spec)
    dataset = snapshot.dataset
    keeps = _keeps(key)
    records = [r for r in svc.filtered_records(dataset, snapshot.filters) if keeps(r)]
    schools, clusters = _places(records)
    rows = [_row(dataset, record, schools, clusters) for record in records]
    rank = {lead.name: index for index, lead in enumerate(snapshot.tree.leads)}

    def sort_key(row):
        return (
            rank.get(row["lead"], len(rank)),
            row["lead"].casefold(),
            row["staff"] == NOBODY,
            row["staff"].casefold(),
            -row["_age"],
            _sortable(row["due"]),
            _sortable(row["school"]),
        )

    table.rows = sorted(rows, key=sort_key)
    for row in table.rows:
        row.pop("_age")
    table.notes = _notes(snapshot, key)
    c = snapshot.tree.country
    if key == "visits":
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} planned · "
            f"{c.v_delivered:,} delivered · {c.v_verified:,} verified"
        )
    else:
        schools_reached = len({row["school_id"] for row in rows if row["school_id"]})
        table.summary = (
            f"{_count_line(len(rows), spec.unit)} at "
            f"{_count_line(schools_reached, 'school')}"
        )
    return table


def table_url(key: str, query: str = "") -> str:
    return svc.records_url(key, query)


__all__ = [
    "METRIC_TABLES",
    "SPECS",
    "TAB_ORDER",
    "build",
    "table_url",
]
