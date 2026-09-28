"""Re-file work dated on a quarter's first day that was filed under the day before.

Until 2026-09-28 ``apps.core.fy`` read an aware datetime in UTC. A date picked
in the app is stored as local midnight, and midnight in Nairobi is 21:00 UTC
the day before, so work dated 1 October was filed under the fiscal year before
and work dated 1 January, 1 April or 1 July under the quarter before. The
reading is fixed; this re-files what it already wrote (owner, 2026-09-28: "yes,
write the migration").

What it wrote, and where:

- an activity's ``fy``, ``fiscal_year`` and ``quarter`` (create, reschedule,
  partner scheduling, cluster bulk scheduling, an applied budget amendment);
- its cost lines' ``fiscal_year`` and ``quarter`` — only an applied budget
  amendment wrote those; costing reads the plain planned date and was right;
- an advance's ``fy`` and ``quarter``, copied from its activity;
- a budget amendment's ``new_fy`` and ``new_quarter``;
- an SSA record's ``fy`` and ``quarter``.

A value is re-filed only when it is exactly what the old reading gave — the
year or quarter of the day before the row's own day. A year or quarter set on
purpose to something else is left alone, and so is every row already right.
Nothing is priced again. Cost lines that change year or quarter have their
weekly and monthly draft fund requests re-synced, old and new periods both
(the sync leaves any request that has left draft untouched).

Migration ``activities.0060`` runs this once on deploy; the
``refile_fy_boundary_rows`` command lists what is left and can apply it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.apps import apps as django_apps
from django.db import models
from django.db.models import Max, Min, Q
from django.utils import timezone

from apps.core.fy import get_operational_fy, get_quarter_for_date

QUARTER_START_MONTHS = (1, 4, 7, 10)


@dataclass(frozen=True)
class _Target:
    model: str
    day_field: str
    fy_fields: tuple[str, ...]
    quarter_fields: tuple[str, ...]
    live: dict = field(default_factory=dict)


TARGETS = (
    _Target(
        "activities.Activity",
        "planned_date",
        ("fy", "fiscal_year"),
        ("quarter",),
        {"deleted_at__isnull": True},
    ),
    _Target(
        "activities.ActivityScheduleCostLine",
        "planned_date",
        ("fiscal_year",),
        ("quarter",),
    ),
    _Target("fund_requests.AdvanceRequest", "planned_date", ("fy",), ("quarter",)),
    _Target("budget.BudgetAmendment", "new_date", ("new_fy",), ("new_quarter",)),
    _Target(
        "ssa.SsaRecord",
        "date_of_ssa",
        ("fy",),
        ("quarter",),
        {"deleted_at__isnull": True},
    ),
)

COST_LINE = "activities.ActivityScheduleCostLine"


@dataclass
class Misfiled:
    model: str
    pk: str
    day: date
    changes: dict[str, tuple[str, str]]


def _quarter_starts(first: date, last: date) -> list[date]:
    return [
        date(year, month, 1)
        for year in range(first.year, last.year + 1)
        for month in QUARTER_START_MONTHS
        if first <= date(year, month, 1) <= last
    ]


def _candidates(queryset, day_field: str, is_datetime: bool):
    """Rows whose own day is a quarter's first day and whose UTC day is the day
    before — the only rows the UTC reading could have misfiled."""
    if not is_datetime:
        return queryset.filter(
            **{f"{day_field}__month__in": QUARTER_START_MONTHS, f"{day_field}__day": 1}
        )
    span = queryset.aggregate(first=Min(day_field), last=Max(day_field))
    if span["first"] is None:
        return queryset.none()
    first = timezone.localtime(span["first"]).date()
    last = timezone.localtime(span["last"]).date()
    windows = Q()
    for day in _quarter_starts(first, last):
        local_midnight = timezone.make_aware(datetime.combine(day, time.min))
        utc_midnight = datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc)
        if local_midnight < utc_midnight:
            windows |= Q(
                **{
                    f"{day_field}__gte": local_midnight,
                    f"{day_field}__lt": utc_midnight,
                }
            )
    return queryset.filter(windows) if windows else queryset.none()


def find_misfiled(registry=None) -> list[Misfiled]:
    """Every row carrying the old reading's year or quarter. Reads only.

    ``registry`` is the app registry to take models from: the migration passes
    its historical one, so this runs against the schema of the moment.
    """
    registry = registry or django_apps
    found = []
    for target in TARGETS:
        Model = registry.get_model(*target.model.split("."))
        is_datetime = isinstance(
            Model._meta.get_field(target.day_field), models.DateTimeField
        )
        rows = _candidates(
            Model._base_manager.filter(**target.live), target.day_field, is_datetime
        ).values("pk", target.day_field, *target.fy_fields, *target.quarter_fields)
        for row in rows:
            day = row[target.day_field]
            if is_datetime:
                day = timezone.localtime(day).date()
            before = day - timedelta(days=1)
            changes = {}
            for name in target.fy_fields:
                wrong, right = get_operational_fy(before), get_operational_fy(day)
                if wrong != right and row[name] == wrong:
                    changes[name] = (wrong, right)
            for name in target.quarter_fields:
                wrong, right = get_quarter_for_date(before), get_quarter_for_date(day)
                if row[name] == wrong:
                    changes[name] = (wrong, right)
            if changes:
                found.append(Misfiled(target.model, str(row["pk"]), day, changes))
    return found


def report(rows: list[Misfiled]) -> list[str]:
    return [
        f"{row.model} {row.pk} ({row.day.isoformat()}): "
        + ", ".join(
            f"{name} {old} -> {new}" for name, (old, new) in row.changes.items()
        )
        for row in rows
    ]


def refile_misfiled(rows=None, *, registry=None, out=print) -> int:
    """Write the day's own year and quarter onto every misfiled row, then re-sync
    the draft fund requests of any activity whose cost lines moved period.

    The rows are written through ``registry`` (the migration's historical
    models); only the fund-request sync is live code, and it runs only when a
    cost line changed.
    """
    registry = registry or django_apps
    rows = find_misfiled(registry) if rows is None else rows
    if not rows:
        return 0

    CostLine = registry.get_model(*COST_LINE.split("."))
    moved_line_ids = [row.pk for row in rows if row.model == COST_LINE]
    prior_buckets = defaultdict(list)
    for line in CostLine._base_manager.filter(pk__in=moved_line_ids).values(
        "activity_id", "responsible_user", "fiscal_year", "month", "week_start_date"
    ):
        prior_buckets[line["activity_id"]].append(
            (
                line["responsible_user"],
                line["fiscal_year"],
                line["month"],
                line["week_start_date"],
            )
        )

    for row in rows:
        Model = registry.get_model(*row.model.split("."))
        Model._base_manager.filter(pk=row.pk).update(
            **{name: new for name, (_old, new) in row.changes.items()}
        )
    for line in report(rows):
        out(f"Re-filed {line}")

    if prior_buckets:
        from apps.activities.models import Activity
        from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
        from apps.fund_requests.weekly_service import sync_weekly_requests_for_activity

        for activity in Activity.objects.filter(pk__in=list(prior_buckets)):
            buckets = prior_buckets[activity.pk]
            sync_weekly_requests_for_activity(activity, prior_buckets=buckets)
            sync_monthly_drafts_for_activity(activity, prior_buckets=buckets)
            out(f"Re-synced draft fund requests for activity {activity.pk}")
    return len(rows)
