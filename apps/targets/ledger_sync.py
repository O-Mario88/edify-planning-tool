"""Rebuild the achievement ledger only for the officers whose sources changed.

The ledger is derived from three sources: an officer's activities, the SSAs
they collected and their Most Significant Change stories. Leadership pages
(Team Targets, CD/RVP analytics, team rosters) rebuilt every officer's
ledger on each load, about 2 s for 150 officers at 50,000 schools
(2026-09-24 A+ audit, F-D, owner-approved).

Now every write to a source marks its officer and year "dirty" in the same
transaction (one upsert), and a page calls `refresh_many`, which rebuilds
only the dirty members of its roster and clears their marks. A change made
through a model save or delete is therefore on the next page load exactly as
before, and a page with nothing dirty writes nothing. Writes that bypass
model signals mark explicitly (`mark`), a change to the target areas marks
everyone, and `target_ledger_sync` (every 30 min) still rebuilds every active
officer as the backstop.

Each model remembers the owner and date it was loaded with, so a reassigned
activity marks its previous owner too, and a date moved across the fiscal
year boundary marks both years. Reading those values from the instance
`__dict__` never loads a deferred field.
"""

from __future__ import annotations

from datetime import date, datetime
from functools import reduce
from operator import or_

from django.db.models import Q
from django.db.models.signals import post_delete, post_init, post_save
from django.utils import timezone


def _fy_of(value) -> str | None:
    from apps.core.fy import get_operational_fy

    if isinstance(value, (date, datetime)):
        return get_operational_fy(value)
    return None


def mark(owner_ids, fys) -> None:
    """Mark these owners (user or staff-profile ids) dirty for these years."""
    from apps.targets.models import TargetLedgerDirty

    owner_ids = sorted({str(o) for o in owner_ids if o})
    fys = sorted({str(fy) for fy in fys if fy})
    if not owner_ids or not fys:
        return
    now = timezone.now()
    TargetLedgerDirty.objects.bulk_create(
        [
            TargetLedgerDirty(owner_id=owner, fy=fy, marked_at=now)
            for owner in owner_ids
            for fy in fys
        ],
        update_conflicts=True,
        unique_fields=["owner_id", "fy"],
        update_fields=["marked_at"],
    )


def mark_sources(pairs) -> None:
    """Mark (owner id, source date) pairs: for writes that bypass model
    signals, such as a bulk import."""
    by_fy: dict[str, set] = {}
    for owner, when in pairs:
        fy = _fy_of(when)
        if owner and fy:
            by_fy.setdefault(fy, set()).add(owner)
    for fy, owners in by_fy.items():
        mark(owners, {fy})


def mark_everyone() -> None:
    """Every officer with a ledger, for every year it holds, and every
    active officer for the operational year: what a change to the target
    areas themselves invalidates."""
    from apps.accounts.models import User
    from apps.core.fy import get_operational_fy
    from apps.targets.models import TargetAchievementLedger

    pairs = set(TargetAchievementLedger.objects.values_list("user_id", "fy").distinct())
    fy = get_operational_fy()
    pairs |= {
        (uid, fy)
        for uid in User.objects.filter(
            status="active", deleted_at__isnull=True
        ).values_list("id", flat=True)
    }
    for year in {y for _u, y in pairs}:
        mark({u for u, y in pairs if y == year}, {year})


def refresh_many(users, fy: str) -> None:
    """Bring these users' ledgers for `fy` up to date: rebuild the ones
    marked dirty, then clear exactly the marks that rebuild answered.

    A mark written while the rebuild ran has a newer `marked_at` and
    survives, so the next load picks it up.
    """
    from apps.targets.models import TargetLedgerDirty
    from apps.targets.my_targets import TargetAchievementService, _user_ids

    users = list(users)
    ids_of = {u.id: set(map(str, _user_ids(u))) for u in users}
    owners = set().union(*ids_of.values()) if ids_of else set()
    if not owners:
        return
    marks = list(
        TargetLedgerDirty.objects.filter(fy=fy, owner_id__in=owners).values_list(
            "id", "owner_id", "marked_at"
        )
    )
    if not marks:
        return
    dirty = {owner for _id, owner, _at in marks}
    stale = [u for u in users if ids_of[u.id] & dirty]
    TargetAchievementService.rebuild_many(stale, fy)
    TargetLedgerDirty.objects.filter(
        reduce(or_, (Q(id=pk, marked_at=at) for pk, _owner, at in marks))
    ).delete()


def _remember(owner_field, date_field):
    def handler(sender, instance, **kwargs):
        loaded = instance.__dict__
        instance._ledger_was = (
            loaded.get(owner_field),
            loaded.get(date_field),
            loaded.get("activity_type"),
        )

    return handler


def _changed(owner_field, date_field, relevant=None):
    def handler(sender, instance, **kwargs):
        now = instance.__dict__
        was_owner, was_date, was_type = getattr(
            instance, "_ledger_was", (None, None, None)
        )
        current = (now.get(owner_field), now.get(date_field), now.get("activity_type"))
        instance._ledger_was = current
        if relevant is not None and not (relevant(current[2]) or relevant(was_type)):
            return
        mark({was_owner, current[0]}, {_fy_of(was_date), _fy_of(current[1])})

    return handler


def _credited_activity_type(activity_type) -> bool:
    """Only activity types some target area counts can move the ledger."""
    from apps.targets.my_targets import AREA_SOURCES

    return any(
        stype == "activity" and activity_type in (types or ())
        for stype, types in AREA_SOURCES.values()
    )


def _areas_changed(sender, **kwargs):
    mark_everyone()


def connect() -> None:
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord
    from apps.targets.models import MostSignificantChangeStory, TargetArea

    sources = (
        (Activity, "responsible_staff_id", "planned_date", _credited_activity_type),
        (SsaRecord, "collected_by_user_id", "date_of_ssa", None),
        (MostSignificantChangeStory, "user_id", "story_date", None),
    )
    for model, owner_field, date_field, relevant in sources:
        uid = f"target_ledger_dirty_{model.__name__}"
        post_init.connect(
            _remember(owner_field, date_field),
            sender=model,
            weak=False,
            dispatch_uid=f"{uid}_init",
        )
        changed = _changed(owner_field, date_field, relevant)
        post_save.connect(changed, sender=model, weak=False, dispatch_uid=f"{uid}_save")
        post_delete.connect(
            changed, sender=model, weak=False, dispatch_uid=f"{uid}_delete"
        )
    for signal in (post_save, post_delete):
        signal.connect(
            _areas_changed,
            sender=TargetArea,
            weak=False,
            dispatch_uid=f"target_ledger_dirty_areas_{signal is post_save}",
        )
