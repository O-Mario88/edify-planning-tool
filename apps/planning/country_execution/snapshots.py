"""PeriodExecutionSnapshotService — lock each period's execution figures when it ends.

Spec §22 (owner, 2026-09-28): "At the end of each period, create a locked
oversight snapshot … Do not silently rewrite leadership reports."

**When.** Once a day the scheduler looks at the most recently ended week
(Monday to Sunday), month, quarter and financial year (October to September)
and locks each one that has no snapshot yet. A period is locked only within
``GRACE_DAYS`` of its end: later than that, the live figures have moved on,
and presenting them as the period-end result would be the rewrite the rule
forbids — such a period says it has no snapshot instead.

**What.** The same fold the page reads, for the whole country, as of the day
after the period's last day (so work due in it and not done by its end reads
overdue), with the original plan reconstructed from the schedule trail where
the period began after the trail did (dataset._integrity). Required-slot
completion is read from the planning coverage service for months, quarters and
years (a week has no phased requirement).

**Revisions.** A correction made later through the governed workflow changes
the live figures, never a snapshot. Where policy permits, a person may record
a revision: a new row read from the live figures now, naming the snapshot it
revises, with the reason, the person and the date. Nobody's revision replaces
the original; both are listed. Who may revise is ``REVISION_ROLES`` — the
Admin only until the owner approves a policy.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.planning.country_execution import dataset as ds
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight.coverage import Window, window_for

logger = logging.getLogger(__name__)

PERIOD_TYPES = ("week", "month", "quarter", "fy")
PERIOD_NAMES = {"week": "Week", "month": "Month", "quarter": "Quarter", "fy": "Year"}
#: How long after a period ends its closing snapshot may still be taken.
GRACE_DAYS = 14
#: Who may record a revision (no policy approved yet: the Admin only).
REVISION_ROLES = frozenset({"Admin"})

#: The figures a snapshot keeps for the country, each channel and each row.
ROW_FIGURES = (
    "due",
    "started",
    "executed",
    "pl_applicable",
    "pl_reviewed",
    "verified",
    "closed",
    "overdue",
    "returned",
    "cancelled",
    "carried_forward",
    "finance_open",
    "on_time",
)


class SnapshotError(Exception):
    """A snapshot could not be taken or revised; the message says why."""


# ── Which periods have ended ─────────────────────────────────────────────────
def ended_windows(today: date) -> list[Window]:
    """The most recently ended week, month, quarter and financial year."""
    from apps.core.fy import get_operational_fy, get_quarter_for_date

    monday = today - timedelta(days=today.weekday())
    last_week = monday - timedelta(days=7)
    windows = [window_for(get_operational_fy(last_week), "week", week_start=last_week)]
    last_month_day = today.replace(day=1) - timedelta(days=1)
    windows.append(
        window_for(
            get_operational_fy(last_month_day), "month", month=last_month_day.month
        )
    )
    this_quarter = window_for(
        get_operational_fy(today), "quarter", quarter=get_quarter_for_date(today)
    )
    before = this_quarter.start - timedelta(days=1)
    windows.append(
        window_for(
            get_operational_fy(before), "quarter", quarter=get_quarter_for_date(before)
        )
    )
    windows.append(window_for(str(int(get_operational_fy(today)) - 1), "fy"))
    return windows


def due_windows(today: date) -> list[Window]:
    """The ended periods still close enough to their end to be locked."""
    return [
        w
        for w in ended_windows(today)
        if w.end <= today and (today - w.end).days <= GRACE_DAYS
    ]


# ── Reading a period ─────────────────────────────────────────────────────────
def _named(tally) -> dict:
    return {name: getattr(tally, name) for name in ROW_FIGURES}


def _read(country: str, window: Window) -> dict:
    """The period's figures for the whole country, as of the day it ended."""
    from apps.planning.country_execution.service import ExecFilters, fold
    from apps.planning.country_oversight.service import system_scope

    as_of = window.end
    dataset = ds.build(system_scope(country), window, today=as_of)
    filters = ExecFilters(
        fy=window.fy,
        period=window.period,
        quarter=window.quarter or "",
        month=window.month,
        week=window.start.strftime("%G-W%V") if window.period == "week" else "",
    )
    tree = fold(dataset, filters)
    c = tree.country
    integrity = dataset.integrity
    tracked = bool(integrity.get("tracked"))
    figures = _named(c)
    figures.update(
        {
            "original_plan": integrity["original"] if tracked else None,
            "added": integrity["added"] if tracked else None,
            "rescheduled_in": integrity["moved_in"] if tracked else None,
            "rescheduled_out": integrity["moved_out"] if tracked else None,
            "plan_cancelled": integrity["cancelled"] if tracked else None,
            "current_plan": c.due,
            # Spec §7: due in the period and not IA verified by its end.
            "carryover": max(0, c.due - c.verified),
            "plan_tracked": tracked,
            "unique_schools": len(
                {
                    r.school_id
                    for r in dataset.records
                    if r.school_id and not r.cancelled
                }
            ),
            "slots": _slots(country, filters),
        }
    )
    names = dataset.partner_names
    hierarchy = [
        {
            "key": lead.key,
            "name": lead.name,
            "figures": _named(lead.tally),
            "owners": [
                {
                    "key": owner.key,
                    "name": owner.label,
                    "kind": owner.kind,
                    "figures": _named(owner.tally),
                    "partners": [
                        {
                            "key": key,
                            "name": "Staff delivery"
                            if key == ds.STAFF_KEY
                            else names.get(key, "Unrecorded Partner"),
                            "figures": _named(tally),
                        }
                        for key, tally in sorted(owner.partners.items())
                    ],
                }
                for owner in lead.owners
                if owner.tally.due
                or owner.tally.cancelled
                or owner.tally.carried_forward
            ],
        }
        for lead in tree.leads
    ]
    return {
        "as_of": as_of,
        "figures": figures,
        "channels": {
            "staff": _named(tree.staff),
            "partner": _named(tree.partner_channel),
        },
        "hierarchy": hierarchy,
        "follow_ups": _open_follow_ups(country),
    }


