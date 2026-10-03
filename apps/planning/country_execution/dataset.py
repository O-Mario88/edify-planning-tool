"""The window's activities, classified once and summed for every filter.

A fixed handful of grouped reads whatever the size of the country:

1. the activities due in the window (planned or cancelled), with the school,
   cluster and closure columns the classifier needs;
2. which of them wait on money the Accountant has not disbursed (the weekly
   advance ledger, AdvanceRequest);
3. who holds each verified record's closure (the governed ClosureBlocker
   checklist and the Partner payment);
4. the people behind every owner id (the planning owner directory);
5. the schedule trail for the window: what was due in it when it began, and
   what has been moved out of it since.

Each activity becomes one compact record (for the lists) and adds one vector
to its cell — owner, Partner, channel, region, district and activity type —
so any combination of the page's filters is a sum of whole cells.

**Who owns an activity.** Staff work belongs to the person delivering it (the
responsible staff member): supervision is not ownership, and a CCEO's work
stays the CCEO's while their Lead reads it through the team. Partner work has
no responsible staff member by construction; it is credited as Country
Planning Oversight credits it (apps.planning.country_oversight.people) — to
whoever monitors or made the hand-over, then the activity's own monitor, then
whoever holds the school — so a Partner's visit sits under the same person on
the planning tab, this tab and the monitors (owner audit, 2026-10-02).

**Which visits count.** Every activity is execution to follow, and the six
figures count them all. Beside them, the visits the rulebook counts toward a
person's 280 or 560 (apps.planning.country_oversight.rules: staff Follow up and
In-school Training) are counted on their own — planned,
delivered, verified — so delivery can be read against the same target the
plan is read against.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import cached_property
from typing import NamedTuple

from django.db.models import Q
from django.utils import timezone

from apps.planning.country_execution import stages as st
from apps.planning.country_oversight import policy, rules
from apps.planning.country_oversight.coverage import Window, _day
from apps.planning.country_oversight.requirements import (
    NO_OWNER_KEY,
    NO_OWNER_LABEL,
    OwnerInfo,
    lead_rosters,
    owner_directory,
    system_leads,
)

#: Staff delivery's place where a Partner key would be.
STAFF_KEY = "__staff__"

# ── The figures one activity contributes ─────────────────────────────────────
BASE_FIELDS: tuple[str, ...] = (
    "due",
    "started",
    "executed",
    "pl_applicable",
    "pl_reviewed",
    "verified",
    "closed",
    "returned",
    "cancelled",
    "overdue",
    "od_execution",
    "od_evidence",
    "od_correction",
    "od_pl_review",
    "od_ia_review",
    "finance_open",
    "on_time",
    "late",
    "start_unknown",
    "not_started",
    "upcoming",
    "age_1_2",
    "age_3_7",
    "age_8_14",
    "age_15",
    "own_staff",
    "own_pl",
    "own_ia",
    "own_partner",
    "own_finance",
    "own_external",
    "carried_forward",
    "funds_pending",
    # The visits counted toward a person's 280 or 560 (rules.visit_kind, staff
    # delivery): on the plan, delivered (submitted for review) and verified.
    "v_planned",
    "v_delivered",
    "v_verified",
    # Donor, story, invitation and social visits staff delivered: shown, not
    # counted.
    "v_outreach",
)
BASE_WIDTH = len(BASE_FIELDS)
IDX = {name: index for index, name in enumerate(BASE_FIELDS)}
#: Per trend bucket: planned, executed, verified, closed (not cumulative).
TREND_SERIES = ("plan", "exec", "ver", "closed")


class Bucket(NamedTuple):
    label: str
    caption: str
    start: date
    end: date  # exclusive


def buckets_for(window: Window) -> list[Bucket]:
    """The trend's sub-periods (spec §11.2): the week's days, the month's
    weeks, the quarter's months, the year's quarters."""
    if window.period == "week":
        return [
            Bucket(
                (window.start + timedelta(days=n)).strftime("%a"),
                (window.start + timedelta(days=n)).strftime("%-d %b"),
                window.start + timedelta(days=n),
                window.start + timedelta(days=n + 1),
            )
            for n in range((window.end - window.start).days)
        ]
    if window.period == "month":
        out = []
        days = (window.end - window.start).days
        edges = [0, 7, 14, 21, days]
        for n in range(4):
            start = window.start + timedelta(days=edges[n])
            end = window.start + timedelta(days=edges[n + 1])
            out.append(
                Bucket(
                    f"W{n + 1}",
                    f"{start.day}–{(end - timedelta(days=1)).day} {start:%b}",
                    start,
                    end,
                )
            )
        return out
    if window.period == "quarter":
        out = []
        cursor = window.start
        while cursor < window.end:
            last = calendar.monthrange(cursor.year, cursor.month)[1]
            nxt = cursor.replace(day=last) + timedelta(days=1)
            out.append(
                Bucket(
                    cursor.strftime("%b"),
                    cursor.strftime("%Y"),
                    cursor,
                    min(nxt, window.end),
                )
            )
            cursor = nxt
        return out
    # The year: its four quarters, October first.
    out = []
    cursor = window.start
    for n in range(4):
        month = cursor.month + 3
        year = cursor.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        nxt = date(year, month, 1)
        out.append(
            Bucket(
                f"Q{n + 1}",
                f"{cursor:%b}–{(nxt - timedelta(days=1)):%b}",
                cursor,
                min(nxt, window.end),
            )
        )
        cursor = nxt
    return out


def _bucket_of(day: date | None, buckets: list[Bucket]) -> int:
    """Index of the bucket a day falls in; -1 before the first, len after."""
    if day is None:
        return len(buckets)
    if day < buckets[0].start:
        return -1
    for index, bucket in enumerate(buckets):
        if day < bucket.end:
            return index
    return len(buckets)


# ── One activity, as the lists read it ───────────────────────────────────────
class ActivityRecord(NamedTuple):
    id: str
    activity_type: str
    status: str
    stage: str
    owner_key: str
    partner_key: str  # STAFF_KEY for staff delivery
    channel: str  # "staff" | "partner"
    school_id: str | None
    cluster_id: str | None
    region_id: str | None
    district_id: str | None
    due: date | None
    overdue: str
    owner: str  # who holds the next action, for open past-due work
    timing: str
    age: int
    started: bool
    executed: bool
    pl_applicable: bool
    pl_reviewed: bool
    verified: bool
    closed: bool
    returned: bool
    cancelled: bool
    finance_open: bool
    funds_pending: bool
    paid: bool  # a Partner payment made (payment_status paid or closed)
    executed_day: date | None
    verified_day: date | None
    closed_day: date | None
    last_action: date | None
    school_type: str
    # The counted kind of a visit at a school (rules.visit_kind), or "".
    kind: str
    # A donor, story, invitation or social visit at a school.
    outreach: bool
    delivered_day: date | None

    @property
    def counted(self) -> bool:
        """One of the visits a person's 280 or 560 is made of."""
        return bool(self.kind) and self.channel == "staff"


