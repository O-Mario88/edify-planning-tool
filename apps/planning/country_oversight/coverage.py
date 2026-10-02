"""PlanningCoverageService — what each school has planned, and which slots it fills.

Read from the canonical records only: the Activity rows every other page
reads, the Partner handovers (PartnerAssignment), the cluster rosters
(ClusterActivityAttendance) and the cluster register. Nothing here is stored.

**Facts, then claims.** One grouped query per source yields, for every
eligible school, how many qualifying activities it has before the selected
window, inside it and in the whole year. Claims are then made per school,
earliest first, and capped at the school's slots — so a school counts once, a
slot counts once, a rescheduled visit is still one visit, and two Partners
sharing a school cannot conjure extra slots.

What fills a visit slot is the planning rulebook's counted visit (``rules``):
In-school Training or Follow up at the school — never a donor,
story, social or invitation visit, and never the companion visit an in-school
training writes beside itself. A staff plan fills a staff slot; Partner work
fills a Partner slot once the PARTNER has dated it, and is *assigned* until
then, whoever else put a date on it.

A Core school's slots are two staff and two Partner, each side its own: a
third staff visit claims nothing (owner, 2026-09-30). A client-rule school has
one slot — staff's if staff planned the school, otherwise the Partner's. A
Champion school has none.

A training slot is filled by a training at the school itself, or by a cluster
session whose *planned roster* names the school — never because the school is
in the cluster. A Core school's four are two staff and two Partner; a cluster
session is staff's. A cluster meeting covers a school the same way.

**Planned twice.** A client-rule school is visited by staff or by a Partner,
never both. Its slot is still claimed once, so a second plan changes no
figure; ``duplicate_reasons`` names the schools where one exists.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import NamedTuple

from django.db.models import Count, Q
from django.db.models.functions import Coalesce, TruncDate

from apps.planning.country_oversight import policy

# ── The window ───────────────────────────────────────────────────────────────
MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


def fy_label(fy: str) -> str:
    """ "2027" → "FY 2026/27": the year a fiscal year starts and ends in."""
    try:
        end = int(fy)
    except (TypeError, ValueError):
        return f"FY {fy}"
    return f"FY {end - 1}/{str(end)[-2:]}"


@dataclass(frozen=True)
class Window:
    """The slice of a fiscal year being read. ``end`` is exclusive."""

    fy: str
    period: str  # "fy" | "quarter" | "month" | "week"
    start: date
    end: date
    fy_start: date
    fy_end: date
    months_of_fy: tuple[int, ...] = ()
    quarter: str | None = None
    month: int | None = None
    week: str | None = None

    @property
    def is_annual(self) -> bool:
        return self.period == "fy"

    @property
    def has_phased_target(self) -> bool:
        """Quarters and months have an approved phasing; a week has none."""
        return self.period in ("quarter", "month")

    @property
    def label(self) -> str:
        if self.period == "quarter":
            return f"{self.quarter} · {fy_label(self.fy)}"
        if self.period == "month":
            return f"{MONTH_NAMES[self.month]} {self.start.year}"
        if self.period == "week":
            return f"Week of {self.start:%-d %b %Y}"
        return fy_label(self.fy)

    @property
    def view_label(self) -> str:
        return {
            "fy": "Annual View",
            "quarter": "Quarterly View",
            "month": "Monthly View",
            "week": "Weekly View",
        }[self.period]

    @property
    def cache_part(self) -> str:
        return (
            f"{self.fy}:{self.period}:{self.start.isoformat()}:{self.end.isoformat()}"
        )


def _fy_month_index(calendar_month: int) -> int:
    return calendar_month - 9 if calendar_month >= 10 else calendar_month + 3


def window_for(
    fy: str,
    period: str = "fy",
    *,
    quarter: str | None = None,
    month: int | None = None,
    week_start: date | None = None,
) -> Window:
    from apps.core.fy import get_fy_date_range, get_quarter_date_range

    fy = str(fy)
    fy_start_dt, fy_end_dt = get_fy_date_range(fy)
    fy_start, fy_end = fy_start_dt.date(), fy_end_dt.date()
    if period == "quarter" and quarter in ("Q1", "Q2", "Q3", "Q4"):
        start_dt, end_dt = get_quarter_date_range(fy, quarter)
        start, end = start_dt.date(), end_dt.date()
        first = _fy_month_index(start.month)
        return Window(
            fy,
            "quarter",
            start,
            end,
            fy_start,
            fy_end,
            months_of_fy=(first, first + 1, first + 2),
            quarter=quarter,
        )
    if period == "month" and month and 1 <= int(month) <= 12:
        month = int(month)
        year = fy_start.year if month >= 10 else fy_end.year
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return Window(
            fy,
            "month",
            start,
            end,
            fy_start,
            fy_end,
            months_of_fy=(_fy_month_index(month),),
            month=month,
        )
    if period == "week" and week_start:
        start = week_start
        return Window(
            fy,
            "week",
            start,
            start + timedelta(days=7),
            fy_start,
            fy_end,
            week=start.strftime("%G-W%V"),
        )
    return Window(
        fy, "fy", fy_start, fy_end, fy_start, fy_end, months_of_fy=tuple(range(1, 13))
    )


# ── Facts ────────────────────────────────────────────────────────────────────
# Positions in a partner's count list. ``P_SSA_T`` is how much of the year's
# Partner work at the school (dated or still waiting) is SSA Support.
(
    P_SCHED_B,
    P_SCHED_I,
    P_SCHED_T,
    P_PEND_B,
    P_PEND_I,
    P_PEND_T,
    P_VERIFIED,
    P_RETURNED,
    P_SSA_T,
) = range(9)
P_WIDTH = 9


@dataclass(slots=True)
class SchoolFacts:
    """One eligible school, and what its records say about the year."""

    id: str
    code: str
    name: str
    school_type: str
    family: str
    owner_key: str
    raw_owner_id: str | None
    region_id: str | None
    district_id: str | None
    cluster_id: str | None  # an ACTIVE cluster, or None
    raw_cluster_id: str | None
    cluster_status: str
    # [before, inside, total, verified inside]
    staff: list = field(default_factory=lambda: [0, 0, 0, 0])
    # partner id → [sched b, sched i, sched t, pending b, pending i, pending t,
    #               verified i, returned i, ssa support t]
    partners: dict | None = None
    # Staff trainings and cluster sessions: [before, inside, total, verified inside]
    training: list = field(default_factory=lambda: [0, 0, 0, 0])
    meeting: list = field(default_factory=lambda: [0, 0, 0])
    # Set from the annual claims, for the owner's allocation.
    annual_staff_claims: int = 0
    annual_holder: str = "open"
    # Trainings a Partner has dated: [before, inside, total, verified inside]
    training_partner: list = field(default_factory=lambda: [0, 0, 0, 0])
    # How many of the year's staff visits are SSA Support (see duplicates).
    staff_ssa: int = 0
    # In a Partner's hands: any live Partner work, a visit or not.
    with_partner: bool = False
    # A Core school's cluster trainings: [before, inside, total, verified
    # inside]. Outside its package (owner, 2026-10-02), so they fill none of
    # its four training slots; they still say the school has training planned.
    session: list = field(default_factory=lambda: [0, 0, 0, 0])

    @property
    def clustered(self) -> bool:
        return self.cluster_id is not None

    @property
    def is_governed(self) -> bool:
        return self.family != policy.UNMAPPED_FAMILY

    def freeze(self, vector: tuple = (), shared: dict | None = None) -> SchoolRecord:
        """The read-only record the dataset keeps once loading is done.

        Repeated values become one object — the same id strings, the same
        count tuples, the same figure vectors — so a cached dataset of 50,000
        schools stores each of them once and reads back several times faster.
        """
        shared = {} if shared is None else shared

        def same(values) -> tuple:
            values = tuple(values)
            return shared.setdefault(values, values)

        return SchoolRecord(
            self.id,
            self.code,
            self.name,
            _intern(self.school_type),
            _intern(self.family),
            _intern(self.owner_key),
            _intern(self.raw_owner_id),
            _intern(self.region_id),
            _intern(self.district_id),
            _intern(self.cluster_id),
            _intern(self.raw_cluster_id),
            _intern(self.cluster_status),
            same(self.staff),
            {_intern(pid): same(counts) for pid, counts in self.partners.items()}
            if self.partners
            else None,
            same(self.training),
            same(self.meeting),
            self.annual_staff_claims,
            _intern(self.annual_holder),
            same(vector),
            same(self.training_partner),
            self.staff_ssa,
            self.with_partner,
            same(self.session),
        )


def _intern(value):
    return sys.intern(value) if isinstance(value, str) else value


class SchoolRecord(NamedTuple):
    """One school's facts once the dataset is built: read-only and cheap to keep.

    The fields of SchoolFacts (which is only the loading form), plus
    ``vector``: the school's figures with no channel or Partner filter, so a
    list of schools can be filtered and sorted by a gap without re-reading
    every school's claims. Everything that reads a school reads it by name, so
    either form serves.
    """

    id: str
    code: str
    name: str
    school_type: str
    family: str
    owner_key: str
    raw_owner_id: str | None
    region_id: str | None
    district_id: str | None
    cluster_id: str | None
    raw_cluster_id: str | None
    cluster_status: str
    staff: tuple
    partners: dict | None
    training: tuple
    meeting: tuple
    annual_staff_claims: int
    annual_holder: str
    vector: tuple = ()
    training_partner: tuple = (0, 0, 0, 0)
    staff_ssa: int = 0
    with_partner: bool = False
    session: tuple = (0, 0, 0, 0)

    @property
    def clustered(self) -> bool:
        return self.cluster_id is not None

    @property
    def is_governed(self) -> bool:
        return self.family != policy.UNMAPPED_FAMILY


class FactsTable(dict):
    """school id → SchoolRecord, pickled as plain rows.

    A NamedTuple is rebuilt through a Python call per school when it is
    unpickled; plain tuples are not, and turning them back into records is a
    single C call each. For the dataset a cached page reads that is the
    difference between ~90 ms and ~65 ms at 50,000 schools — and against the
    mutable loading form, ~190 ms.
    """

    __slots__ = ()

    def __reduce__(self):
        return (_facts_table, ([tuple(record) for record in self.values()],))


def _facts_table(rows) -> FactsTable:
    make = tuple.__new__
    return FactsTable((row[0], make(SchoolRecord, row)) for row in rows)


def _day(prefix: str = ""):
    return Coalesce(f"{prefix}planned_date", TruncDate(f"{prefix}scheduled_date"))


def _counts(
    window: Window,
    *,
    verified: bool = False,
    field_name: str = "day",
    status_field: str = "status",
):
    inside = Q(**{f"{field_name}__gte": window.start, f"{field_name}__lt": window.end})
    aggregates = {
        "before": Count("id", filter=Q(**{f"{field_name}__lt": window.start})),
        "inside": Count("id", filter=inside),
        "total": Count("id"),
    }
    if verified:
        aggregates["verified"] = Count(
            "id",
            filter=inside & Q(**{f"{status_field}__in": policy.VERIFIED_STATES}),
        )
    return aggregates


def visit_claim_q() -> Q:
    """The activities that fill a visit slot: the rulebook's counted visits."""
    from apps.planning.country_oversight import rules

    return rules.counted_visit_q()