def _slots(country: str, filters) -> dict | None:
    """Required-slot completion for the period (spec §4.2), from the planning
    coverage service; a week has no phased requirement."""
    if filters.period == "week":
        return None
    from apps.planning.country_oversight import service as planning

    try:
        pfilters = filters.planning()
        dataset = planning.build_dataset(
            planning.system_scope(country), pfilters.window
        )
        t = planning.fold(dataset, pfilters).country
    except Exception:  # noqa: BLE001 - a snapshot without slots beats none
        logger.warning("Required-slot completion could not be read", exc_info=True)
        return None
    return {
        "visit_slots": t.visit_slots,
        "visits_verified": t.staff_verified + t.partner_verified,
        "training_slots": t.training_slots,
        "trainings_verified": t.training_verified,
        "remaining": max(0, t.visit_slots - t.staff_verified - t.partner_verified)
        + max(0, t.training_slots - t.training_verified),
    }


def _open_follow_ups(country: str) -> list[dict]:
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    rows = PlanningOversightFollowUp.objects.filter(
        module="execution", status__in=OPEN_FOLLOW_UP_STATES, country=country
    ).order_by("assigned_at")
    return [
        {
            "id": f.id,
            "issue": f.issue_type,
            "lead": f.program_lead_name,
            "cceo": f.cceo_name,
            "partner": f.partner_name,
            "activity": f.activity_label,
            "status": f.status,
            "open": f.remaining_value,
            "sent": timezone.localtime(f.assigned_at).date().isoformat()
            if f.assigned_at
            else "",
            "due": f.due_date.isoformat() if f.due_date else "",
        }
        for f in rows[:500]
    ]


# ── Locking ──────────────────────────────────────────────────────────────────
def window_of(snapshot) -> Window:
    """The period a snapshot locked, as a window."""
    from apps.core.fy import get_quarter_for_date

    return window_for(
        snapshot.fy,
        snapshot.period_type,
        quarter=get_quarter_for_date(snapshot.period_start)
        if snapshot.period_type == "quarter"
        else None,
        month=snapshot.period_start.month if snapshot.period_type == "month" else None,
        week_start=snapshot.period_start if snapshot.period_type == "week" else None,
    )


def latest(country: str, window: Window):
    from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

    return (
        ExecutionPeriodSnapshot.objects.filter(
            country=country, period_type=window.period, period_start=window.start
        )
        .order_by("-version")
        .first()
    )


def take(country: str, window: Window, *, today: date | None = None):
    """Lock a period's original snapshot. Never a second one for a period."""
    from apps.planning.execution_snapshot_models import (
        ExecutionPeriodSnapshot,
        SnapshotKind,
    )

    if window.end > (today or timezone.localdate()):
        raise SnapshotError(f"{window.label} has not ended.")
    if latest(country, window) is not None:
        raise SnapshotError(f"{window.label} is already locked.")
    read = _read(country, window)
    try:
        with transaction.atomic():
            return ExecutionPeriodSnapshot.objects.create(
                country=country,
                fy=window.fy,
                period_type=window.period,
                period_start=window.start,
                period_end=window.end,
                period_label=window.label,
                version=1,
                kind=SnapshotKind.ORIGINAL,
                as_of=read["as_of"],
                stage_policy=st.STAGE_POLICY,
                figures=read["figures"],
                channels=read["channels"],
                hierarchy=read["hierarchy"],
                follow_ups=read["follow_ups"],
            )
    except IntegrityError as exc:
        raise SnapshotError(f"{window.label} was locked at the same moment.") from exc