class RecordTable(list):
    """ActivityRecords, pickled as plain rows (see coverage.FactsTable)."""

    __slots__ = ()

    def __reduce__(self):
        return (_record_table, ([tuple(record) for record in self],))


def _record_table(rows) -> RecordTable:
    make = tuple.__new__
    return RecordTable(make(ActivityRecord, row) for row in rows)


# ── The dataset ──────────────────────────────────────────────────────────────
@dataclass
class ExecutionDataset:
    window: Window
    today: date
    built_at: datetime
    buckets: list
    records: list  # RecordTable
    cells: dict  # (owner, partner, channel, region, district, type) → vector
    owners: dict
    leads: list
    rosters: dict
    partner_names: dict
    region_names: dict
    type_labels: dict
    integrity: dict
    scope_label: str = ""
    universe: str = ""
    stamp: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def width(self) -> int:
        return BASE_WIDTH + len(TREND_SERIES) * len(self.buckets)

    @cached_property
    def by_owner(self) -> dict:
        grouped: dict[str, list] = {}
        for record in self.records:
            grouped.setdefault(record.owner_key, []).append(record)
        return grouped

    def __getstate__(self):
        state = dict(self.__dict__)
        state.pop("by_owner", None)
        return state


_COLUMNS = (
    "id",
    "activity_type",
    "status",
    "delivery_type",
    "school_id",
    "cluster_id",
    "responsible_staff_id",
    "monitored_by_staff_id",
    "assigned_partner_id",
    "purpose_type",
    "planned_date",
    "scheduled_date",
    "execution_started_at",
    "actual_delivery_date",
    "pl_reviewed_at",
    "ia_confirmed_at",
    "payment_status",
    "updated_at",
    "school__account_owner_id",
    "school__region_id",
    "school__district_id",
    "school__operational_status",
    "school__school_type",
    "cluster__responsible_staff_id",
    "cluster__district__region_id",
    "cluster__district_id",
    "closure_details__closed_at",
    "created_at",
)


