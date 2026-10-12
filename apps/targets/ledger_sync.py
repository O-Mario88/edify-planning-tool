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


def _pairs(owner_ids, fys) -> set[tuple[str, str]]:
    return {(str(owner), str(fy)) for owner in owner_ids if owner for fy in fys if fy}


def _write_marks(pairs) -> None:
    from apps.targets.models import TargetLedgerDirty

    pairs = sorted(pairs)
    if not pairs:
        return
    now = timezone.now()
    TargetLedgerDirty.objects.bulk_create(
        [
            TargetLedgerDirty(owner_id=owner, fy=fy, marked_at=now)
            for owner, fy in pairs
        ],
        update_conflicts=True,
        unique_fields=["owner_id", "fy"],
        update_fields=["marked_at"],
    )


def mark(owner_ids, fys) -> None:
    """Mark these owners (user or staff-profile ids) dirty for these years."""
    _write_marks(_pairs(owner_ids, fys))


# ── The mark is written when the save commits ────────────────────────────────
# A mark is one row an officer and year, upserted. Written inside the save, its
# row stayed locked from the save's first write to its commit, so a second save
# for the same officer (a second tab, a click repeated because the first was
# slow, the re-pricing sweep) waited behind the whole of the first: in
# production the one-row write averaged 25.6 ms over 26,777 calls and waited up
# to 22.9 s (pg_stat_statements, 2026-10-12).
#
# A save now only remembers whom to mark, and the marks are written in one
# statement the moment its transaction commits: the row is locked for that
# statement and no longer. The rebuild is as correct as before, because it
# reads its marks first, rebuilds, and clears only the marks it read, by the
# time they were written (`refresh_many`): a mark that lands after the read
# survives it. What changes is one window: a page that reads the ledger
# between the commit and the mark shows the figures as they were, and the
# next read is right. A save that rolls back marks nobody, where it used to
# mark and lose the mark with the rollback, which is the same thing.
#
# Kept on the connection, in Django's own list of what to do on commit, so a
# savepoint that rolls back takes the marks first asked for inside it with it.
# A mark asked for later from a savepoint that then rolls back is kept: one
# rebuild that was not needed. `LEDGER_MARKS_AFTER_COMMIT=false` writes the
# mark inside the save again.
class _MarksOnCommit:
    """The officers and years to mark when the transaction in hand commits."""

    def __init__(self) -> None:
        self.pairs: set[tuple[str, str]] = set()

    def __call__(self) -> None:
        pairs, self.pairs = self.pairs, set()
        _write_marks(pairs)


def _marks_in_hand(connection):
    for _sids, callback, _robust in connection.run_on_commit:
        if isinstance(callback, _MarksOnCommit):
            return callback
    return None


def _marks_wait_for_commit(connection) -> bool:
    """Inside a transaction the application opened, with the switch on. The
    blocks a test case wraps its tests in do not count: they never commit."""
    from django.conf import settings

    return bool(getattr(settings, "LEDGER_MARKS_AFTER_COMMIT", False)) and any(
        not getattr(block, "_from_testcase", False)
        for block in connection.atomic_blocks
    )


def mark_when_committed(owner_ids, fys) -> None:
    """Mark these owners for these years when the transaction in hand commits;
    at once where there is none."""
    from django.db import transaction

    pairs = _pairs(owner_ids, fys)
    if not pairs:
        return
    connection = transaction.get_connection()
    if not _marks_wait_for_commit(connection):
        _write_marks(pairs)
        return
    waiting = _marks_in_hand(connection)
    if waiting is None:
        waiting = _MarksOnCommit()
        # robust: the save has committed by then, and a mark that could not
        # be written must not answer it with an error. `target_ledger_sync`
        # rebuilds every officer within the half hour.
        transaction.on_commit(waiting, robust=True)
    waiting.pairs |= pairs


