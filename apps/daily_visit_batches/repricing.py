"""Bring days planned before a pricing rule up to the rule.

Two rules of 2026-10-05 change what a night away costs, and a day planned
before them keeps the price it was planned at until something re-prices it:

* the last of a run of days in a secondary district is the day the traveller
  comes home, with no night and no dinner (``return_day``);
* every member of staff but a CCEO sleeps at the second accommodation rate
  (``districts``);
* a trip of several days has no night and no dinner on its last day.

``find_days_to_reprice`` lists the planned days that still carry the old
price and ``reprice_days`` re-prices them one at a time, each in its own
transaction; ``find_trips_to_reprice`` and ``reprice_trips`` do the same for
planned work of several days, which is priced on its own and belongs to no
day. A day or a trip whose week has left draft, whose money has moved or
whose work is done is left as it was priced. Daily visit batches migration
0003 runs them inside the deploy's time limit; ``refresh_daily_cost_allocations
--apply`` picks up the days it did not reach.
"""

from __future__ import annotations

import time

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

from .districts import accommodation_key_for_role, accommodation_key_for_staff
from .pricing import ACCOMMODATION_KEYS
from .return_day import ONE_DAY, is_return_day, priced_as_return_day


def night_is_stale(batch) -> bool:
    """Whether this secondary-district day is priced with a night it should
    not have, without one it should, or at the wrong traveller's rate."""
    if batch.district_type != "secondary" or not batch.school_count:
        return False
    if priced_as_return_day(batch) != is_return_day(
        batch.responsible_user, batch.visit_date
    ):
        return True
    priced_keys = set(batch.rate_snapshot or {}) & ACCOMMODATION_KEYS
    return bool(priced_keys) and (
        accommodation_key_for_staff(batch.responsible_user) not in priced_keys
    )


def find_days_to_reprice(apps=None, *, today=None) -> list[str]:
    """Ids of the planned secondary-district days still priced the old way,
    earliest first.

    Takes the migration's historical ``apps`` so the migration can ask
    without touching live models; anything else passes nothing. Days before
    today are history and are not looked at."""
    if apps is not None:
        Batch = apps.get_model("daily_visit_batches", "DailyVisitBatch")
        User = apps.get_model("accounts", "User")
    else:
        from apps.accounts.models import User

        from .models import DailyVisitBatch as Batch

    today = today or timezone.localdate()
    days = list(
        Batch.objects.filter(
            district_type="secondary",
            school_count__gt=0,
            # Yesterday decides whether today is a return day.
            visit_date__gte=today - ONE_DAY,
        )
        .order_by("visit_date", "id")
        .values_list("id", "responsible_user", "visit_date", "rate_snapshot")
    )
    if not days:
        return []
    away = {(user, day) for _id, user, day, _rates in days}
    roles = {
        user_id: active_role or (list(roles or [])[:1] or [None])[0]
        for user_id, active_role, roles in User.objects.filter(
            id__in={user for _id, user, _day, _rates in days}
        ).values_list("id", "active_role", "roles")
    }
    stale = []
    for batch_id, user, day, rates in days:
        if day < today:
            continue
        priced_keys = set(rates or {}) & ACCOMMODATION_KEYS
        return_day = (user, day - ONE_DAY) in away and (user, day + ONE_DAY) not in away
        wrong_rate = bool(priced_keys) and (
            accommodation_key_for_role(roles.get(user)) not in priced_keys
        )
        if (not priced_keys) != return_day or wrong_rate:
            stale.append(batch_id)
    return stale


def reprice_days(ids=None, *, write=print, deadline=None) -> dict:
    """Re-price each stale day through the one day-pricing writer.

    ``deadline`` is a ``time.monotonic()`` value after which no further day
    is started; the days not reached are returned as ``left`` and are found
    again by a later run."""
    from .models import DailyVisitBatch
    from .services import (
        _PLANNED_DAY_STATUSES,
        _is_locked,
        _recalculate_and_write_lines,
    )
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

    ids = find_days_to_reprice() if ids is None else list(ids)
    repriced: list[str] = []
    skipped: list[str] = []
    left: list[str] = []
    for batch in DailyVisitBatch.objects.filter(id__in=ids).order_by(
        "visit_date", "id"
    ):
        if deadline is not None and time.monotonic() >= deadline:
            left.append(batch.id)
            continue
        if not night_is_stale(batch):
            # Re-pricing its neighbour has already settled it.
            continue
        label = f"{batch.id} ({batch.responsible_user}, {batch.visit_date})"
        worked = (
            batch.activities.filter(deleted_at__isnull=True)
            .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
            .exclude(status__in=_PLANNED_DAY_STATUSES)
            .exists()
        )
        if worked or _is_locked(batch.responsible_user, batch.visit_date):
            skipped.append(batch.id)
            write(
                f"  kept {label}: "
                + ("already worked." if worked else "its week has left draft.")
            )
            continue
        before = batch.daily_pool_amount
        try:
            with transaction.atomic():
                locked = DailyVisitBatch.objects.select_for_update().get(pk=batch.pk)
                _recalculate_and_write_lines(locked, None, locked.responsible_user)
                after = locked.daily_pool_amount
        except BadRequest as exc:
            skipped.append(batch.id)
            write(f"  kept {label}: {getattr(exc, 'detail', exc)}")
            continue
        repriced.append(batch.id)
        write(f"  re-priced {label}: UGX {before:,} -> UGX {after:,}")
    return {"repriced": repriced, "skipped": skipped, "left": left}