def activity_scope_q(scope) -> Q | None:
    """The reader's activities, as one filter (None: none at all).

    The country's through its schools, clusters and staff
    (apps.core.scoping.activity_country_q); a region's through geography; an
    RVP with no regions reads the deployment; anyone else their schools.
    """
    from apps.core.scoping import activity_country_q

    def regions(ids) -> Q | None:
        ids = list(ids or [])
        if not ids:
            return None
        return Q(school__region_id__in=ids) | Q(
            school__isnull=True, cluster__district__region_id__in=ids
        )

    if getattr(scope, "country_scope", False):
        return activity_country_q(scope)
    if getattr(scope, "region_scope", False):
        return regions(scope.region_ids)
    if getattr(scope, "can_view_summary_only", False):
        if getattr(scope, "rvp_region_scoped", False):
            return regions(scope.region_ids)
        return Q()
    school_ids = list(getattr(scope, "school_ids", None) or [])
    return Q(school_id__in=school_ids) if school_ids else None


def _local_day(moment) -> date | None:
    if moment is None:
        return None
    if isinstance(moment, datetime):
        if timezone.is_aware(moment):
            return timezone.localtime(moment).date()
        return moment.date()
    return moment


_STAFF_ORDER = (
    "responsible_staff_id",
    "school__account_owner_id",
    "cluster__responsible_staff_id",
    "monitored_by_staff_id",
)
_PARTNER_ORDER = (
    "monitored_by_staff_id",
    "responsible_staff_id",
    "school__account_owner_id",
    "cluster__responsible_staff_id",
)


def _owner_candidates(row: dict, handed: dict) -> list[str]:
    """The raw ids an activity may be credited to, in order.

    Staff work: the person delivering it. Partner work: whoever monitors or
    made its hand-over, then the activity's own monitor and responsible
    person, then whoever holds the school or the cluster — the order Country
    Planning Oversight credits Partner work in (people.people_plan).
    """
    if row["delivery_type"] == "partner":
        raw = [*handed.get(row["id"], ()), *(row[name] for name in _PARTNER_ORDER)]
    else:
        raw = [row[name] for name in _STAFF_ORDER]
    return [str(value) for value in raw if value]


