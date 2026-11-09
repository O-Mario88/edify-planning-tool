"""Export Planned Activities: the upload file, written from the work already
scheduled (owner, 2026-11-09).

"The bulk completion template must be generated directly from activities
already scheduled in the Planning module", for a chosen period, so a file
completes exactly the activities staff planned and never names one by guess.

Each line is the activity's Activity ID and School ID — the two the upload
matches on — and its Planned Date, then the cells the uploader fills in: the
School Visit ID or Training ID and the Completed Date, and a training's
Teachers Trained and School Leaders Trained (owner, 2026-11-09). A cluster or
group training gives one line per school invited to it, since the upload
takes one line per participating school.

Open work only by default; ``completed=1`` adds the work already completed so
a file can be reconciled (uploaded again, those lines are skipped as already
completed). Cancelled, rejected and deferred work is never exported.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from .columns import (
    ACTIVITY_ID,
    COMPLETED_DATE,
    COUNT_COLUMNS,
    OWN_ID,
    TEMPLATE_NOTES,
    Column,
)
from .models import BulkKind
from .periods import Period
from .rules import (
    CALLED_OFF_STATUSES,
    HANDED_IN_STATUSES,
    KIND_TYPES,
    activities_in_reach,
)

#: An export lists at most this many activities; a country's year of visits
#: is well under it, and the file stays quick to open.
TEMPLATE_ROW_LIMIT = 20000

FILE_STEMS = {
    BulkKind.VISIT: "bulk-school-visit-completion",
    BulkKind.TRAINING: "bulk-training-completion",
}

DAY_FORMAT = "d mmm yyyy"

#: The columns between the Activity ID and the cells to fill in, for both
#: uploads. The School ID is the upload's; the Planned Date is there to find
#: the work by, and the upload ignores it.
DESCRIBING = ("School ID", "Planned Date")


def _fill_in(kind: str) -> tuple[Column, ...]:
    counts = COUNT_COLUMNS if kind == BulkKind.TRAINING else ()
    return (OWN_ID[kind], COMPLETED_DATE, *counts)


def export_headings(kind: str) -> list[str]:
    return [
        ACTIVITY_ID.heading,
        *DESCRIBING,
        *(column.heading for column in _fill_in(kind)),
    ]


# ── Filters ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ExportFilters:
    staff: str = ""
    lead: str = ""
    district: str = ""
    activity_type: str = ""
    include_completed: bool = False

    @classmethod
    def from_query(cls, query, kind: str) -> "ExportFilters":
        wanted_type = (query.get("type") or "").strip()
        return cls(
            staff=(query.get("staff") or "").strip()[:30],
            lead=(query.get("lead") or "").strip()[:30],
            district=(query.get("district") or "").strip()[:30],
            activity_type=wanted_type if wanted_type in KIND_TYPES[kind] else "",
            include_completed=(query.get("completed") or "") == "1",
        )

    def query(self) -> dict[str, str]:
        params = {
            "staff": self.staff,
            "lead": self.lead,
            "district": self.district,
            "type": self.activity_type,
            "completed": "1" if self.include_completed else "",
        }
        return {key: value for key, value in params.items() if value}


def _both_id_spaces(ids) -> set[str]:
    """StaffProfile ids and the User ids they belong to, each way:
    ``Activity.responsible_staff_id`` holds either (scoping.owner_ids)."""
    from apps.accounts.models import StaffProfile

    wanted = {str(i) for i in ids if i}
    if not wanted:
        return wanted
    for staff_id, user_id in StaffProfile.objects.filter(
        Q(id__in=wanted) | Q(user_id__in=wanted)
    ).values_list("id", "user_id"):
        wanted.update(i for i in (staff_id, user_id) if i)
    return wanted


def _lead_team(lead_id: str) -> set[str]:
    """The Programme Lead and everyone reporting to them, both id spaces."""
    from apps.planning.oversight_service import program_lead_rosters

    roster = program_lead_rosters([lead_id]).get(lead_id, [])
    return {i for member in roster for i in member["ids"] if i}


def _owned_by(ids: set[str]) -> Q:
    return Q(responsible_staff_id__in=ids) | Q(monitored_by_staff_id__in=ids)


def _in_district(district_id: str) -> Q:
    return (
        Q(school__district_id=district_id)
        | Q(school__isnull=True, cluster__district_id=district_id)
        | Q(school__isnull=True, cluster__isnull=True, event_district_id=district_id)
    )


# ── Which activities ─────────────────────────────────────────────────────────
def _done_q() -> Q:
    """rules.is_done, as a query."""
    from apps.core.activity_types import COMPLETED_WORK_STATUSES

    partner_waiting = Q(delivery_type="partner", status="awaiting_ia_verification")
    return (
        Q(status__in=COMPLETED_WORK_STATUSES)
        | (Q(status__in=HANDED_IN_STATUSES) & ~partner_waiting)
        | Q(ia_verification_status="confirmed")
    )


def _open_q() -> Q:
    """rules.is_open and not done, as a query: work an upload can complete."""
    from apps.activities.services import STARTABLE_STATUSES, SUBMITTABLE_STATUSES

    staff_open = Q(status__in=(*STARTABLE_STATUSES, *SUBMITTABLE_STATUSES)) & ~Q(
        delivery_type="partner"
    )
    partner_waiting = Q(delivery_type="partner", status="awaiting_ia_verification")
    return (staff_open | partner_waiting) & ~_done_q()


def _in_period(period: Period) -> Q:
    """Scheduled in the period: the planned day, or the scheduled instant's
    day for older rows without one (my_plan.services._scheduled_in_range)."""
    days = (period.start, period.end)
    return Q(planned_date__range=days) | Q(
        planned_date__isnull=True, scheduled_date__date__range=days
    )


def _period_work(principal, kind: str, period: Period):
    return (
        activities_in_reach(principal)
        .filter(activity_type__in=KIND_TYPES[kind])
        .filter(_in_period(period))
        .exclude(status__in=CALLED_OFF_STATUSES)
    )


def planned_activities(principal, kind: str, period: Period, filters: ExportFilters):
    """The scheduled activities of this kind in the period, as filtered."""
    standing = _open_q() | _done_q() if filters.include_completed else _open_q()
    qs = _period_work(principal, kind, period).filter(standing)
    if filters.staff:
        qs = qs.filter(_owned_by(_both_id_spaces({filters.staff})))
    if filters.lead:
        qs = qs.filter(_owned_by(_lead_team(filters.lead)))
    if filters.district:
        qs = qs.filter(_in_district(filters.district))
    if filters.activity_type:
        qs = qs.filter(activity_type=filters.activity_type)
    return qs.order_by("planned_date", "scheduled_date", "id")


# ── Choices for the filters ──────────────────────────────────────────────────
def _people(ids) -> dict[str, str]:
    """{id in either space: the person's name}."""
    from apps.accounts.models import StaffProfile, User

    wanted = {str(i) for i in ids if i}
    names: dict[str, str] = {}
    if not wanted:
        return names
    for staff_id, user_id, name in StaffProfile.objects.filter(
        Q(id__in=wanted) | Q(user_id__in=wanted)
    ).values_list("id", "user_id", "user__name"):
        for key in (staff_id, user_id):
            if key:
                names[str(key)] = name or ""
    for user_id, name in User.objects.filter(id__in=wanted - set(names)).values_list(
        "id", "name"
    ):
        names[str(user_id)] = name or ""
    return names


def _staff_choices(work) -> list[dict]:
    """One choice per person who owns work in the period, whichever id
    space their activities were filed under."""
    from apps.accounts.models import StaffProfile

    owners = set(
        work.exclude(responsible_staff_id__isnull=True)
        .order_by()
        .values_list("responsible_staff_id", flat=True)
        .distinct()
    )
    canonical = {i: i for i in owners}
    for staff_id, user_id in StaffProfile.objects.filter(
        Q(id__in=owners) | Q(user_id__in=owners)
    ).values_list("id", "user_id"):
        for key in (staff_id, user_id):
            if key in canonical:
                canonical[key] = staff_id
    names = _people(owners)
    people = {canonical[i]: names.get(i) or "Unnamed staff" for i in owners}
    return sorted(
        ({"id": pk, "name": name} for pk, name in people.items()),
        key=lambda c: c["name"].lower(),
    )


def _lead_choices(principal) -> list[dict]:
    from apps.accounts.models import User
    from apps.core.rbac import EdifyRole
    from apps.core.role_holding import holds_role_q
    from apps.core.scoping import person_country_q, resolve_user_scope

    leads = (
        User.objects.filter(
            holds_role_q(EdifyRole.COUNTRY_PROGRAM_LEAD, prefix=""),
            deleted_at__isnull=True,
        )
        .filter(person_country_q(resolve_user_scope(principal), "id"))
        .order_by("name")
    )
    return [{"id": pk, "name": name} for pk, name in leads.values_list("id", "name")]


def _district_choices(work) -> list[dict]:
    from apps.geography.models import District

    ids = set(work.order_by().values_list("school__district_id", flat=True))
    ids |= set(work.order_by().values_list("cluster__district_id", flat=True))
    ids |= set(work.order_by().values_list("event_district_id", flat=True))
    rows = District.objects.filter(id__in={i for i in ids if i}).order_by("name")
    return [{"id": pk, "name": name} for pk, name in rows.values_list("id", "name")]


def _type_choices(kind: str) -> list[dict]:
    from apps.core.enums import ActivityType

    labels = dict(ActivityType.choices)
    return [{"id": t, "name": labels.get(t, t)} for t in KIND_TYPES[kind]]


def filter_choices(principal, kind: str, period: Period) -> dict:
    """What each filter offers: the people, districts and kinds of work the
    period holds, and the Programme Leads in the uploader's country."""
    work = _period_work(principal, kind, period)
    return {
        "staff": _staff_choices(work),
        "leads": _lead_choices(principal),
        "districts": _district_choices(work),
        "types": _type_choices(kind),
    }


# ── The lines ────────────────────────────────────────────────────────────────
def _invited_schools(activities) -> dict[str, list[str]]:
    """{activity id: [School ID]} for the trainings with no school."""
    from apps.activities.models import ClusterActivityAttendance

    ids = [a.pk for a in activities if not a.school_id]
    invited: dict[str, list[str]] = {}
    if not ids:
        return invited
    for activity_id, code in (
        ClusterActivityAttendance.objects.filter(activity_id__in=ids)
        .order_by("school__name")
        .values_list("activity_id", "school__school_id")
    ):
        if code:
            invited.setdefault(activity_id, []).append(code)
    return invited


def _filled_in(activity, kind: str) -> list:
    """The fill-in cells. The ID already saved on the activity is offered
    back, so work whose ID was entered but never handed in completes as it is;
    completed work shows the day it was done, for reconciliation."""
    cells = [
        activity.salesforce_activity_id or "",
        activity.actual_delivery_date or "",
    ]
    if kind == BulkKind.TRAINING:
        cells += [activity.teachers_attended or "", activity.leaders_attended or ""]
    return cells


def _lines(activity, kind: str, invited: dict) -> list[list]:
    from .lines import scheduled_day

    if activity.school_id:
        schools = [activity.school.school_id]
    else:
        schools = invited.get(activity.id) or [""]
    planned = scheduled_day(activity)
    filled = _filled_in(activity, kind)
    return [[activity.id, code, planned, *filled] for code in schools]


def export_sheets(principal, kind: str, period: Period, filters: ExportFilters):
    """The workbook: the planned activities, then how to fill them in."""
    activities = list(
        planned_activities(principal, kind, period, filters).select_related("school")[
            :TEMPLATE_ROW_LIMIT
        ]
    )
    invited = _invited_schools(activities) if kind == BulkKind.TRAINING else {}
    headings = export_headings(kind)
    rows = [line for activity in activities for line in _lines(activity, kind, invited)]
    day_columns = (
        headings.index("Planned Date") + 1,
        headings.index(COMPLETED_DATE.heading) + 1,
    )
    return [
        {
            "title": "Planned Activities",
            "headers": headings,
            "rows": rows,
            "number_formats": {column: DAY_FORMAT for column in day_columns},
        },
        {
            "title": "How to fill it in",
            "headers": ["Instructions"],
            "rows": [[f"Period: {period.label}."], [TEMPLATE_NOTES[kind]]],
            "widths": [120],
            "filter": False,
        },
    ]
