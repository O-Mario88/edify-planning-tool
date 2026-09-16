"""Team Oversight school coverage (owner brief, 2026-09-15).

Three questions about a supervisor's schools in one selected period:

* **Planned Schools** — every school with valid planned or scheduled work,
  grouped by day inside a week, week inside a month, fiscal month inside a
  quarter and quarter inside a year, so the totals reconcile across the
  hierarchy. Built from the canonical planning items the rest of Team
  Oversight reads, never from a parallel table.
* **Schools with Planned Cluster Training or Meeting** — schools the planning
  record explicitly attaches to a live cluster session in the period.
* **Schools with No Training Planned** — the rest, each with the reason.

Supervision is not ownership: these read the supervisor's team, and the CCEO
who owns each school stays named on every row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Exists, OuterRef, Q

from apps.core.activity_types import CLUSTER_MEETING_TYPES
from apps.core.fy import get_month_date_range, get_quarter_date_range
from apps.schools.school_status import (
    CLUSTER_SESSION_TYPES,
    DEAD_STATUSES,
    cluster_training_coverage,
    visit_statuses,
)

#: How many rows each table shows before "open the full list".
ROW_LIMIT = 100

FY_MONTH_ORDER = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MONTH_QUARTER = {
    10: "Q1",
    11: "Q1",
    12: "Q1",
    1: "Q2",
    2: "Q2",
    3: "Q2",
    4: "Q3",
    5: "Q3",
    6: "Q3",
    7: "Q4",
    8: "Q4",
    9: "Q4",
}
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


@dataclass
class CoverageGroup:
    key: str
    label: str
    rows: list = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def school_count(self) -> int:
        return len({row["school_id"] for row in self.rows if row["school_id"]})

    @property
    def page_param(self) -> str:
        """This group's own page parameter.

        Each group is its own table, so paging one must not page the others:
        a country lens in the FY view puts two hundred schools in a quarter
        and four in the next, and one shared parameter would move both.
        """
        safe = "".join(ch if ch.isalnum() else "_" for ch in self.key).strip("_")
        return f"planned_{safe or 'group'}_page"


def _period_days(*, fy: str, period: str, month, quarter, date_start, date_end):
    """The [start, end] the selected period covers, inclusive."""
    if period == "week" and date_start and date_end:
        return date_start, date_end - timedelta(days=1)
    if period == "month" and month:
        start, end = get_month_date_range(
            fy,
            FY_MONTH_ORDER.index(int(month)) + 1 if int(month) in FY_MONTH_ORDER else 1,
        )
        return start.date(), end.date() - timedelta(days=1)
    if period == "quarter" and quarter:
        start, end = get_quarter_date_range(fy, quarter)
        return start.date(), end.date() - timedelta(days=1)
    from apps.core.fy import get_fy_date_range

    start, end = get_fy_date_range(fy)
    return start.date(), end.date() - timedelta(days=1)


def _group_of(day: date | None, *, period: str) -> tuple[str, str]:
    """Which group a dated row belongs to, and that group's label."""
    if day is None:
        return "undated", "No date yet"
    if period == "week":
        return day.isoformat(), f"{day:%A %-d %b}"
    if period == "month":
        week = min(5, (day.day - 1) // 7 + 1)
        return f"w{week}", f"Week {week}"
    if period == "quarter":
        return f"m{day.month}", f"{MONTH_NAMES[day.month]} {day.year}"
    return MONTH_QUARTER[
        day.month
    ], f"{MONTH_QUARTER[day.month]} · {MONTH_NAMES[day.month][:3]}–"


def _quarter_label(day: date) -> str:
    quarter = MONTH_QUARTER[day.month]
    spans = {"Q1": "Oct–Dec", "Q2": "Jan–Mar", "Q3": "Apr–Jun", "Q4": "Jul–Sep"}
    return f"{quarter} · {spans[quarter]}"


def planned_schools(items, *, period: str) -> tuple[list[CoverageGroup], dict]:
    """Planned and scheduled school work, grouped for the selected period.

    ``items`` are the oversight items the page already built, so the table can
    never disagree with the rest of Team Oversight about what is planned.
    """
    school_items = [item for item in items if item.school_id]
    groups: dict[str, CoverageGroup] = {}
    for item in school_items:
        day = item.planned_date
        if period == "fy" and day is not None:
            key, label = MONTH_QUARTER[day.month], _quarter_label(day)
        else:
            key, label = _group_of(day, period=period)
        group = groups.setdefault(key, CoverageGroup(key=key, label=label))
        group.rows.append(
            {
                "school_id": item.school_id,
                "school_name": item.school_name,
                "owner_name": item.operational_owner_name or "Unassigned",
                "region_name": item.region_name,
                "district_name": item.district_name,
                "cluster_name": item.cluster_name,
                "activity_id": item.activity_id,
                "activity_type": item.activity_type,
                "activity_label": (item.activity_type or "").replace("_", " ").title(),
                "category": "Cluster meeting"
                if item.activity_type in CLUSTER_MEETING_TYPES
                else "Visit"
                if "visit" in (item.activity_type or "")
                else "Training",
                "planned_date": day,
                "scheduled_date": item.planned_date,
                "delivery_channel": "Partner" if item.is_partner_work else "Staff",
                "partner_name": item.partner_name,
                "funding_status": item.finance_status
                or ("Costed" if item.planned_cost else "No cost yet"),
                "activity_status": item.activity_status or item.assignment_status,
                "stage": item.stage,
                "detail_url": (
                    f"/team-planning-oversight/detail?activity={item.activity_id}"
                    if item.activity_id
                    else ""
                ),
            }
        )

    def sort_key(group: CoverageGroup):
        if group.key == "undated":
            return (1, "")
        return (0, group.key)

    ordered = sorted(groups.values(), key=sort_key)
    for group in ordered:
        group.rows.sort(
            key=lambda row: (row["planned_date"] or date.max, row["school_name"])
        )
    totals = {
        "activities": len(school_items),
        "schools": len({item.school_id for item in school_items}),
        "groups": len(ordered),
    }
    return ordered, totals


def _schools_in_oversight_scope(principal):
    """The schools this supervisor watches — their team's, or their country's."""
    from apps.core.scoping import resolve_user_scope, scoped_school_queryset
    from apps.schools.lifecycle_service import active_schools

    scope = resolve_user_scope(principal)
    qs = scoped_school_queryset(scope)
    if qs is None:
        return None
    # Closed schools take no work and are never "missing training"
    # (owner, 2026-09-15).
    return active_schools(qs)


def training_coverage(
    principal,
    *,
    fy: str,
    period: str = "fy",
    month=None,
    quarter=None,
    date_start=None,
    date_end=None,
    limit: int = ROW_LIMIT,
) -> dict:
    """Schools with a planned cluster session in the period, and those without."""
    from apps.activities.models import Activity, ClusterActivityAttendance

    schools = _schools_in_oversight_scope(principal)
    if schools is None:
        return {
            "planned_rows": [],
            "missing_rows": [],
            "planned_count": 0,
            "missing_count": 0,
            "total": 0,
            "period_label": "",
        }
    start, end = _period_days(
        fy=fy,
        period=period,
        month=month,
        quarter=quarter,
        date_start=date_start,
        date_end=date_end,
    )

    sessions = Activity.objects.filter(
        activity_type__in=CLUSTER_SESSION_TYPES,
        deleted_at__isnull=True,
        fy=str(fy),
    ).exclude(status__in=DEAD_STATUSES)
    sessions = sessions.filter(
        Q(planned_date__range=(start, end))
        | Q(planned_date__isnull=True, scheduled_date__date__range=(start, end))
    )
    attached = ClusterActivityAttendance.objects.filter(
        activity_id__in=sessions.values("id"), school_id=OuterRef("id")
    ).filter(Q(invited=True) | Q(attended=True))

    # School.cluster_id is a plain column, not a relation: the cluster's name
    # is resolved in one lookup below rather than joined.
    schools = schools.select_related("district", "region").annotate(
        has_session=Exists(attached)
    )
    planned_qs = schools.filter(has_session=True)
    missing_qs = schools.filter(has_session=False)
    planned_count = planned_qs.count()
    missing_count = missing_qs.count()

    planned_page = list(planned_qs.order_by("name")[:limit])
    missing_page = list(missing_qs.order_by("name")[:limit])
    coverage = cluster_training_coverage(
        planned_page + missing_page, fy=fy, date_start=start, date_end=end
    )
    visits = visit_statuses(
        [school.id for school in planned_page + missing_page],
        fy=fy,
        date_start=start,
        date_end=end,
    )
    owners = _owner_names(planned_page + missing_page)
    cluster_names = _cluster_names(planned_page + missing_page)

    def row(school):
        state = coverage[school.id]
        visit = visits[school.id]
        return {
            "school_id": school.id,
            "school_code": school.school_id,
            "school_name": school.name,
            "owner_name": owners.get(school.account_owner_id, "Unassigned"),
            "district_name": school.district.name if school.district_id else "",
            "cluster_id": school.cluster_id,
            "cluster_name": state.cluster_name
            or cluster_names.get(school.cluster_id, ""),
            "activity_label": state.activity_label
            or (state.activity_type or "").replace("_", " ").title(),
            "activity_type": state.activity_type,
            "planned_date": state.planned_date,
            "delivery_channel": "Partner"
            if state.delivery_type == "partner"
            else "Staff",
            "partner_name": state.partner_name,
            "status": state.status,
            "training_status": state.label,
            "reason": state.reason,
            "visit_status": visit.label,
            "visit_status_tone": visit.tone,
            "next_visit_date": visit.next_date,
            "school_url": f"/schools/{school.school_id}",
            "cluster_url": f"/clusters/{school.cluster_id}"
            if school.cluster_id
            else "",
        }

    return {
        "planned_rows": [row(school) for school in planned_page],
        "missing_rows": [row(school) for school in missing_page],
        "planned_count": planned_count,
        "missing_count": missing_count,
        "total": planned_count + missing_count,
        "period_start": start,
        "period_end": end,
    }


def _cluster_names(schools) -> dict[str, str]:
    from apps.clusters.models import Cluster

    ids = {s.cluster_id for s in schools if s.cluster_id}
    if not ids:
        return {}
    return dict(Cluster.objects.filter(id__in=ids).values_list("id", "name"))


def _owner_names(schools) -> dict[str, str]:
    from apps.accounts.models import StaffProfile

    ids = {s.account_owner_id for s in schools if s.account_owner_id}
    if not ids:
        return {}
    names: dict[str, str] = {}
    for profile in (
        StaffProfile.objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .select_related("user")
        .only("id", "user_id", "user__name")
    ):
        if profile.user_id and profile.user.name:
            names[profile.id] = profile.user.name
            names[profile.user_id] = profile.user.name
    return names


def missing_training_count(principal, *, fy: str) -> int:
    """How many schools in this supervisor's scope have no cluster session
    planned this fiscal year — the attention count and the To-Do's number."""
    return training_coverage(principal, fy=fy, period="fy", limit=0)["missing_count"]


__all__ = [
    "CoverageGroup",
    "ROW_LIMIT",
    "missing_training_count",
    "planned_schools",
    "training_coverage",
]