def _handed_by(activity_ids) -> dict:
    """Partner activity id → (monitor, assigner) of the hand-over it came
    from or carries."""
    from apps.partners.models import PartnerAssignment

    handed: dict = {}
    for scheduled, source, monitor, assigner in (
        PartnerAssignment.objects.filter(
            Q(scheduled_activity_id__in=activity_ids)
            | Q(source_activity_id__in=activity_ids)
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
    return handed


def _is_outreach(row: dict) -> bool:
    """A donor, story, invitation or social visit, or data collection, at a
    school (rules.outreach_visit_q, for a row already read)."""
    if not row["school_id"]:
        return False
    return rules.is_uncounted_visit(
        row["activity_type"], row["purpose_type"], delivery_type=row["delivery_type"]
    )


def build(
    scope,
    window: Window,
    *,
    base_q: Q | None = None,
    today: date | None = None,
    universe: str = "",
) -> ExecutionDataset:
    """Read, classify and sum the window's activities for this reader."""
    from apps.activities.models import Activity
    from apps.core.enums import ActivityType

    today = today or timezone.localdate()
    buckets = buckets_for(window)
    scope_q = activity_scope_q(scope)
    rows: list[dict] = []
    queryset = None
    if scope_q is not None:
        queryset = (
            Activity.objects.filter(deleted_at__isnull=True, status__in=st.READ_STATES)
            .annotate(due_day=_day())
            .filter(due_day__gte=window.start, due_day__lt=window.end)
            .filter(scope_q)
        )
        if base_q is not None:
            queryset = queryset.filter(base_q)
        rows = list(queryset.values(*_COLUMNS, "due_day").order_by())

    ids_subquery = queryset.values("id") if queryset is not None else []
    funds = _funds_pending(ids_subquery) if rows else set()
    closure = _closure_owners(queryset) if rows else {}

    moved = (
        _integrity(scope_q, base_q, window, rows)
        if scope_q is not None
        else _empty_integrity()
    )
    handed: dict = {}
    if any(row["delivery_type"] == "partner" for row in rows):
        handed.update(_handed_by(ids_subquery))
    moved_partner = [
        row["id"] for row in moved["moved_rows"] if row["delivery_type"] == "partner"
    ]
    if moved_partner:
        handed.update(_handed_by(moved_partner))
    candidates = {
        row["id"]: _owner_candidates(row, handed)
        for row in (*rows, *moved["moved_rows"])
    }
    directory = owner_directory({i for ids in candidates.values() for i in ids})

    owners: dict[str, OwnerInfo] = {}

    def owner_of(row) -> tuple[str, OwnerInfo | None]:
        ids = candidates[row["id"]]
        if row["delivery_type"] != "partner":
            # Staff work is its responsible person's, known to us or not.
            ids = ids[:1]
        for raw in ids:
            info = directory.get(raw)
            if info is not None:
                owners.setdefault(info.key, info)
                return info.key, info
        return NO_OWNER_KEY, None

    width = BASE_WIDTH + len(TREND_SERIES) * len(buckets)
    cells: dict[tuple, list] = {}
    records = RecordTable()
    for row in rows:
        owner_key, info = owner_of(row)
        partner = row["delivery_type"] == "partner"
        kind = info.kind if info is not None else "unassigned"
        status = row["status"]
        due = row["due_day"]
        # On time is read from the day the work was delivered, once the
        # officer has recorded it (owner, 2026-10-02): a visit delivered on
        # its day and keyed the next day is not late. Until then the day
        # execution was started in the app is the only date there is.
        start = row["actual_delivery_date"] or _local_day(row["execution_started_at"])
        verified_at = row["ia_confirmed_at"] or (
            row["pl_reviewed_at"] if status in st.VERIFIED else None
        )
        stage = st.classify(
            status=status,
            partner=partner,
            due=due,
            start=start,
            pl_reviewed_at=row["pl_reviewed_at"],
            reviewer_path="pl" if kind == "cceo" else "ia",
            school_operating=(row["school__operational_status"] or "")
            not in st.NOT_OPERATING,
            funds_pending=row["id"] in funds,
            closure_owner=_closure_owner(row, closure),
            today=today,
        )
        partner_key = (row["assigned_partner_id"] or "") if partner else STAFF_KEY
        region_id = row["school__region_id"] or row["cluster__district__region_id"]
        district_id = row["school__district_id"] or row["cluster__district_id"]
        executed_day = (
            (row["actual_delivery_date"] or start or due) if stage.executed else None
        )
        verified_day = _local_day(verified_at) if stage.verified else None
        closed_day = (
            _local_day(row["closure_details__closed_at"]) if stage.closed else None
        )
        at_school = bool(row["school_id"]) and not row["cluster_id"]
        kind = (
            rules.visit_kind(
                row["activity_type"],
                row["purpose_type"],
                delivery_type=row["delivery_type"],
            )
            if at_school
            else None
        )
        record = ActivityRecord(
            row["id"],
            row["activity_type"],
            status,
            stage.stage,
            owner_key,
            partner_key,
            "partner" if partner else "staff",
            row["school_id"],
            row["cluster_id"],
            region_id,
            district_id,
            due,
            stage.overdue,
            stage.owner,
            stage.timing,
            stage.age,
            stage.started,
            stage.executed,
            stage.pl_applicable,
            stage.pl_reviewed,
            stage.verified,
            stage.closed,
            stage.returned,
            stage.cancelled,
            stage.finance_open,
            row["id"] in funds,
            (row["payment_status"] or "") in ("paid", "closed"),
            executed_day,
            verified_day,
            closed_day,
            _local_day(row["updated_at"]),
            row["school__school_type"] or "",
            kind or "",
            _is_outreach(row),
            row["actual_delivery_date"],
        )
        records.append(record)
        key = (
            owner_key,
            partner_key,
            record.channel,
            region_id,
            district_id,
            row["activity_type"],
        )
        vector = cells.get(key)
        if vector is None:
            vector = cells[key] = [0] * width
        _add_record(vector, record, stage, buckets)

    for row in moved["moved_rows"]:
        owner_key, _info = owner_of(row)
        partner = row["delivery_type"] == "partner"
        partner_key = (row["assigned_partner_id"] or "") if partner else STAFF_KEY
        region_id = row["school__region_id"] or row["cluster__district__region_id"]
        district_id = row["school__district_id"] or row["cluster__district_id"]
        key = (
            owner_key,
            partner_key,
            "partner" if partner else "staff",
            region_id,
            district_id,
            row["activity_type"],
        )
        vector = cells.get(key)
        if vector is None:
            vector = cells[key] = [0] * width
        vector[IDX["carried_forward"]] += 1

    if any(r.owner_key == NO_OWNER_KEY for r in records) or moved["moved_rows"]:
        owners.setdefault(
            NO_OWNER_KEY, OwnerInfo(key=NO_OWNER_KEY, name=NO_OWNER_LABEL, active=False)
        )

    leads = system_leads()
    rosters = lead_rosters([lead.key for lead in leads])
    from apps.planning.country_oversight.service import _names

    partner_names = _names(
        "partners.Partner",
        {
            r.partner_key
            for r in records
            if r.partner_key and r.partner_key != STAFF_KEY
        },
    )
    region_names = _names("geography.Region", {r.region_id for r in records})
    type_labels = dict(ActivityType.choices)
    integrity = {k: v for k, v in moved.items() if k != "moved_rows"}
    return ExecutionDataset(
        window=window,
        today=today,
        built_at=timezone.now(),
        buckets=buckets,
        records=records,
        cells=cells,
        owners=owners,
        leads=leads,
        rosters=rosters,
        partner_names=partner_names,
        region_names=region_names,
        type_labels=type_labels,
        integrity=integrity,
        scope_label=(getattr(scope, "country", "") or "").strip(),
        universe=universe,
    )


def _add_record(
    vector: list, record: ActivityRecord, stage: st.Stage, buckets: list
) -> None:
    i = IDX
    if record.cancelled:
        vector[i["cancelled"]] += 1
        return
    vector[i["due"]] += 1
    if stage.started:
        vector[i["started"]] += 1
    if stage.executed:
        vector[i["executed"]] += 1
    if stage.pl_applicable:
        vector[i["pl_applicable"]] += 1
    if stage.pl_reviewed:
        vector[i["pl_reviewed"]] += 1
    if stage.verified:
        vector[i["verified"]] += 1
    if stage.closed:
        vector[i["closed"]] += 1
    if stage.returned:
        vector[i["returned"]] += 1
    if stage.overdue:
        vector[i["overdue"]] += 1
        vector[i[f"od_{stage.overdue}"]] += 1
        group = st.age_group(stage.age)
        if group:
            vector[i[group]] += 1
    if stage.finance_open:
        vector[i["finance_open"]] += 1
    if stage.owner:
        vector[i[f"own_{stage.owner}"]] += 1
    if record.funds_pending and not stage.started:
        vector[i["funds_pending"]] += 1
    if record.counted:
        # On the plan as the planning tab reads "planned" (a scheduled-or-later
        # state; a visit sent back to planning is not on it).
        if record.status in policy.PLANNED_STATES:
            vector[i["v_planned"]] += 1
        if stage.executed:
            vector[i["v_delivered"]] += 1
        if stage.verified:
            vector[i["v_verified"]] += 1
    elif record.outreach and record.channel == "staff" and stage.executed:
        vector[i["v_outreach"]] += 1
    timing = stage.timing
    if timing == "on_time":
        vector[i["on_time"]] += 1
    elif timing == "late":
        vector[i["late"]] += 1
    elif timing == "unknown":
        vector[i["start_unknown"]] += 1
    elif timing == "not_started":
        vector[i["not_started"]] += 1
    elif timing == "upcoming":
        vector[i["upcoming"]] += 1
    # The trend: each series counted in the bucket its day falls in.
    count = len(buckets)
    for series, day in enumerate(
        (record.due, record.executed_day, record.verified_day, record.closed_day)
    ):
        if day is None:
            continue
        index = max(0, _bucket_of(day, buckets))
        if index < count:
            vector[BASE_WIDTH + series * count + index] += 1


# ── Money and closure ────────────────────────────────────────────────────────
#: Advance lines waiting on the Accountant to release money.
_AWAITING_DISBURSEMENT = ("confirmed_for_advance", "submitted_to_accountant")


def _funds_pending(activity_ids) -> set:
    """Activities with money requested and not yet disbursed (and none moved)."""
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

    waiting: set = set()
    moved: set = set()
    for activity_id, status in (
        AdvanceRequest.objects.filter(activity_id__in=activity_ids)
        .values_list("activity_id", "status")
        .order_by()
    ):
        if status in _AWAITING_DISBURSEMENT:
            waiting.add(activity_id)
        elif status in MONEY_MOVED_ADVANCE_STATUSES:
            moved.add(activity_id)
    return waiting - moved


def _closure_owners(queryset) -> dict:
    """Verified records' closure blockers: activity id → roles blocking it."""
    from apps.activities.models import ClosureBlocker

    verified_ids = queryset.filter(status__in=st.VERIFIED - st.CLOSED).values("id")
    roles: dict[str, set] = {}
    for activity_id, role in ClosureBlocker.objects.filter(
        activity_id__in=verified_ids
    ).values_list("activity_id", "responsible_role"):
        roles.setdefault(activity_id, set()).add(role or "")
    return roles


def _closure_owner(row: dict, closure: dict) -> str:
    """Who holds a verified record's closure (spec §10, §24)."""
    if row["status"] not in st.VERIFIED or row["status"] in st.CLOSED:
        return ""
    if row["delivery_type"] == "partner" and (row["payment_status"] or "") not in (
        "paid",
        "closed",
    ):
        return "finance"  # Partner payment pending: the Accountant
    roles = closure.get(row["id"], set())
    if "Accountant" in roles:
        return "finance"
    if "ImpactAssessment" in roles and not (roles & {"CCEO"}):
        return "ia"
    return "staff"


# ── The original plan (spec §7) ──────────────────────────────────────────────
def _empty_integrity() -> dict:
    return {
        "tracked": False,
        "tracking_since": None,
        "cutoff": None,
        "original": 0,
        "added": 0,
        "moved_in": 0,
        "moved_out": 0,
        "cancelled": 0,
        "current": 0,
        "moved_rows": [],
    }


def _integrity(scope_q, base_q, window: Window, rows: list[dict]) -> dict:
    """What was due in the window when it began, and what changed since.

    The cutoff is the window's first moment — the plan as it stood when the
    period began (no other cutoff is approved; spec §7 asks it to be
    configurable, and this is the neutral one). Reconstructed from the
    schedule trail, so it is exact for periods that began after the trail did,
    and marked untracked before that.
    """
    from apps.activities.models import Activity, ActivityScheduleChange
    from apps.activities.schedule_trail import tracking_since

    result = _empty_integrity()
    since = tracking_since()
    cutoff = timezone.make_aware(datetime.combine(window.start, datetime.min.time()))
    result["tracking_since"] = since
    result["cutoff"] = cutoff
    live_now = {row["id"] for row in rows if row["status"] not in st.OFF_PLAN}
    result["current"] = len(live_now)
    if since is None or since > cutoff:
        return result
    result["tracked"] = True

    # The first change after the cutoff says where each moved activity was.
    first_after: dict[str, tuple] = {}
    for activity_id, from_day, from_status in (
        ActivityScheduleChange.objects.filter(changed_at__gte=cutoff)
        # Every move that matters touches the window: into it (to_day) or
        # out of it (from_day). A cancellation keeps its day on both sides.
        .filter(
            Q(from_day__gte=window.start, from_day__lt=window.end)
            | Q(to_day__gte=window.start, to_day__lt=window.end)
        )
        .order_by("activity_id", "changed_at")
        .values_list("activity_id", "from_day", "from_status")
    ):
        first_after.setdefault(activity_id, (from_day, from_status))

    def in_window(day) -> bool:
        return day is not None and window.start <= day < window.end

    now_rows = {row["id"]: row for row in rows}
    created = {row["id"]: row["created_at"] for row in rows}
    missing = [pk for pk in first_after if pk not in created]
    if missing:
        created.update(
            Activity.objects.filter(id__in=missing).values_list("id", "created_at")
        )
    original = added = moved_in = moved_out = cancelled = 0
    moved_out_ids: list[str] = []
    for activity_id in set(first_after) | set(now_rows):
        made = created.get(activity_id)
        existed = made is not None and made < cutoff
        if activity_id in first_after:
            was_day, was_status = first_after[activity_id]
            was_live = was_status not in st.OFF_PLAN and was_status not in st.NOT_A_PLAN
        else:
            row = now_rows[activity_id]
            was_day, was_live = row["due_day"], True
        row = now_rows.get(activity_id)
        now_in = row is not None and row["status"] not in st.OFF_PLAN
        was_in = existed and was_live and in_window(was_day)
        if was_in:
            original += 1
            if row is not None and row["status"] in st.OFF_PLAN:
                cancelled += 1
            elif not now_in:
                moved_out += 1
                moved_out_ids.append(activity_id)
        elif now_in:
            if existed:
                moved_in += 1
            else:
                added += 1
        elif row is not None and not existed and row["status"] in st.OFF_PLAN:
            cancelled += 1
    result.update(
        original=original,
        added=added,
        moved_in=moved_in,
        moved_out=moved_out,
        cancelled=cancelled,
    )
    # The moved-out work, for the owner rows' "Carried forward": still live,
    # now due after the window (moved earlier is not carried forward).
    if moved_out_ids and scope_q is not None:
        later = (
            Activity.objects.filter(id__in=moved_out_ids, deleted_at__isnull=True)
            .annotate(due_day=_day())
            .filter(due_day__gte=window.end)
            .filter(scope_q)
        )
        if base_q is not None:
            later = later.filter(base_q)
        result["moved_rows"] = list(later.values(*_COLUMNS, "due_day").order_by())
    return result