def write_marks_in_hand() -> None:
    """Write now the marks waiting for this transaction's commit: for a read
    of the ledger made inside the transaction that changed its sources."""
    from django.db import transaction

    waiting = _marks_in_hand(transaction.get_connection())
    if waiting is not None:
        waiting()


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
    from apps.accounts.models import attach_staff_profile_ids
    from apps.targets.models import TargetLedgerDirty
    from apps.targets.my_targets import TargetAchievementService, _user_ids

    users = attach_staff_profile_ids(users)
    ids_of = {u.id: set(map(str, _user_ids(u))) for u in users}
    owners = set().union(*ids_of.values()) if ids_of else set()
    if not owners:
        return
    write_marks_in_hand()
    marks = list(
        TargetLedgerDirty.objects.filter(fy=fy, owner_id__in=owners).values_list(
            "id", "owner_id", "marked_at"
        )
    )
    if not marks:
        return
    global _generation
    _generation += 1  # marks remembered before this clear no longer stand
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
        owners = {was_owner, current[0]}
        fys = {_fy_of(was_date), _fy_of(current[1])}
        from django.db import transaction

        if _marks_wait_for_commit(transaction.get_connection()):
            mark_when_committed(owners, fys)
            return
        if _already_marked(instance, owners, fys):
            return
        mark(owners, fys)
        _remember_mark(instance, owners, fys)

    return handler


# ── One mark per row per transaction ─────────────────────────────────────────
# Within one web request (and only there — see _row_marks), scheduling one
# visit saves its Activity five times (create, catalogue
# snapshot, plan alignment, batch, cost) and each save upserted the same mark.
# The first upsert is enough while its transaction is still open: the row
# commits with every later change to the activity, and the rebuild reads the
# activity as committed. So a save repeats the upsert only when the owner or
# year changed, or when the transaction holding the first mark has ended or
# lost it to a savepoint rollback.
#
# "Still open" is read from Django's own bookkeeping: the first mark queues a
# no-op on_commit sentinel, and Django drops it from `run_on_commit` on commit,
# on rollback, and when the savepoint it was queued in rolls back. A
# `refresh_many` in the same transaction clears marks, so it also ends every
# remembered mark (_generation).
_generation = 0


def _mark_key(owners, fys):
    return (
        frozenset(str(o) for o in owners if o),
        frozenset(str(fy) for fy in fys if fy),
    )


def _row_marks():
    """Remembered marks by row, for the request in hand, or None outside a
    request (commands, jobs and direct service calls mark on every save, as
    before). Kept per request, not on the instance: the pricing steps re-read
    the Activity, so later saves come from other copies of the same row."""
    from apps.core.request_cache import store

    bucket = store()
    if bucket is None:
        return None
    return bucket.setdefault("targets.ledger_sync.row_marks", {})


def _row(instance):
    return (instance._meta.label, instance.pk)


def _already_marked(instance, owners, fys) -> bool:
    from django.db import transaction

    connection = transaction.get_connection()
    marks = _row_marks()
    if marks is None or not connection.in_atomic_block or instance.pk is None:
        return False
    remembered = marks.get(_row(instance))
    if remembered is None:
        return False
    key, sentinel, generation = remembered
    if key != _mark_key(owners, fys) or generation != _generation:
        return False
    return any(
        callback is sentinel for _sids, callback, _robust in connection.run_on_commit
    )


def _remember_mark(instance, owners, fys) -> None:
    from django.db import transaction

    connection = transaction.get_connection()
    marks = _row_marks()
    if marks is None:
        return
    if not connection.in_atomic_block or instance.pk is None:
        marks.pop(_row(instance), None)
        return
    # Entries whose transaction has ended are dead weight; drop them so the
    # dict never outlives more than the transaction in hand.
    live = {id(callback) for _sids, callback, _robust in connection.run_on_commit}
    for row in [r for r, (_k, s, _g) in marks.items() if id(s) not in live]:
        del marks[row]

    def sentinel():
        return None

    transaction.on_commit(sentinel)
    marks[_row(instance)] = (_mark_key(owners, fys), sentinel, _generation)


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
