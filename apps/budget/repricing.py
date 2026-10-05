"""Bring plans already made up to the Cost Catalogue as it now stands.

Owner, 2026-10-05: "I still see the old cost being fetched like even when the
cost is changed or deleted, it still fetches."

A plan is priced when it is scheduled and keeps the lines it was priced with:
the rate, the catalogue and its version. Saving a rate in Cost Settings
publishes a new version of the catalogue, and until now that was all it did,
so every activity already on a plan went on carrying the old rate, and the
weekly request, which fetches those lines, went on asking for the old money.

Work that is still a plan now follows the catalogue. `stale_plan_ids` finds
the open plans whose saved lines no longer agree with it:

* a line priced at a rate that has since changed;
* a line under a cost that is no longer in the catalogue;
* a plan of an activity the Country Director has since added a cost for,
  which has no line for it.

`reprice_stale_plans` puts each one through the single cost writer
(`apps.activities.services.reprice_activity`), which also rebuilds its draft
weekly and monthly requests, each in its own transaction.

What is left as it was priced, as everywhere else: work that has been carried
out, work money has moved on, and work whose weekly request has left draft
(the writer's own finance locks refuse it). Those are history, and the cost
they were approved at is the cost they keep.

It runs when a rate is saved or a cost is added (`apps.budget.services`), for
as long as a request can spare; a scheduled job (`cost_reprice_sweep`) and
``manage.py reprice_stale_cost_plans --apply`` take up what is left.
"""

from __future__ import annotations

import logging
import time

from django.db import transaction

from apps.core.exceptions import BadRequest

logger = logging.getLogger(__name__)

#: Work still a plan: staff's own, and a Partner's before it is delivered.
OPEN_STATUSES = (
    "planned",
    "scheduled",
    "rescheduled",
    "assigned_to_partner",
    "partner_scheduled",
)
UNPAID_PAYMENT_STATUSES = ("", "none")

#: How long a rate change spends re-pricing inside the Country Director's own
#: request before handing the rest to the scheduled sweep.
INLINE_SECONDS = 12.0


def _base_key(key: str) -> str:
    """A line of a trip that crosses a month is stored "<key>#mYYYYMM"."""
    return (key or "").split("#", 1)[0]


def _rates(catalogue_id) -> dict[str, int]:
    from apps.budget.models import CostSetting

    return dict(
        CostSetting.objects.filter(catalogue_id=catalogue_id).values_list(
            "key", "unit_cost"
        )
    )


def stale_plan_ids(*, limit: int | None = None) -> list[str]:
    """Ids of the open, unpaid plans whose saved cost no longer agrees with
    the active Cost Catalogue, soonest first."""
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.budget.costing_service import active_catalogue
    from apps.budget.models import CostSetting

    active = active_catalogue()
    if active is None:
        return []
    open_plans = Activity.objects.filter(
        deleted_at__isnull=True,
        status__in=OPEN_STATUSES,
        payment_status__in=UNPAID_PAYMENT_STATUSES,
    )
    now = _rates(active.id)
    before: dict[str, dict[str, int]] = {}
    stale: set[str] = set()
    # Plans priced against an earlier version of the catalogue. One priced
    # against this version is settled, whatever it holds: looking at it again
    # would re-price it on every run for ever.
    behind: set[str] = set()
    # Stale where a rate a line was priced at has changed since, or the cost
    # is no longer in the catalogue.
    for activity_id, key, catalogue_id in (
        ActivityScheduleCostLine.objects.filter(activity__in=open_plans)
        .exclude(catalogue_id=active.id)
        .exclude(catalogue_id__isnull=True)
        .values_list("activity_id", "cost_setting_key", "catalogue_id")
        .distinct()
    ):
        behind.add(activity_id)
        if activity_id in stale:
            continue
        key = _base_key(key)
        if catalogue_id not in before:
            before[catalogue_id] = _rates(catalogue_id)
        then = before[catalogue_id].get(key)
        if key not in now or (then is not None and then != now[key]):
            stale.add(activity_id)

    # A cost added for one activity is priced on every schedule of it: a plan
    # of that activity priced before the cost existed has no line for it.
    if behind - stale:
        for key, item_id in CostSetting.objects.filter(
            catalogue=active, catalogue_item__isnull=False
        ).values_list("key", "catalogue_item_id"):
            of_item = set(
                open_plans.filter(
                    catalogue_item_id=item_id, id__in=behind - stale
                ).values_list("id", flat=True)
            )
            if not of_item:
                continue
            with_line = set(
                ActivityScheduleCostLine.objects.filter(
                    activity_id__in=of_item, cost_setting_key=key
                ).values_list("activity_id", flat=True)
            )
            stale |= of_item - with_line

    if not stale:
        return []
    ordered = list(
        Activity.objects.filter(id__in=stale)
        .order_by("planned_date", "id")
        .values_list("id", flat=True)
    )
    return ordered[:limit] if limit else ordered


