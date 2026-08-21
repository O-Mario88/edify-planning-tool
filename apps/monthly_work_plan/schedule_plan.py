"""The monthly Work Plan, derived entirely from the schedule (§18).

Three columns and nothing else: **Activity · Target · Cost**, one section per
financial-year month, each row an aggregate of the scheduled activities of that
type in that month, expandable to the individual records behind it.

Nothing here is typed by a user. There is no argument that lets a caller supply
a target contribution or a cost, and there is no write path — which is the
point. A Work Plan anyone can edit by hand is a second plan, and a second plan
is the thing that disagrees with the schedule the moment either one moves. When
an activity is rescheduled, cancelled, reassigned to a partner or cost-amended,
this recomputes because it never held its own copy.

Cost comes from the authoritative schedule cost lines, never from a rate
re-derived here — one activity, one cost.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum

#: Financial year runs October → September.
FY_MONTH_ORDER = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)
MONTH_LABELS = {
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

#: A scheduled activity is a real commitment from the moment it is scheduled
#: through to closure. Draft and abandoned work is not a plan.
PLANNED_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "rescheduled",
    "in_progress",
    "completion_started",
    "submitted",
    "pending_review",
    "pl_review",
    "ia_review",
    "approved",
    "ia_verified",
    "completed",
    "closed",
)
EXCLUDED_STATUSES = (
    "draft",
    "unscheduled",
    "returned",
    "returned_to_staff",
    "rejected",
    "cancelled",
    "deferred",
    "invalidated",
)


@dataclass
class ScheduledRecord:
    """One scheduled activity behind an aggregated row."""

    activity_id: str
    date: str
    where: str
    status: str
    cost: Decimal
    contribution: int

    def as_dict(self) -> dict:
        return {
            "activityId": self.activity_id,
            "date": self.date,
            "where": self.where,
            "status": self.status,
            "cost": self.cost,
            "contribution": self.contribution,
        }


@dataclass
class ActivityRow:
    """One activity type in one month."""

    activity_type: str
    label: str
    unit: str
    target: int = 0
    cost: Decimal = Decimal("0")
    records: list[ScheduledRecord] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "activityType": self.activity_type,
            "label": self.label,
            "unit": self.unit,
            "target": self.target,
            "cost": self.cost,
            "records": [r.as_dict() for r in self.records],
            "count": len(self.records),
        }


def _month_label(month: int, fy: int) -> str:
    # Oct–Dec belong to the year before the FY label; Jan–Sep to the FY itself.
    year = fy - 1 if month >= 10 else fy
    return f"{MONTH_LABELS[month]} {year}"


def _where(activity) -> str:
    school = getattr(activity, "school", None)
    if school is not None:
        return getattr(school, "name", "") or "School"
    cluster = getattr(activity, "cluster", None)
    if cluster is not None:
        return getattr(cluster, "name", "") or "Cluster"
    district = getattr(activity, "event_district", None)
    if district is not None:
        return getattr(district, "name", "") or "District"
    return "—"


def _unit_for(activity_type: str) -> str:
    """What one of these actually counts, so months never sum apples to pears."""
    if "training" in activity_type or "meeting" in activity_type:
        return "sessions"
    if "visit" in activity_type:
        return "visits"
    if "ssa" in activity_type or "assessment" in activity_type:
        return "assessments"
    return "activities"


def monthly_work_plan(*, staff_ids, fy: str, month: int | None = None) -> dict:
    """The Work Plan for these people, by financial-year month.

    `month` restricts to one FY month; omit it for the whole year. The target
    contribution of each row is the count of scheduled records in its own unit
    — the governed milestone rule decides what a unit is, and no arithmetic
    here mixes two of them.
    """
    from apps.activities.models import Activity

    fy_int = int(fy)
    months = (month,) if month in FY_MONTH_ORDER else FY_MONTH_ORDER

    activities = list(
        Activity.objects.filter(
            responsible_staff_id__in=list(staff_ids),
            fy=fy,
            deleted_at__isnull=True,
            planned_date__isnull=False,
        )
        .exclude(status__in=EXCLUDED_STATUSES)
        .annotate(lines_total=Sum("schedule_cost_lines__amount"))
        .select_related("school", "cluster", "event_district")
        .order_by("planned_date")
    )

    by_month: dict[int, dict[str, ActivityRow]] = defaultdict(dict)
    for activity in activities:
        planned = activity.planned_date
        if planned is None or planned.month not in months:
            continue
        activity_type = activity.activity_type or "activity"
        rows = by_month[planned.month]
        row = rows.get(activity_type)
        if row is None:
            row = ActivityRow(
                activity_type=activity_type,
                label=activity_type.replace("_", " ").title(),
                unit=_unit_for(activity_type),
            )
            rows[activity_type] = row
        cost = Decimal(str(activity.lines_total or 0))
        row.target += 1
        row.cost += cost
        row.records.append(
            ScheduledRecord(
                activity_id=activity.id,
                date=planned.isoformat(),
                where=_where(activity),
                status=activity.status,
                cost=cost,
                contribution=1,
            )
        )

    sections = []
    for month_number in FY_MONTH_ORDER:
        if month_number not in months:
            continue
        rows = sorted(by_month.get(month_number, {}).values(), key=lambda r: r.label)
        # Units are summarised separately rather than added together: "24
        # visits · 3 sessions" is true, and "27" is not.
        units: dict[str, int] = defaultdict(int)
        for row in rows:
            units[row.unit] += row.target
        sections.append(
            {
                "month": month_number,
                "label": _month_label(month_number, fy_int),
                "rows": [row.as_dict() for row in rows],
                "totalCost": sum((row.cost for row in rows), Decimal("0")),
                "unitTotals": [
                    {"unit": unit, "count": count}
                    for unit, count in sorted(units.items())
                ],
                "isEmpty": not rows,
            }
        )

    return {
        "fy": fy,
        "sections": sections,
        "totalCost": sum((section["totalCost"] for section in sections), Decimal("0")),
        "scheduledCount": sum(
            len(row["records"]) for section in sections for row in section["rows"]
        ),
    }