def may_revise(user) -> bool:
    return (getattr(user, "active_role", "") or "") in REVISION_ROLES


def revise(snapshot, actor, reason: str):
    """Record a revision of a locked period from the live figures now: a new
    version beside the original, with the reason, the person and the date."""
    from apps.audit.services import log
    from apps.planning.execution_snapshot_models import (
        ExecutionPeriodSnapshot,
        SnapshotKind,
    )

    if not may_revise(actor):
        raise SnapshotError(
            "Revising a locked period snapshot needs an approved policy role."
        )
    reason = (reason or "").strip()
    if not reason:
        raise SnapshotError("Say why the period's snapshot is being revised.")
    window = window_of(snapshot)
    current = latest(snapshot.country, window)
    read = _read(snapshot.country, window)
    try:
        with transaction.atomic():
            revision = ExecutionPeriodSnapshot.objects.create(
                country=snapshot.country,
                fy=snapshot.fy,
                period_type=snapshot.period_type,
                period_start=snapshot.period_start,
                period_end=snapshot.period_end,
                period_label=snapshot.period_label,
                version=current.version + 1,
                kind=SnapshotKind.REVISION,
                revises=current,
                reason=reason,
                as_of=read["as_of"],
                taken_by_id=str(getattr(actor, "id", "") or ""),
                taken_by_name=getattr(actor, "name", "")
                or getattr(actor, "email", "")
                or "",
                stage_policy=st.STAGE_POLICY,
                figures=read["figures"],
                channels=read["channels"],
                hierarchy=read["hierarchy"],
                follow_ups=read["follow_ups"],
            )
    except IntegrityError as exc:
        raise SnapshotError(
            "Someone has just revised this period. Open it again."
        ) from exc
    try:
        log(
            action="execution_snapshot.revised",
            subject_kind="ExecutionPeriodSnapshot",
            subject_id=revision.id,
            actor_id=getattr(actor, "id", None) or "system",
            actor_role=getattr(actor, "active_role", None) or "system",
            payload={
                "revises": current.id,
                "version": revision.version,
                "country": snapshot.country,
                "period": snapshot.period_label,
                "reason": reason,
            },
        )
    except Exception:  # noqa: BLE001 - the revision itself is the record
        logger.warning("Could not audit the snapshot revision", exc_info=True)
    return revision


def lock_ended_periods(today: date | None = None) -> int:
    """The scheduled close: lock every recently ended period not yet locked,
    for each country the oversight is read in. Returns how many were locked."""
    from apps.planning.country_oversight.service import warm_targets

    today = today or timezone.localdate()
    countries = sorted({country for country, _filters in warm_targets(today)})
    locked = 0
    failed: Exception | None = None
    for country in countries:
        for window in due_windows(today):
            if latest(country, window) is not None:
                continue
            try:
                take(country, window, today=today)
            except SnapshotError:
                continue
            except Exception as exc:  # noqa: BLE001 - one period must not stop the rest
                logger.exception("Could not lock %s %s", country, window.label)
                failed = failed or exc
                continue
            locked += 1
    if failed is not None:
        raise failed
    return locked


# ── Reading snapshots back ───────────────────────────────────────────────────
def for_window(country: str, window: Window) -> list:
    """Every version of a period's snapshot, the original first."""
    from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

    return list(
        ExecutionPeriodSnapshot.objects.filter(
            country=country, period_type=window.period, period_start=window.start
        ).order_by("version")
    )


def listing(country: str, *, period_type: str = "") -> list:
    """The country's locked periods, the latest first, each with its versions
    (the drawer shows them a page at a time)."""
    from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

    rows = ExecutionPeriodSnapshot.objects.filter(country=country).defer(
        "hierarchy", "follow_ups", "channels"
    )
    if period_type in PERIOD_TYPES:
        rows = rows.filter(period_type=period_type)
    grouped: dict[tuple, list] = {}
    for snapshot in rows.order_by("-period_end", "period_type", "version"):
        grouped.setdefault((snapshot.period_type, snapshot.period_start), []).append(
            snapshot
        )
    periods = []
    for versions in grouped.values():
        original = versions[0]
        periods.append(
            {
                "original": original,
                "latest": versions[-1],
                "versions": versions,
                "type_label": PERIOD_NAMES.get(
                    original.period_type, original.period_type
                ),
            }
        )
    return periods


class PeriodExecutionSnapshotService:
    """The period snapshots, as one importable surface."""

    ended_windows = staticmethod(ended_windows)
    take = staticmethod(take)
    revise = staticmethod(revise)
    lock_ended_periods = staticmethod(lock_ended_periods)
    for_window = staticmethod(for_window)
    listing = staticmethod(listing)
