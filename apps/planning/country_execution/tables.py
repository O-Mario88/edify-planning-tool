"""The consolidated tables behind the Execution & Completion figures.

Owner, 2026-10-02: what was done for the planning tab, for execution — every
card is a link to the table of what it counts, so a figure can be followed up
with the people it belongs to, and every table that lists schools carries the
School ID.

Each table lists the same records its card counts: the period's classified
activities (``dataset``) under the page's filters, kept by the same test the
card's number is counted with (``service.STAGE_FILTERS``). A card's number IS
its table's row count.

They are drawn as the planning tables are (apps.planning.country_oversight.
tables; owner, 2026-10-02: "a normal table with sub region, cceo, PL, cluster
all in columns"): an ordinary table that opens with the Programme Lead,
sub-region, district, CCEO or Programme Lead and cluster of the school — who
HOLDS it, so a school is under one person in every table — then the School
ID, the school and the rest. Who the work is credited to, as the cards count
it, is a column of its own ("Responsible"), and the page's Programme Lead
choice keeps a person's work. The selection's balance is the title band's
summary line; there are no heading rows.
"""

from __future__ import annotations

from apps.planning.country_execution import service as svc
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight import rules
from apps.planning.country_oversight.requirements import (
    NO_LEAD_KEY,
    NO_LEAD_LABEL,
    NO_OWNER_KEY,
    NO_OWNER_LABEL,
)
from apps.planning.country_oversight.tables import (
    PLACE,
    SCHOOL,
    Column,
    Spec,
    Table,
    _count_line,
    _Places,
)

NOBODY = "No responsible person recorded"
COUNTED = "Yes"
NOT_COUNTED = "No — donor, story or social"
NOT_DELIVERED = "Not yet delivered"
NOT_RECORDED = "Date not recorded"

C = Column
#: Whose work it is, as the cards count it: the person delivering staff
#: work; for Partner work, who handed it over or monitors it.
RESPONSIBLE = (
    C("staff", "Responsible"),
    C("role", "Responsible's Role"),
    C("staff_lead", "Responsible's Programme Lead"),
)
RECORD_COLUMNS = (
    *PLACE,
    *SCHOOL,
    C("activity", "Activity"),
    C("counted", "Counts Toward Target"),
    C("by", "Delivered By"),
    *RESPONSIBLE,
    C("due", "Due", is_date=True),
    C("delivered", "Delivered On", is_date=True, blank=NOT_DELIVERED),
    C("stage", "Stage"),
    C("age", "Days Overdue", numeric=True),
    C("waiting", "Waiting On"),
    C("last", "Last Action", is_date=True),
)
EXPORT_ONLY = ("role", "staff_lead", "last")


def _records(key: str, title: str, description: str, *, metric: str, short: str):
    return Spec(
        key,
        title,
        "activity",
        description,
        RECORD_COLUMNS,
        export_only=EXPORT_ONLY,
        metric=metric,
        short=short,
    )