def _ssa_count():
    """How many of the counted visits are SSA Support, the client rule's
    second yearly count."""
    from apps.planning.country_oversight import rules

    return Count("id", filter=rules.kind_q(rules.KIND_SSA))


def _planned_activities(fy: str):
    from apps.activities.models import Activity

    return (
        Activity.objects.filter(
            fy=str(fy), deleted_at__isnull=True, status__in=policy.PLANNED_STATES
        )
        .annotate(day=_day())
        .filter(day__isnull=False)
    )


def _roster(fy: str, activity_types):
    from apps.activities.models import ClusterActivityAttendance

    return (
        ClusterActivityAttendance.objects.filter(
            invited=True,
            activity__fy=str(fy),
            activity__deleted_at__isnull=True,
            activity__status__in=policy.PLANNED_STATES,
            activity__activity_type__in=activity_types,
            activity__cluster__isnull=False,
        )
        .annotate(day=_day("activity__"))
        .filter(day__isnull=False)
    )


def load_facts(
    school_rows,
    window: Window,
    *,
    school_ids,
    active_cluster_ids=None,
    owner_as_of: dict | None = None,
    type_as_of: dict | None = None,
) -> dict[str, SchoolFacts]:
    """Every eligible school's facts for the window, in a fixed handful of
    grouped queries whatever the size of the estate.

    ``school_rows`` are (id, code, name, type, owner, region, district,
    cluster, cluster_status) tuples; ``school_ids`` is the same set as a
    queryset or a list, used as a subquery by every read below.
    """
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.clusters.models import Cluster

    owner_as_of = owner_as_of or {}
    type_as_of = type_as_of or {}
    if active_cluster_ids is None:
        active_cluster_ids = set(
            Cluster.objects.filter(status="active").values_list("id", flat=True)
        )

    facts: dict[str, SchoolFacts] = {}
    for (
        pk,
        code,
        name,
        school_type,
        owner,
        region_id,
        district_id,
        cluster_id,
        cluster_status,
    ) in school_rows:
        school_type = type_as_of.get(pk) or school_type or ""
        owner = owner_as_of.get(pk, owner)
        facts[pk] = SchoolFacts(
            id=pk,
            code=code or "",
            name=name or "",
            school_type=school_type,
            family=policy.family_of(school_type),
            owner_key="",
            raw_owner_id=owner or None,
            region_id=region_id,
            district_id=district_id,
            cluster_id=cluster_id if cluster_id in active_cluster_ids else None,
            raw_cluster_id=cluster_id,
            cluster_status=cluster_status or "",
        )
    if not facts:
        return facts

    from apps.planning.country_oversight import rules

    fy = window.fy
    planned = _planned_activities(fy).filter(school_id__in=school_ids)
    counted = visit_claim_q()

    # Staff visits that count.
    for row in (
        planned.filter(counted & rules.staff_delivery_q())
        .values("school_id")
        .annotate(**_counts(window, verified=True), ssa=_ssa_count())
        .order_by()
    ):
        school = facts.get(row["school_id"])
        if school is None:
            continue
        school.staff[0] += row["before"]
        school.staff[1] += row["inside"]
        school.staff[2] += row["total"]
        school.staff[3] += row["verified"]
        school.staff_ssa += row["ssa"]

    # Partner visits: planned once the Partner has dated them, assigned until
    # then — including work moved onto a Partner as an activity, which the
    # reassign path writes no handover for (owner, 2026-09-29), and a day
    # staff chose for the Partner (owner, 2026-10-01).
    _load_partner_activities(facts, window, school_ids)

    # Trainings at the school itself: one slot per training. Staff's, and a
    # Partner's once the Partner has dated it.
    school_trainings = planned.filter(
        activity_type__in=SCHOOL_TRAINING_TYPES, cluster__isnull=True
    )
    for attribute, mine in (
        ("training", rules.staff_delivery_q()),
        ("training_partner", rules.partner_planned_q()),
    ):
        for row in (
            school_trainings.filter(mine)
            .values("school_id")
            .annotate(**_counts(window, verified=True))
            .order_by()
        ):
            _add(facts.get(row["school_id"]), attribute, row)

    # Cluster trainings and meetings: one slot per school on the planned roster.
    cluster_trainings = tuple(
        t for t in TRAINING_TYPES if t not in SCHOOL_TRAINING_TYPES
    )
    for attribute, types in (
        ("training", cluster_trainings),
        ("meeting", CLUSTER_MEETING_TYPES),
    ):
        for row in (
            _roster(fy, types)
            .filter(school_id__in=school_ids)
            .values("school_id")
            .annotate(
                **_counts(
                    window,
                    verified=attribute == "training",
                    status_field="activity__status",
                )
            )
            .order_by()
        ):
            school = facts.get(row["school_id"])
            if (
                attribute == "training"
                and school is not None
                and school.family == policy.CORE_FAMILY
            ):
                # Outside a Core school's package: the four trainings there
                # are in-school trainings (owner, 2026-10-02).
                attribute_for = "session"
            else:
                attribute_for = attribute
            _add(school, attribute_for, row)

    _load_handovers(facts, window, school_ids)
    return facts


