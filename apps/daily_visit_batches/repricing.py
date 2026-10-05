"""Bring days planned before a pricing rule up to the rule.

Two rules of 2026-10-05 change what a night away costs, and a day planned
before them keeps the price it was planned at until something re-prices it:

* the last of a run of days in a secondary district is the day the traveller
  comes home, with no night and no dinner (``return_day``);
* the Program Lead, the Country Director, Impact Assessment and the
  Accountant sleep at their own accommodation rate (``districts``).

``find_days_to_reprice`` lists the planned days that still carry the old
price and ``reprice_days`` re-prices them one at a time, each in its own
transaction. A day whose week has left draft, whose money has moved or whose
work is done is left as it was priced. Daily visit batches migration 0003
runs both inside the deploy's time limit; ``refresh_daily_cost_allocations
--apply`` picks up whatever it did not reach.
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


__all__ = ["night_is_stale", "find_days_to_reprice", "reprice_days"]