def reprice_stale_plans(ids=None, *, deadline=None, write=None) -> dict:
    """Re-price each stale plan through the one cost writer.

    ``deadline`` is a ``time.monotonic()`` value after which no further plan
    is started; those not reached are returned as ``left`` and are found
    again by a later run. A plan the writer refuses (its week has left
    draft, its money has moved) is ``kept`` at the cost it was approved at.
    """
    from apps.activities.models import Activity
    from apps.activities.services import reprice_activity

    ids = stale_plan_ids() if ids is None else list(ids)
    result = {"repriced": [], "kept": [], "left": []}
    if not ids:
        return result
    say = write or (lambda _line: None)
    # A day's visits are priced together: re-pricing one settles the others.
    settled_days: set[str] = set()
    for activity in Activity.objects.filter(id__in=ids).order_by("planned_date", "id"):
        if deadline is not None and time.monotonic() >= deadline:
            result["left"].append(activity.id)
            continue
        if activity.daily_visit_batch_id in settled_days:
            result["repriced"].append(activity.id)
            continue
        before = activity.est_cost_cents or 0
        try:
            with transaction.atomic():
                reprice_activity(activity)
        except BadRequest as exc:
            result["kept"].append(activity.id)
            say(f"  kept {activity.id}: {getattr(exc, 'detail', exc)}")
            continue
        except Exception:  # noqa: BLE001 - one plan never stops the sweep
            logger.exception("Re-pricing failed for activity %s", activity.id)
            result["kept"].append(activity.id)
            say(f"  kept {activity.id}: could not be re-priced (logged)")
            continue
        activity.refresh_from_db(fields=["est_cost_cents", "daily_visit_batch"])
        if activity.daily_visit_batch_id:
            settled_days.add(activity.daily_visit_batch_id)
        result["repriced"].append(activity.id)
        say(
            f"  re-priced {activity.id}: UGX {before:,} -> "
            f"UGX {activity.est_cost_cents or 0:,}"
        )
    return result


def reprice_after_catalogue_change() -> dict:
    """What a saved rate or an added cost does to the plans already made:
    re-price them for as long as the request can spare, and say how many were
    done, kept and left for the sweep. Never the reason the save fails."""
    try:
        return reprice_stale_plans(deadline=time.monotonic() + INLINE_SECONDS)
    except Exception:  # noqa: BLE001 - the rate is saved; the sweep follows
        logger.exception("Re-pricing after a catalogue change failed")
        return {"repriced": [], "kept": [], "left": []}


def summary(result: dict) -> str:
    """One sentence for the person who changed the catalogue."""
    done, kept, left = (len(result[k]) for k in ("repriced", "kept", "left"))
    if not (done or kept or left):
        return "No planned activity was priced with it."
    parts = []
    if done:
        parts.append(
            f"{done} planned activit{'y' if done == 1 else 'ies'} re-priced at "
            "the new cost"
        )
    if left:
        parts.append(f"{left} more will be re-priced in the next few minutes")
    if kept:
        parts.append(
            f"{kept} kept at the cost already approved (their week has been "
            "submitted or money has moved)"
        )
    return "; ".join(parts).capitalize() + "."