def _load_partner_activities(
    facts: dict[str, SchoolFacts], window: Window, school_ids
) -> None:
    """Every live Partner activity at the schools, in one grouped read.

    A counted visit the Partner dated is *scheduled*; any other counted visit
    in the Partner's hands is *pending* — undated work is outstanding from the
    year's first day. Work that is not a counted visit (a training, other
    support) still puts the school in the Partner's hands. An activity that an
    open handover already carries is read there instead.
    """
    from django.db.models import Case, IntegerField, Value, When

    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules

    carried = PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        source_activity_id__isnull=False,
    ).values("source_activity_id")
    inside = Q(day__gte=window.start, day__lt=window.end)
    undated_inside = window.start <= window.fy_start < window.end
    held = (
        Activity.objects.filter(
            fy=str(window.fy), deleted_at__isnull=True, school_id__in=school_ids
        )
        .filter(rules.partner_held_q())
        # Data collection is assigned on any school and counts nowhere: it
        # does not put a school in a Partner's hands (owner, 2026-10-02).
        .exclude(rules.data_collection_q())
        # Alumni work does not put a school in a Partner's hands.
        .filter(rules.not_outside_ssa_q())
        .exclude(id__in=carried)
        .annotate(
            day=_day(),
            dated=Case(
                When(rules.partner_planned_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            counts=Case(
                When(visit_claim_q(), then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
    )
    rows = (
        held.values("school_id", "assigned_partner_id", "dated", "counts")
        .annotate(
            before=Count("id", filter=Q(day__lt=window.start)),
            inside=Count("id", filter=inside),
            undated=Count("id", filter=Q(day__isnull=True)),
            total=Count("id"),
            verified=Count("id", filter=inside & Q(status__in=policy.VERIFIED_STATES)),
            ssa=_ssa_count(),
        )
        .order_by()
    )
    for row in rows:
        school = facts.get(row["school_id"])
        if school is None or not school.is_governed:
            continue
        school.with_partner = True
        if not row["counts"]:
            continue
        counts = _partner_counts(school, row["assigned_partner_id"] or "")
        counts[P_SSA_T] += row["ssa"]
        if row["dated"]:
            counts[P_SCHED_B] += row["before"]
            counts[P_SCHED_I] += row["inside"]
            counts[P_SCHED_T] += row["total"]
            counts[P_VERIFIED] += row["verified"]
        else:
            counts[P_PEND_B] += row["before"]
            counts[P_PEND_I] += row["inside"] + (
                row["undated"] if undated_inside else 0
            )
            counts[P_PEND_T] += row["total"]


def _is_ssa_handover(handover) -> bool:
    from apps.planning.country_oversight import rules

    kind = rules.visit_kind(
        handover.expected_activity_type or "school_visit", handover.purpose_of_visit
    )
    return kind == rules.KIND_SSA


def _add(school, attribute: str, row) -> None:
    if school is None:
        return
    counts = getattr(school, attribute)
    counts[0] += row["before"]
    counts[1] += row["inside"]
    counts[2] += row["total"]
    if len(counts) > 3:
        counts[3] += row.get("verified", 0)


def _partner_counts(school: SchoolFacts, partner_id: str) -> list:
    if school.partners is None:
        school.partners = {}
    return school.partners.setdefault(partner_id, [0] * P_WIDTH)


class _Handover:
    """The columns ``package_credit.assignment_kind`` reads, as attributes."""

    __slots__ = (
        "support_type",
        "visit_number",
        "training_number",
        "project_id",
        "expected_activity_type",
        "purpose_of_visit",
    )

    def __init__(self, *values):
        for name, value in zip(self.__slots__, values):
            setattr(self, name, value)


def handover_kind(school_type: str, handover) -> str | None:
    """ "visit" or "training" for a Partner handover at a school of this type."""
    from apps.core_schools.package_credit import PACKAGE_TRAINING_TYPES, assignment_kind

    from apps.planning.country_oversight import rules

    if rules.is_data_collection(
        handover.expected_activity_type, handover.purpose_of_visit
    ):
        return None
    if school_type == "core":
        return assignment_kind(handover)
    expected = str(handover.expected_activity_type or "")
    if expected in PACKAGE_TRAINING_TYPES or expected == "in_school_training":
        return "training"
    return "visit"


def _bucket(day: date, window: Window) -> int:
    if day < window.start:
        return 0
    if day < window.end:
        return 1
    return 2


def _load_handovers(facts: dict[str, SchoolFacts], window: Window, school_ids) -> None:
    """Partner handovers not yet dated (assigned) and handed back (returned).

    A handover carries no fiscal year. One still waiting for its Partner's
    date is a school assigned to that Partner today, whichever year it was
    made in — Partner Oversight's rule (owner, 2026-09-28: "show exactly the
    number of schools assigned to the partner"). So it is read in every year
    from the one it was made in, and in a later year it counts from that
    year's first day. Filed under its creation year alone, a handover made in
    September for October's work vanished from the planning year the Country
    Director was reading, and the Partner Assigned column read nothing while
    the Partner held the school (owner, 2026-09-29). A returned one is read
    in the year it came back. A dated handover is not read here at all: the
    activity it became is the record, which is what keeps one piece of work
    from counting twice.
    """
    from apps.core.fy import get_operational_fy
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules

    rows = (
        PartnerAssignment.objects.filter(
            school_id__in=school_ids,
            status__in=(
                *PartnerAssignment.UNSCHEDULED_STATUSES,
                PartnerAssignment.STATUS_RETURNED_TO_STAFF,
            ),
        )
        # Nor does a hand-over of Alumni work (rules.not_outside_ssa_q).
        .filter(rules.not_outside_ssa_q())
        .values_list(
            "school_id",
            "partner_id",
            "status",
            "created_at",
            "returned_at",
            "support_type",
            "visit_number",
            "training_number",
            "project_id",
            "expected_activity_type",
            "purpose_of_visit",
        )
    )
    for (
        school_id,
        partner_id,
        status,
        created_at,
        returned_at,
        *kind_fields,
    ) in rows:
        school = facts.get(school_id)
        if school is None or not school.is_governed:
            continue
        handover = _Handover(*kind_fields)
        if rules.is_data_collection(
            handover.expected_activity_type, handover.purpose_of_visit
        ):
            # Assigned and listed; it puts no school in a Partner's hands
            # and counts nowhere (owner, 2026-10-02).
            continue
        is_visit = handover_kind(school.school_type, handover) == "visit"
        if status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
            moment = returned_at or created_at
            if moment is None or get_operational_fy(moment) != window.fy:
                continue
            if is_visit and _bucket(_local_day(moment), window) == 1:
                _partner_counts(school, partner_id or "")[P_RETURNED] += 1
            continue
        if created_at is None or int(get_operational_fy(created_at)) > int(window.fy):
            continue
        # Any open handover, a visit or a training, is a school in a
        # Partner's hands (owner, 2026-10-01: capture every one).
        school.with_partner = True
        if not is_visit:
            continue
        counts = _partner_counts(school, partner_id or "")
        # Carried into a later year, it is outstanding from the year's start.
        where = _bucket(max(_local_day(created_at), window.fy_start), window)
        counts[P_PEND_T] += 1
        if _is_ssa_handover(handover):
            counts[P_SSA_T] += 1
        if where == 0:
            counts[P_PEND_B] += 1
        elif where == 1:
            counts[P_PEND_I] += 1


def _local_day(moment: datetime) -> date:
    from django.utils import timezone

    if timezone.is_aware(moment):
        return timezone.localtime(moment).date()
    return moment.date()


# ── Claims ───────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Claims:
    """The slots one school's plan fills, in the window and in the year."""

    visit_slots: int = 0
    staff_expected: int = 0
    partner_expected: int = 0
    deficit: int = 0
    training_slots: int = 0
    # Window claims.
    staff: int = 0
    staff_core: int = 0
    staff_client: int = 0
    partner_assigned: int = 0
    partner_scheduled: int = 0
    staff_verified: int = 0
    partner_verified: int = 0
    training: int = 0
    training_verified: int = 0
    meeting_covered: bool = False
    # Claims up to the window's end (the year so far).
    cum_staff: int = 0
    cum_partner_assigned: int = 0
    cum_partner_scheduled: int = 0
    cum_training: int = 0
    cum_meeting_covered: bool = False
    # Raw presence in the window, for unique-school counts.
    any_staff: bool = False
    any_partner_scheduled: bool = False
    any_partner_assigned: bool = False
    any_training: bool = False
    returned: int = 0
    # Per Partner: id → [assigned, scheduled, verified, returned] in the window.
    by_partner: dict | None = None
    # Annual-basis gaps against the school's expected channels.
    staff_gap: int = 0
    partner_gap: int = 0
    # A school the requirement asks nothing of (a Champion): it has no
    # planning state and is in no "not yet planned" count.
    outside: bool = False

    @property
    def planned(self) -> int:
        return self.staff + self.partner_scheduled

    @property
    def unallocated(self) -> int:
        return max(0, self.visit_slots - self.staff - self.partner_assigned)

    @property
    def training_gap(self) -> int:
        return max(0, self.training_slots - self.training)


def duplicate_reasons(school) -> tuple[str, ...]:
    """Why a school's year is planned more often than it should be, if it is:
    the rulebook's reasons (``rules.duplicate_reasons``), from the year's
    counts. A Partner's side includes work it has not dated yet."""
    from apps.planning.country_oversight import rules

    if school.family not in (policy.CLIENT_FAMILY, policy.CORE_FAMILY):
        return ()
    staff_all, staff_ssa = school.staff[2], school.staff_ssa
    partner_all = partner_ssa = 0
    for counts in (school.partners or {}).values():
        partner_all += counts[P_SCHED_T] + counts[P_PEND_T]
        partner_ssa += counts[P_SSA_T]
    return rules.duplicate_reasons(
        school.school_type,
        {rules.POOL_SSA: staff_ssa, rules.POOL_SUPPORT: staff_all - staff_ssa},
        {rules.POOL_SSA: partner_ssa, rules.POOL_SUPPORT: partner_all - partner_ssa},
    )


def _partner_totals(school: SchoolFacts, only_partner: str | None) -> tuple[list, dict]:
    totals = [0] * P_WIDTH
    kept: dict = {}
    for partner_id, counts in (school.partners or {}).items():
        if only_partner is not None and partner_id != only_partner:
            continue
        kept[partner_id] = counts
        for index, value in enumerate(counts):
            totals[index] += value
    return totals, kept


def annual_position(school: SchoolFacts, *, only_partner: str | None = None) -> None:
    """Record the school's annual staff claims and slot holder for allocation."""
    requirement = policy.requirement_for(school.family)
    p, _ = _partner_totals(school, only_partner)
    st = school.staff[2]
    if school.family == policy.CORE_FAMILY:
        partner_cap = requirement.partner_visit_slots
        assigned = min(p[P_SCHED_T] + p[P_PEND_T], partner_cap)
        school.annual_staff_claims = min(st, requirement.staff_visit_slots)
        school.annual_holder = "staff" if st else ("partner" if assigned else "open")
    elif school.family == policy.CLIENT_FAMILY:
        school.annual_staff_claims = min(st, requirement.flexible_visit_slots)
        if st:
            school.annual_holder = "staff"
        elif p[P_SCHED_T] or p[P_PEND_T]:
            school.annual_holder = "partner"
        else:
            school.annual_holder = "open"
    else:
        school.annual_staff_claims = 0
        school.annual_holder = "open"


def _first_in(before: int, inside: int) -> int:
    """1 when a one-slot claim is first made inside the window."""
    return 1 if before == 0 and inside > 0 else 0


def claims_for(
    school: SchoolFacts,
    allocation,
    window: Window,
    *,
    channel: str | None = None,
    only_partner: str | None = None,
) -> Claims:
    """The school's claims. ``channel`` ("staff"/"partner") reads one delivery
    channel only; ``only_partner`` reads one Partner's work only."""
    requirement = policy.requirement_for(school.family)
    claims = Claims()
    if not school.is_governed:
        return claims

    staff_counts = school.staff if channel != "partner" else [0, 0, 0, 0]
    p, partners = (
        _partner_totals(school, only_partner)
        if channel != "staff"
        else ([0] * P_WIDTH, {})
    )
    staff_expected = allocation.staff if channel != "partner" else 0
    partner_expected = allocation.partner if channel != "staff" else 0
    claims.visit_slots = staff_expected + partner_expected
    claims.staff_expected = staff_expected
    claims.partner_expected = partner_expected
    claims.deficit = allocation.deficit if channel != "partner" else 0

    sb, si, st, sv = staff_counts
    claims.returned = p[P_RETURNED]

    if school.family == policy.CORE_FAMILY:
        claims.any_staff = si > 0
        claims.any_partner_scheduled = p[P_SCHED_I] > 0
        claims.any_partner_assigned = (p[P_SCHED_I] + p[P_PEND_I]) > 0
        cap = requirement.partner_visit_slots if channel != "staff" else 0
        sched_b = min(p[P_SCHED_B], cap)
        claims.partner_scheduled = min(p[P_SCHED_I], cap - sched_b)
        assigned_b = min(p[P_SCHED_B] + p[P_PEND_B], cap)
        claims.partner_assigned = max(
            claims.partner_scheduled,
            min(p[P_SCHED_I] + p[P_PEND_I], cap - assigned_b),
        )
        # Two staff and two Partner, each side its own (owner, 2026-09-30):
        # a third staff visit fills no Partner slot and claims nothing.
        staff_slots = requirement.staff_visit_slots if channel != "partner" else 0
        staff_b = min(sb, staff_slots)
        claims.staff = min(si, staff_slots - staff_b)
        claims.staff_core = claims.staff
        claims.cum_staff = staff_b + claims.staff
        claims.cum_partner_scheduled = sched_b + claims.partner_scheduled
        claims.cum_partner_assigned = assigned_b + claims.partner_assigned
    elif school.family == policy.CLIENT_FAMILY:
        claims.any_staff = si > 0
        claims.any_partner_scheduled = p[P_SCHED_I] > 0
        claims.any_partner_assigned = (p[P_SCHED_I] + p[P_PEND_I]) > 0
        # One flexible slot: staff hold it if they plan the school at all,
        # else the Partner who dated it, else the Partner it was handed to.
        # A channel filter reads the holder's claim or nothing: it never hands
        # a slot staff hold to a Partner, so a Partner's work there claims no
        # slot on the Partner view either (read the school's own staff plan,
        # not the channel's zeroed copy).
        if school.staff[2]:
            if channel != "partner":
                claims.staff = _first_in(sb, si)
                claims.cum_staff = 1 if (sb + si) else 0
        elif (p[P_SCHED_T] or p[P_PEND_T]) and channel != "staff":
            claims.partner_scheduled = _first_in(p[P_SCHED_B], p[P_SCHED_I])
            claims.partner_assigned = max(
                claims.partner_scheduled,
                _first_in(p[P_SCHED_B] + p[P_PEND_B], p[P_SCHED_I] + p[P_PEND_I]),
            )
            claims.cum_partner_scheduled = 1 if (p[P_SCHED_B] + p[P_SCHED_I]) else 0
            claims.cum_partner_assigned = (
                1 if (p[P_SCHED_B] + p[P_SCHED_I] + p[P_PEND_B] + p[P_PEND_I]) else 0
            )
        claims.staff_client = claims.staff
        # A flexible slot is one slot, whoever holds it.
        claims.visit_slots = min(claims.visit_slots, requirement.flexible_visit_slots)
    else:
        # Outreach only: the requirement asks nothing of this school.
        claims.outside = True

    claims.staff_verified = min(sv, claims.staff)
    claims.partner_verified = min(p[P_VERIFIED], claims.partner_scheduled)

    # Training and meeting coverage do not depend on the delivery channel.
    # A Core school's four trainings are two staff and two Partner; a
    # client-rule school's one is anybody's. A cluster session is staff's.
    staff_need, partner_need, either_need = policy.training_slots_for(
        school.school_type
    )
    claims.training_slots = staff_need + partner_need + either_need
    tb, ti, _tt, tv = school.training
    pb, pi, _pt, pv = school.training_partner
    if either_need:
        before = min(tb + pb, either_need)
        claims.training = min(ti + pi, either_need - before)
    else:
        staff_before, partner_before = min(tb, staff_need), min(pb, partner_need)
        before = staff_before + partner_before
        claims.training = min(ti, staff_need - staff_before) + min(
            pi, partner_need - partner_before
        )
    claims.cum_training = before + claims.training
    # Verified inside the window, never more than the window's claims.
    claims.training_verified = min(tv + pv, claims.training)
    # A Core school on a cluster training's list has training planned, though
    # the session fills none of its package's slots.
    claims.any_training = (
        bool(claims.training_slots) and (ti + pi + school.session[1]) > 0
    )
    mb, mi, _ = school.meeting
    claims.meeting_covered = mi > 0
    claims.cum_meeting_covered = (mb + mi) > 0

    # Gaps are read against the channel each slot is expected from. A staff
    # plan closes a staff slot; a Partner closes its own first, then a
    # client-rule slot staff were expected to take and handed over instead.
    staff_on_staff = min(claims.cum_staff, staff_expected)
    partner_on_partner = min(claims.cum_partner_assigned, partner_expected)
    partner_on_staff = claims.cum_partner_assigned - partner_on_partner
    staff_on_partner = claims.cum_staff - staff_on_staff
    claims.staff_gap = max(0, staff_expected - staff_on_staff - partner_on_staff)
    claims.partner_gap = max(
        0, partner_expected - partner_on_partner - staff_on_partner
    )

    if partners:
        claims.by_partner = _split_between_partners(
            partners, claims.partner_assigned, claims.partner_scheduled
        )
    return claims


def _split_between_partners(partners: dict, assigned: int, scheduled: int) -> dict:
    """Share a school's Partner claims between the Partners holding it, so
    Partner rows add up to the school rather than each claiming the slots."""
    order = sorted(
        partners.items(),
        key=lambda item: (
            -item[1][P_SCHED_I],
            -(item[1][P_SCHED_I] + item[1][P_PEND_I]),
            item[0],
        ),
    )
    left_assigned, left_scheduled = assigned, scheduled
    shares: dict = {}
    for partner_id, counts in order:
        take_assigned = min(counts[P_SCHED_I] + counts[P_PEND_I], left_assigned)
        take_scheduled = min(counts[P_SCHED_I], left_scheduled, take_assigned)
        left_assigned -= take_assigned
        left_scheduled -= take_scheduled
        shares[partner_id] = [
            take_assigned,
            take_scheduled,
            min(counts[P_VERIFIED], take_scheduled),
            counts[P_RETURNED],
        ]
    return shares


# ── Requirement slots, one school at a time ──────────────────────────────────
@dataclass
class SlotRow:
    """One requirement slot and the record that fills it, if any."""

    label: str
    kind: str  # "visit" | "training" | "meeting" | "beyond"
    expected: str  # "Staff" | "Partner" | "Staff or Partner" | ""
    state: str  # "planned" | "verified" | "assigned" | "open" | "beyond" | "cover"
    activity_id: str | None = None
    activity_type: str = ""
    day: date | None = None
    status: str = ""
    who: str = ""
    note: str = ""


def school_slots(school: SchoolFacts, allocation, window: Window) -> list[SlotRow]:
    """The school's requirement slots for the year and what fills each.

    The read model behind the drill-down's last two levels (slot → linked
    activity). Built from the same records and the same claim order as the
    counts, earliest first. Anything beyond the slots claims nothing and is
    listed as such, so a duplicate is visible rather than double counted.
    """
    from django.db.models import Case, IntegerField, Value, When

    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.activities.models import Activity
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.core.fy import get_operational_fy
    from apps.partners.models import Partner, PartnerAssignment
    from apps.planning.country_oversight import rules

    requirement = policy.requirement_for(school.family)
    if not school.is_governed:
        return []
    fy = window.fy
    columns = (
        "id",
        "activity_type",
        "status",
        "day",
        "delivery_type",
        "assigned_partner_id",
        "delivery_contact_name",
        "responsible_staff_id",
    )
    dated_by_partner = Case(
        When(rules.partner_planned_q(), then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    visits = list(
        _planned_activities(fy)
        .filter(school_id=school.id)
        .filter(visit_claim_q())
        .annotate(dated=dated_by_partner)
        .order_by("day", "created_at", "id")
        .values(*columns, "dated")
    )
    staff_rows = [v for v in visits if v["delivery_type"] != "partner"]
    partner_rows = [v for v in visits if v["delivery_type"] == "partner" and v["dated"]]

    # In a Partner's hands and not dated by it: work moved to the Partner as
    # an activity, a day staff chose for it, and handovers still waiting.
    carried = PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        source_activity_id__isnull=False,
    ).values("source_activity_id")
    waiting = [
        {"partner_id": row["assigned_partner_id"]}
        for row in Activity.objects.filter(
            fy=str(fy), deleted_at__isnull=True, school_id=school.id
        )
        .filter(rules.partner_held_q() & visit_claim_q())
        .exclude(rules.partner_planned_q())
        .exclude(id__in=carried)
        .order_by("created_at")
        .values("assigned_partner_id")
    ]
    for row in (
        PartnerAssignment.objects.filter(
            school_id=school.id, status__in=PartnerAssignment.UNSCHEDULED_STATUSES
        )
        .order_by("created_at")
        .values(
            "partner_id",
            "created_at",
            "support_type",
            "visit_number",
            "training_number",
            "project_id",
            "expected_activity_type",
            "purpose_of_visit",
        )
    ):
        handover = _Handover(
            row["support_type"],
            row["visit_number"],
            row["training_number"],
            row["project_id"],
            row["expected_activity_type"],
            row["purpose_of_visit"],
        )
        if handover_kind(school.school_type, handover) != "visit":
            continue
        created = row["created_at"]
        if created is None or int(get_operational_fy(created)) > int(fy):
            continue
        waiting.append({"partner_id": row["partner_id"]})

    partner_names = dict(
        Partner.objects.filter(
            id__in={v["assigned_partner_id"] for v in visits}
            | {w["partner_id"] for w in waiting}
        ).values_list("id", "name")
    )
    staff_names = _staff_names({v["responsible_staff_id"] for v in visits})

    def filled(label, kind, expected, row, *, state=None, note=""):
        verified = row["status"] in policy.VERIFIED_STATES
        who = (
            partner_names.get(row["assigned_partner_id"], "Partner")
            + (
                f" · {row['delivery_contact_name']}"
                if row.get("delivery_contact_name")
                else ""
            )
            if row["delivery_type"] == "partner"
            else staff_names.get(row["responsible_staff_id"] or "", "Staff")
        )
        return SlotRow(
            label,
            kind,
            expected,
            state or ("verified" if verified else "planned"),
            activity_id=row["id"],
            activity_type=row["activity_type"],
            day=row["day"],
            status=row["status"],
            who=who,
            note=note,
        )

    def assigned(label, expected, entry):
        return SlotRow(
            label,
            "visit",
            expected,
            "assigned",
            who=partner_names.get(entry["partner_id"], "Partner"),
            note="Assigned, not yet scheduled by the Partner",
        )

    def beyond_row(row, note="Claims no slot"):
        return filled(
            "Beyond the requirement", "beyond", "", row, state="beyond", note=note
        )

    slots: list[SlotRow] = []
    beyond: list[SlotRow] = []
    if school.family == policy.CORE_FAMILY:
        staff_slots = requirement.staff_visit_slots
        partner_slots = requirement.partner_visit_slots
        for index in range(staff_slots):
            label = f"Core Staff Visit {index + 1}"
            slots.append(
                filled(label, "visit", "Staff", staff_rows[index])
                if index < len(staff_rows)
                else SlotRow(label, "visit", "Staff", "open")
            )
        dated = partner_rows[:partner_slots]
        for index in range(partner_slots):
            label = f"Core Partner Visit {index + 1}"
            if index < len(dated):
                slots.append(filled(label, "visit", "Partner", dated[index]))
            elif index - len(dated) < len(waiting):
                slots.append(assigned(label, "Partner", waiting[index - len(dated)]))
            else:
                slots.append(SlotRow(label, "visit", "Partner", "open"))
        beyond += [
            beyond_row(row)
            for row in staff_rows[staff_slots:] + partner_rows[partner_slots:]
        ]
    elif school.family == policy.CLIENT_FAMILY:
        expected = "Staff" if getattr(allocation, "staff", 0) else "Partner"
        label = "Visit 1"
        twice = "Planned twice: this school has one visit a year"
        if staff_rows:
            slots.append(filled(label, "visit", expected, staff_rows[0]))
            rest = staff_rows[1:] + partner_rows
        elif partner_rows:
            slots.append(filled(label, "visit", expected, partner_rows[0]))
            rest = partner_rows[1:]
        elif waiting:
            slots.append(assigned(label, expected, waiting[0]))
            rest = []
        else:
            slots.append(SlotRow(label, "visit", expected, "open"))
            rest = []
        reasons = duplicate_reasons(school)
        beyond += [
            beyond_row(row, twice if reasons else "Claims no slot") for row in rest
        ]
    else:
        # Outreach only: no slots, and whatever was planned is listed.
        beyond += [beyond_row(row) for row in staff_rows + partner_rows]

    # Training slots: trainings at the school and sessions naming it.
    training_columns = (*columns, "dated")
    trainings = list(
        _planned_activities(fy)
        .filter(
            school_id=school.id,
            activity_type__in=SCHOOL_TRAINING_TYPES,
            cluster__isnull=True,
        )
        .annotate(dated=dated_by_partner)
        .values(*training_columns)
    )
    cluster_trainings = tuple(
        t for t in TRAINING_TYPES if t not in SCHOOL_TRAINING_TYPES
    )
    for row in (
        _roster(fy, cluster_trainings)
        .filter(school_id=school.id)
        .values(
            "activity_id",
            "activity__activity_type",
            "activity__status",
            "day",
            "activity__delivery_type",
            "activity__assigned_partner_id",
            "activity__responsible_staff_id",
            "activity__cluster__name",
        )
    ):
        trainings.append(
            {
                "id": row["activity_id"],
                "activity_type": row["activity__activity_type"],
                "status": row["activity__status"],
                "day": row["day"],
                # A cluster session is staff's, whoever facilitates it.
                "delivery_type": "staff",
                "assigned_partner_id": row["activity__assigned_partner_id"],
                "delivery_contact_name": "",
                "responsible_staff_id": row["activity__responsible_staff_id"],
                "cluster": row["activity__cluster__name"],
                "dated": 0,
            }
        )
    trainings.sort(key=lambda row: (row["day"], row["id"]))
    outside_package = []
    if school.family == policy.CORE_FAMILY:
        # Outside a Core package (owner, 2026-10-02): listed, in no slot.
        outside_package = [t for t in trainings if t.get("cluster")]
        trainings = [t for t in trainings if not t.get("cluster")]
    staff_names.update(
        _staff_names({t["responsible_staff_id"] for t in trainings + outside_package})
    )
    partner_names.update(
        Partner.objects.filter(
            id__in={t["assigned_partner_id"] for t in trainings} - set(partner_names)
        ).values_list("id", "name")
    )
    staff_trainings = [t for t in trainings if t["delivery_type"] != "partner"]
    partner_trainings = [
        t for t in trainings if t["delivery_type"] == "partner" and t["dated"]
    ]

    def training_row(label, expected, row):
        return filled(
            label,
            "training",
            expected,
            row,
            note=f"Cluster session · {row['cluster']}" if row.get("cluster") else "",
        )

    staff_need, partner_need, either_need = policy.training_slots_for(
        school.school_type
    )
    if either_need:
        everyone = sorted(
            staff_trainings + partner_trainings, key=lambda row: (row["day"], row["id"])
        )
        groups = [("Training", "", everyone, either_need)]
    else:
        groups = [
            ("Staff Training", "Staff", staff_trainings, staff_need),
            ("Partner Training", "Partner", partner_trainings, partner_need),
        ]
    for name, expected, rows, need in groups:
        for index in range(need):
            label = f"{name} {index + 1}"
            slots.append(
                training_row(label, expected, rows[index])
                if index < len(rows)
                else SlotRow(label, "training", expected, "open")
            )
        beyond += [beyond_row(row) for row in rows[need:]]
    beyond += [
        beyond_row(
            row, note=f"Cluster session · {row['cluster']} · outside the package"
        )
        for row in outside_package
    ]

    meetings = list(
        _roster(fy, CLUSTER_MEETING_TYPES)
        .filter(school_id=school.id)
        .order_by("day")
        .values(
            "activity_id",
            "activity__activity_type",
            "activity__status",
            "day",
            "activity__cluster__name",
        )
    )
    if meetings:
        first = meetings[0]
        slots.append(
            SlotRow(
                "Cluster meeting",
                "meeting",
                "",
                "verified"
                if first["activity__status"] in policy.VERIFIED_STATES
                else "planned",
                activity_id=first["activity_id"],
                activity_type=first["activity__activity_type"],
                day=first["day"],
                status=first["activity__status"],
                who=first["activity__cluster__name"] or "",
                note=f"{len(meetings)} planned" if len(meetings) > 1 else "",
            )
        )
    else:
        slots.append(
            SlotRow(
                "Cluster meeting",
                "meeting",
                "",
                "open",
                note="Not in an active cluster"
                if not school.clustered
                else "On no planned meeting's roster",
            )
        )
    return slots + beyond


def _staff_names(ids) -> dict[str, str]:
    from django.db.models import Q as _Q

    from apps.accounts.models import StaffProfile

    ids = {i for i in ids if i}
    if not ids:
        return {}
    names: dict[str, str] = {}
    for staff_id, user_id, name in StaffProfile.all_objects.filter(
        _Q(id__in=ids) | _Q(user_id__in=ids)
    ).values_list("id", "user_id", "user__name"):
        for key in (staff_id, user_id):
            if key:
                names[str(key)] = name or ""
    return names


class PlanningCoverageService:
    """The coverage half of the page, as one importable surface."""

    window_for = staticmethod(window_for)
    load_facts = staticmethod(load_facts)
    annual_position = staticmethod(annual_position)
    claims_for = staticmethod(claims_for)
    visit_claim_q = staticmethod(visit_claim_q)
    duplicate_reasons = staticmethod(duplicate_reasons)
    school_slots = staticmethod(school_slots)
