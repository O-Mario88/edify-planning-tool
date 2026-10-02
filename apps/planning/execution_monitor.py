"""The Execution & Completion Monitor: each person's plan as it is delivered.

Owner, 2026-09-29: "Design a similar Country execution and completion
Monitoring" beside the Planning Monitor. The Planning Monitor asks whether
the year is planned; this one asks whether the plan is happening and whether
what happened is finished: delivered, then complete — the Salesforce ID and
the form both in (apps.activities.completion_columns, owner 2026-09-26) —
then verified by Impact Assessment.

The same people as the Planning Monitor (apps.planning.monitor_roster): every
Programme Lead (280 visits a year) and every CCEO (560) in the reader's
scope, under their Lead. Their own staff-delivered work in the fiscal year is
counted by the person responsible for it, in either id space, as My Plan
counts it; the partner work they handed over or monitor is counted apart.

Counted by the planning rulebook (apps.planning.country_oversight.rules), as
the Planning tab beside this one counts the plan (owner audit, 2026-10-02):

* **Visits** against 280 or 560 are Follow up, In-school Training and SSA
  Support at a school. An in-school training is one visit and one training.
  Donor, story, invitation and social visits are delivered work like any
  other — due, delivered, overdue — and are shown apart, never among the
  visits.
* **Partner work** is credited to whoever handed it over or monitors it,
  then to whoever holds the school: the order Country Planning Oversight and
  its Execution tab credit it in, so one Partner visit sits under one person
  on every page.

* **Due** — work whose planned date has arrived. Future work is not late.
* **Delivered** — the status says the work happened: submitted, awaiting
  verification, or verified.
* **Overdue** — past its planned day, not delivered, not returned. The day
  itself is not late.
* **Complete** — delivered with the Salesforce ID and the form both in.
* **Verified** — confirmed by Impact Assessment.

A fixed handful of queries whatever the size of the country, and every
figure folded from the activity rows under it, so a Lead's total is the sum
of their people and every count opens the list of activities behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Q

from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
from apps.core.metrics import percentage
from apps.planning.monitor_roster import ROLE_CCEO, ROLE_PL

TRAINING_KINDS = frozenset(str(t) for t in TRAINING_TYPES)
MEETING_KINDS = frozenset(str(t) for t in CLUSTER_MEETING_TYPES)

RETURNED_STATUSES = frozenset(("returned", "returned_by_pl", "returned_by_ia"))

#: The drill-down lists, in the order the page offers them.
LISTS = (
    ("overdue", "Overdue — due, not delivered"),
    ("missing_salesforce", "Delivered, missing the Salesforce ID"),
    ("missing_evidence", "Delivered, missing the form"),
    ("awaiting_ia", "Awaiting IA verification"),
    ("returned", "Returned for correction"),
)
LIST_LABELS = dict(LISTS)

#: The table's follow-up columns: each count opens its list.
LIST_COLUMNS = (
    ("overdue", "Overdue", "danger"),
    ("missing_salesforce", "No SF ID", "warning"),
    ("missing_evidence", "No form", "warning"),
    ("awaiting_ia", "Awaiting IA", "info"),
    ("returned", "Returned", "danger"),
)


@dataclass
class WorkRow:
    """One activity, for the drill-down list."""

    id: str
    activity_type: str
    status: str
    planned_date: date | None
    school_id: str
    school_code: str
    school_name: str
    cluster_name: str
    person_key: str
    person_name: str
    salesforce_ok: bool = False
    evidence_ok: bool = False

    @property
    def place(self) -> str:
        return self.school_name or self.cluster_name or "—"

    @property
    def url(self) -> str:
        return f"/activities/{self.id}"


@dataclass
class PersonExecution:
    key: str
    name: str
    lead_id: str
    lead_name: str
    role: str = ROLE_CCEO
    visits_target: int = 0
    ids: frozenset = field(default_factory=frozenset)

    visits_planned: int = 0
    visits_delivered: int = 0
    # Donor, story, invitation and social visits: delivered, not counted.
    outreach_planned: int = 0
    outreach_delivered: int = 0
    trainings_planned: int = 0
    trainings_delivered: int = 0
    meetings_planned: int = 0
    meetings_delivered: int = 0
    planned: int = 0
    due: int = 0
    delivered: int = 0
    delivered_due: int = 0
    complete: int = 0
    verified: int = 0
    overdue: int = 0
    missing_salesforce: int = 0
    missing_evidence: int = 0
    awaiting_ia: int = 0
    returned: int = 0
    partner_scheduled: int = 0
    partner_delivered: int = 0

    @property
    def is_lead(self) -> bool:
        return self.role == ROLE_PL

    @property
    def role_label(self) -> str:
        return {ROLE_PL: "Programme Lead", ROLE_CCEO: "CCEO"}.get(self.role, "")

    @property
    def target_progress(self) -> int | None:
        return percentage(self.visits_delivered, self.visits_target)

    @property
    def due_progress(self) -> int | None:
        return percentage(self.delivered_due, self.due)

    @property
    def complete_share(self) -> int | None:
        return percentage(self.complete, self.delivered)

    @property
    def target_tone(self) -> str:
        return _tone(self.target_progress)

    @property
    def due_tone(self) -> str:
        return _tone(self.due_progress)

    @property
    def list_cells(self) -> list[tuple[dict, int]]:
        return [
            ({"key": key, "label": label, "tone": tone}, getattr(self, key))
            for key, label, tone in LIST_COLUMNS
        ]


_SUMMED = tuple(
    name
    for name, spec in PersonExecution.__dataclass_fields__.items()
    if spec.type in ("int", int)
)


@dataclass
class TeamExecution:
    key: str
    name: str
    people: list = field(default_factory=list)

    def __getattr__(self, attr):
        # Every person's count sums the same way; the rates below are
        # recomputed from the sums, never averaged.
        if attr in _SUMMED:
            return sum(getattr(p, attr) for p in self.people)
        raise AttributeError(attr)

    target_progress = PersonExecution.target_progress
    due_progress = PersonExecution.due_progress
    complete_share = PersonExecution.complete_share
    target_tone = PersonExecution.target_tone
    due_tone = PersonExecution.due_tone
    list_cells = PersonExecution.list_cells

    @property
    def person_count(self) -> int:
        return len(self.people)


def _tone(progress: int | None) -> str:
    if progress is None:
        return "neutral"
    if progress >= 90:
        return "success"
    if progress >= 60:
        return "info"
    return "warning"


def execution_monitor(
    principal,
    *,
    fy: str,
    program_lead_id: str | None = None,
    list_key: str | None = None,
    person_id: str | None = None,
    today: date | None = None,
) -> dict:
    """The monitor for this reader and year.

    Returns ``teams`` (TeamExecution, each holding its PersonExecution rows),
    ``totals`` (over everyone), ``lead_options``, ``person_options`` and
    ``rows`` — the activities behind the chosen list, narrowed to the chosen
    Lead and person.
    """
    from apps.activities.completion_columns import (
        completion_records,
        expected_evidence,
    )
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules
    from apps.planning.monitor_roster import monitor_roster
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES
    from apps.planning.planning_monitor import _delivered_statuses
    from apps.planning.school_planning_badges import VERIFIED_STATUSES

    fy = str(fy)
    today = today or date.today()
    teams: list[TeamExecution] = []
    people: dict[str, PersonExecution] = {}
    for team in monitor_roster(principal):
        row = TeamExecution(key=team.key, name=team.name)
        for p in team.people:
            if p.key in people:
                continue
            person = people[p.key] = PersonExecution(
                key=p.key,
                name=p.name,
                lead_id=team.key,
                lead_name=team.name,
                role=p.role,
                visits_target=p.visits_target,
                ids=p.ids,
            )
            row.people.append(person)
        if row.people:
            teams.append(row)

    empty = {
        "fy": fy,
        "teams": [],
        "totals": TeamExecution(key="all", name="All"),
        "lead_options": [],
        "person_options": [],
        "rows": [],
    }
    if not people:
        return empty
    by_id = {i: person for person in people.values() for i in person.ids}
    ids = list(by_id)
    delivered_statuses = _delivered_statuses()
    awaiting_ia = {"awaiting_ia_verification"}

    # The hand-overs these people made or monitor, by the activity each
    # became or carries: its Partner work is theirs first.
    handed: dict[str, tuple] = {}
    for scheduled, source, monitor, assigner in (
        PartnerAssignment.objects.filter(
            Q(monitoring_staff_id__in=ids) | Q(assigning_staff_id__in=ids)
        )
        .filter(
            Q(scheduled_activity_id__isnull=False) | Q(source_activity_id__isnull=False)
        )
        .values_list(
            "scheduled_activity_id",
            "source_activity_id",
            "monitoring_staff_id",
            "assigning_staff_id",
        )
        .order_by("created_at")
    ):
        for activity_id in (scheduled, source):
            if activity_id:
                handed[activity_id] = (monitor, assigner)

    records = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            status__in=LIVE_ACTIVITY_STATUSES,
            fy=fy,
        )
        .filter(
            (Q(responsible_staff_id__in=ids) & ~Q(delivery_type="partner"))
            | Q(delivery_type="partner", monitored_by_staff_id__in=ids)
            | Q(delivery_type="partner", responsible_staff_id__in=ids)
            | Q(delivery_type="partner", school__account_owner_id__in=ids)
            | Q(delivery_type="partner", id__in=list(handed))
        )
        .values_list(
            "id",
            "activity_type",
            "status",
            "planned_date",
            "delivery_type",
            "responsible_staff_id",
            "monitored_by_staff_id",
            "school_id",
            "school__school_id",
            "school__name",
            "cluster__name",
            "purpose_type",
            "cluster_id",
            "school__account_owner_id",
            "scheduled_date",
        )
    )
    delivered_ids = [
        r[0] for r in records if r[4] != "partner" and r[2] in delivered_statuses
    ]
    salesforce, evidence = completion_records(delivered_ids)

    wanted_lead = (
        program_lead_id if program_lead_id not in (None, "", "all", "All") else None
    )
    listed: list[WorkRow] = []
    for (
        activity_id,
        activity_type,
        status,
        planned_date,
        delivery_type,
        responsible,
        monitor,
        school_pk,
        school_code,
        school_name,
        cluster_name,
        purpose_type,
        cluster_pk,
        holder,
        scheduled_date,
    ) in records:
        activity_type = str(activity_type or "")
        if delivery_type == "partner":
            # Dated Partner work only: a hand-over the Partner has not dated
            # is planning still to do, and the Planning tab follows it.
            if planned_date is None and scheduled_date is None:
                continue
            person = next(
                (
                    by_id[str(raw)]
                    for raw in (
                        *handed.get(activity_id, ()),
                        monitor,
                        responsible,
                        holder,
                    )
                    if raw and str(raw) in by_id
                ),
                None,
            )
            if person is None:
                continue
            person.partner_scheduled += 1
            if status in delivered_statuses:
                person.partner_delivered += 1
            continue
        person = by_id.get(str(responsible or ""))
        if person is None:
            continue
        is_delivered = status in delivered_statuses
        is_due = planned_date is not None and planned_date <= today
        person.planned += 1
        at_school = bool(school_pk) and not cluster_pk
        if at_school and rules.visit_kind(activity_type, purpose_type):
            # On the plan as the Planning tab reads it: a visit sent back to
            # planning is not one of the visits planned.
            if status in _planned_states():
                person.visits_planned += 1
            person.visits_delivered += is_delivered
        elif at_school and _is_outreach(activity_type, purpose_type):
            person.outreach_planned += 1
            person.outreach_delivered += is_delivered
        if activity_type in TRAINING_KINDS:
            person.trainings_planned += 1
            person.trainings_delivered += is_delivered
        elif activity_type in MEETING_KINDS:
            person.meetings_planned += 1
            person.meetings_delivered += is_delivered
        if is_due:
            person.due += 1
            person.delivered_due += is_delivered
        gaps = []
        if status in RETURNED_STATUSES:
            person.returned += 1
            gaps.append("returned")
        elif is_due and planned_date < today and not is_delivered:
            person.overdue += 1
            gaps.append("overdue")
        sf_ok = ev_ok = False
        if is_delivered:
            person.delivered += 1
            kinds = evidence.get(activity_id, set())
            sf_ok = bool(salesforce.get(activity_id))
            ev_ok = expected_evidence(activity_type)[0] in kinds
            if sf_ok and ev_ok:
                person.complete += 1
            if not sf_ok:
                person.missing_salesforce += 1
                gaps.append("missing_salesforce")
            if not ev_ok:
                person.missing_evidence += 1
                gaps.append("missing_evidence")
            if status in VERIFIED_STATUSES:
                person.verified += 1
            if status in awaiting_ia:
                person.awaiting_ia += 1
                gaps.append("awaiting_ia")
        if (
            list_key in gaps
            and (not wanted_lead or person.lead_id == wanted_lead)
            and (not person_id or person.key == person_id)
        ):
            listed.append(
                WorkRow(
                    id=activity_id,
                    activity_type=activity_type,
                    status=status,
                    planned_date=planned_date,
                    school_id=school_pk or "",
                    school_code=school_code or "",
                    school_name=school_name or "",
                    cluster_name=cluster_name or "",
                    person_key=person.key,
                    person_name=person.name,
                    salesforce_ok=sf_ok,
                    evidence_ok=ev_ok,
                )
            )

    listed.sort(
        key=lambda r: (
            r.planned_date or date.max,
            r.person_name.casefold(),
            r.place.casefold(),
        )
    )
    lead_options = [
        {"id": team.key, "name": team.name, "count": team.person_count}
        for team in teams
    ]
    totals = TeamExecution(
        key="all", name="All", people=[p for team in teams for p in team.people]
    )
    shown = [team for team in teams if team.key == wanted_lead] or teams
    person_options = [
        {"id": p.key, "name": p.name} for team in shown for p in team.people
    ]
    return {
        "fy": fy,
        "teams": shown,
        "totals": totals,
        "lead_options": lead_options,
        "person_options": person_options,
        "rows": listed,
    }


def _planned_states() -> frozenset:
    from apps.planning.country_oversight import policy

    return policy.PLANNED_STATES


def _is_outreach(activity_type: str, purpose_type) -> bool:
    """A donor, story, invitation or social visit (rules.outreach_visit_q,
    for a row already read at a school)."""
    from apps.planning.country_oversight import rules

    return activity_type in rules.OUTREACH_TYPES or (
        activity_type in rules.COUNTED_VISIT_TYPES
        and str(purpose_type or "") in rules.OUTREACH_PURPOSES
    )


__all__ = [
    "LISTS",
    "LIST_LABELS",
    "PersonExecution",
    "TeamExecution",
    "execution_monitor",
]