#: Work still a plan: the owner may yet move it, and so may a rule.
_PLANNED_STATUSES = ("planned", "scheduled", "rescheduled")


def find_trips_to_reprice(apps=None, *, today=None) -> list[str]:
    """Ids of planned staff work of several days that still charges a night
    for every one of them, earliest first.

    A trip in a secondary district sleeps away every night but the last
    (owner, 2026-10-05); one priced before that carries as many nights as
    days. Read off the saved accommodation lines, so a trip in the home
    district, which has none, is never listed."""
    from django.db.models import Q, Sum

    if apps is not None:
        Activity = apps.get_model("activities", "Activity")
        CostLine = apps.get_model("activities", "ActivityScheduleCostLine")
    else:
        from apps.activities.models import Activity
        from apps.activities.models import ActivityScheduleCostLine as CostLine

    today = today or timezone.localdate()
    trips = {
        activity_id: (end - start).days + 1
        for activity_id, start, end in Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="staff",
            status__in=_PLANNED_STATUSES,
            planned_date__gte=today,
            end_date__isnull=False,
        ).values_list("id", "planned_date", "end_date")
        if end > start
    }
    if not trips:
        return []
    # A night's line is stored once, or once a month for a trip that crosses
    # one ("<key>#mYYYYMM"): the nights are their sum.
    night_lines = Q()
    for key in ACCOMMODATION_KEYS:
        night_lines |= Q(cost_setting_key=key) | Q(
            cost_setting_key__startswith=f"{key}#"
        )
    nights = dict(
        CostLine.objects.filter(night_lines, activity_id__in=trips)
        .values_list("activity_id")
        .annotate(nights=Sum("quantity"))
    )
    stale = [
        activity_id
        for activity_id, days in trips.items()
        if nights.get(activity_id) and nights[activity_id] != days - 1
    ]
    order = dict(
        Activity.objects.filter(id__in=stale).values_list("id", "planned_date")
    )
    return sorted(stale, key=lambda activity_id: (order[activity_id], activity_id))


def reprice_trips(ids=None, *, write=print, deadline=None) -> dict:
    """Re-price each stale trip through the one cost writer, which also
    rebuilds its draft weekly and monthly requests.

    A trip whose money has moved, or whose request has left draft, is refused
    by the writer's finance locks; it is reported and left as it is rather
    than failing the rest. ``deadline`` works as in ``reprice_days``."""
    from apps.activities.models import Activity
    from apps.activities.services import reprice_activity

    ids = find_trips_to_reprice() if ids is None else list(ids)
    repriced: list[str] = []
    skipped: list[str] = []
    left: list[str] = []
    for activity in Activity.objects.filter(id__in=ids).order_by("planned_date", "id"):
        if deadline is not None and time.monotonic() >= deadline:
            left.append(activity.id)
            continue
        label = (
            f"{activity.id} ({activity.activity_name_snapshot or activity.activity_type}, "
            f"{activity.planned_date} to {activity.end_date})"
        )
        before = activity.est_cost_cents or 0
        try:
            with transaction.atomic():
                reprice_activity(activity)
        except BadRequest as exc:
            skipped.append(activity.id)
            write(f"  kept {label}: {getattr(exc, 'detail', exc)}")
            continue
        activity.refresh_from_db(fields=["est_cost_cents"])
        repriced.append(activity.id)
        write(
            f"  re-priced {label}: UGX {before:,} -> "
            f"UGX {activity.est_cost_cents or 0:,}"
        )
    return {"repriced": repriced, "skipped": skipped, "left": left}


__all__ = [
    "night_is_stale",
    "find_days_to_reprice",
    "reprice_days",
    "find_trips_to_reprice",
    "reprice_trips",
]