SPECS: dict[str, Spec] = {
    spec.key: spec
    for spec in (
        _records(
            "due",
            "Activities Planned",
            "Every activity whose approved date falls in the period, the days "
            "still to come included, with who is responsible for it: staff "
            "work is its deliverer's, Partner work is whoever handed it over "
            "or monitors it.",
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
            "action.",
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
                *PLACE,
                *SCHOOL,
                C("activity", "Visit"),
                C("staff", "Planned By"),
                C("role", "Planner's Role"),
                C("staff_lead", "Planner's Programme Lead"),
                C("due", "Due", is_date=True),
                C("delivered", "Delivered On", is_date=True, blank=NOT_DELIVERED),
                C("state", "Delivery"),
                C("stage", "Stage"),
            ),
            export_only=("role", "staff_lead"),
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


class _Where:
    """Where each record's school sits — its holder and their Programme Lead,
    its sub-region, district and cluster — from the planning page's own
    dataset, as the planning tables read it (``_Places``), so a school is
    under the same person in every table on either tab."""

    def __init__(self, user, snapshot, records):
        from apps.schools.models import School

        self.places = _Places(user, snapshot.filters.planning())
        facts = self.places.dataset.facts
        missing = {
            r.school_id for r in records if r.school_id and r.school_id not in facts
        }
        # A school the planning page does not hold (closed since, or outside
        # its requirement) still has execution to list.
        manager = getattr(School, "all_objects", School.objects)
        self.others = (
            {school.id: school for school in manager.filter(id__in=missing)}
            if missing
            else {}
        )

    def of(self, record, lead: str, who: str) -> dict:
        places = self.places
        if record.school_id:
            fact = places.dataset.facts.get(record.school_id)
            if fact is not None:
                return places.of_record(fact)
            place = places.of_school(self.others.get(record.school_id))
            if place is not None:
                return place
        # A cluster session: the cluster's own district, under the person
        # the session is credited to.
        name, district_id, _responsible = places.clusters.get(
            record.cluster_id, ("", None, None)
        )
        district, _sub_id, sub_region = places.districts.get(district_id, ("", "", ""))
        return {
            "holder_lead": lead,
            "holder": who if who != NOBODY else NO_OWNER_LABEL,
            "sub_region": sub_region,
            "district": district,
            "cluster": name or ("Cluster" if record.cluster_id else ""),
            "school_id": "",
            "school": f"{name or 'Cluster'} (cluster)" if record.cluster_id else "",
            "type": "",
        }


def _row(dataset, record, where: _Where) -> dict:
    lead, staff, role = _who(dataset, record)
    partner = dataset.partner_names.get(record.partner_key, "Partner")
    counted = ""
    if record.counted:
        counted = COUNTED
    elif record.outreach:
        counted = NOT_COUNTED
    stage = st.STAGE_LABELS.get(record.stage, record.stage)
    if record.overdue:
        stage = f"{stage} · {st.OVERDUE_LABELS.get(record.overdue, '')}"
    delivered = record.delivered_day if record.started else None
    place = where.of(record, lead, staff)
    return {
        **place,
        "lead": place["holder_lead"],
        "staff": staff,
        "role": role,
        "staff_lead": lead,
        "by": "Staff" if record.channel == "staff" else f"Partner · {partner}",
        "activity": rules.KIND_LABELS.get(record.kind)
        if record.counted
        else dataset.type_labels.get(
            record.activity_type, record.activity_type.replace("_", " ").title()
        ),
        "counted": counted,
        "due": record.due,
        "delivered": delivered,
        # Delivered work with no day recorded says so, not "not yet".
        "delivered_note": NOT_RECORDED if record.executed and not delivered else "",
        "stage": stage,
        "state": _state(record),
        "age": record.age if record.overdue else None,
        "waiting": st.OWNER_LABELS.get(record.owner, ""),
        "last": record.last_action,
    }


def _keeps(key: str):
    if key == "visits":
        # On the plan as the planning tab reads "planned" (dataset v_planned).
        from apps.planning.country_oversight import policy

        return lambda r: r.counted and r.status in policy.PLANNED_STATES
    return svc.STAGE_FILTERS[key]


def _summary(snapshot, key: str, rows: list, unit: str) -> str:
    """What the rows add up to, and the selection's balance (owner,
    2026-10-01: planned AND remaining) — in the title band, the tables having
    no heading rows."""
    c = snapshot.tree.country
    if key == "visits":
        f = snapshot.filters
        target = (
            snapshot.targets.get(("country", ""))
            if not (f.activity_type or f.channel)
            else None
        )
        text = (
            f"{_count_line(len(rows), unit)} planned · {c.v_delivered:,} delivered"
            f" · {c.v_verified:,} verified"
        )
        if target:
            text += (
                f" · target {target:,} · "
                f"{max(0, target - c.v_delivered):,} still to deliver"
            )
        return text
    schools = len({row["school_id"] for row in rows if row["school_id"]})
    return (
        f"{_count_line(len(rows), unit)} at {_count_line(schools, 'school')} · "
        f"{c.executed:,} of {c.due:,} planned delivered · {c.verified:,} verified · "
        f"{c.overdue:,} overdue"
    )


def build(user, snapshot, key: str) -> Table:
    """The whole table for the page's selection, sorted, unpaged."""
    spec = SPECS[key]
    table = Table(spec=spec)
    dataset = snapshot.dataset
    keeps = _keeps(key)
    records = [r for r in svc.filtered_records(dataset, snapshot.filters) if keeps(r)]
    where = _Where(user, snapshot, records)
    rows = [_row(dataset, record, where) for record in records]
    table.rows = where.places.sort(rows, "school", "due", "activity")
    table.summary = _summary(snapshot, key, rows, spec.unit)
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
