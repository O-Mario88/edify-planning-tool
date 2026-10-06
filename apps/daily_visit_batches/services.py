"""
DailyVisitBatchService — the ONE path for scheduling staff-conducted school
visits. N=1 (a lone visit) and N>1 (bulk multi-school scheduling) both funnel
through `schedule_visits`, which is what makes "every school visit
creates/updates a DailyVisitBatch" true system-wide, not just for bulk
scheduling.

Validation order: unclassified district -> locked batch -> CD daily-target
cap (hard) -> CD daily-target floor (soft, needs a reason) -> create/attach ->
recalculate. Schools from any mix of districts may share a day: a day with any
secondary-district school is priced as one secondary day.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from datetime import date

from django.db import transaction
from django.db.models import Count, Q

from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

from .districts import accommodation_key_for_staff, district_type_for_staff
from .exceptions import ReasonRequiredError
from .models import DailyVisitBatch
from .pricing import ACCOMMODATION_KEYS, KEY_LABELS, allocate_pool, compute_daily_pool
from .return_day import ONE_DAY, away_on, is_return_day, priced_as_return_day


#: The days waiting for their price while a save that adds several visits is
#: in hand (`each_day_priced_once`), by batch id. None outside one.
_days_to_price: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "daily_visit_batches_days_to_price", default=None
)


@contextmanager
def each_day_priced_once():
    """Price a day once for all the visits this block adds to it.

    A visit joining a day re-prices every visit already on it, because the
    day's pool is shared. A save that adds five (the cluster's bulk day) did
    that after each one: five visits on an empty day were priced 1+2+3+4+5 =
    15 times, five more on that day 40 times, and each pricing writes a cost
    snapshot, an audit entry, its advance requests and a domain event, about
    32 statements. In production one such save ran 990 to 3,576 statements
    and took 5.6 to 18.9 seconds (performance audit, 2026-10-05, F11).

    Inside this block a visit joins its day and the day is remembered; when
    the block ends each remembered day is priced once, with all its members.
    The figures a day ends with are the ones it ended with before: they are
    computed from the same members, rates and neighbours, and
    `test_day_priced_once` holds the two ways to each other line by line.
    What changes, by the owner's decision of 2026-10-06, is the record of the
    steps nobody saw: a visit added with four others has cost snapshot 1,
    not snapshots 1 to 5, and one "cost calculated" audit entry, not five.

    It must be used inside the save's transaction: until the block ends the
    new visits carry no cost, and a refusal from the pricing (a member whose
    money has moved, a missing rate) has to undo the whole save, as it
    always did. Blocks nest; the outermost one prices. Only joining a day
    waits. A visit leaving a day, or moving between two, is priced at once,
    because what follows it (the week it left is re-filed from its lines)
    reads the result.

    ``PRICE_A_DAY_ONCE_PER_SAVE=false`` prices after every visit again.
    """
    from django.conf import settings
    from django.db import connection

    if _days_to_price.get() is not None or not getattr(
        settings, "PRICE_A_DAY_ONCE_PER_SAVE", True
    ):
        yield
        return
    if not connection.in_atomic_block:
        raise RuntimeError(
            "each_day_priced_once() must run inside the save's transaction: "
            "outside one, a failure before the day is priced would leave "
            "scheduled visits with no cost."
        )
    days: dict[str, tuple] = {}
    token = _days_to_price.set(days)
    try:
        yield
    finally:
        _days_to_price.reset(token)
    for batch_id, (catalogue, responsible_user_id) in days.items():
        batch = DailyVisitBatch.objects.select_for_update().get(id=batch_id)
        _recalculate_and_write_lines(batch, catalogue, responsible_user_id)


def _price_when_the_save_ends(batch, catalogue, responsible_user_id: str) -> bool:
    """Remember this day for `each_day_priced_once`; False outside one."""
    days = _days_to_price.get()
    if days is None:
        return False
    # Asked again for the same day, the latest asking stands, as the latest
    # pricing did when each visit was priced as it joined.
    days.pop(batch.id, None)
    days[batch.id] = (catalogue, responsible_user_id)
    return True


def _catalogue_for_batch_date(visit_date: date):
    """Resolve the CD rate card effective for this batch's activity date.

    A batch has one visit date, so it must never borrow a catalogue from a
    different fiscal year merely because that catalogue has a higher version.
    """
    from apps.budget.costing_service import active_catalogue
    from apps.core.fy import get_operational_fy

    return active_catalogue(get_operational_fy(visit_date), on_date=visit_date)


def _is_locked(responsible_user: str, visit_date: date) -> bool:
    """The exact lock boundary already used everywhere else in this codebase:
    a batch may be recalculated only while its week's WeeklyFundRequest is in
    an OWNER-HELD state (draft or returned — the generator's rebuildable set)
    or doesn't exist yet. A returned week is back in the owner's hands, so
    its batches must be repairable; excluding only the draft status made
    every return a dead end for pool corrections too."""
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.fund_requests.weekly_service import REBUILDABLE_WEEKLY_STATUSES

    return (
        WeeklyFundRequest.objects.filter(
            responsible_user=responsible_user,
            week_start_date__lte=visit_date,
            week_end_date__gte=visit_date,
        )
        .exclude(status__in=REBUILDABLE_WEEKLY_STATUSES)
        .exists()
    )


def batch_needs_repricing(batch) -> bool:
    """Detect old splits without rewriting immutable, approved snapshots."""
    from apps.budget.models import ActivityCostSnapshot

    members = batch.activities.filter(deleted_at__isnull=True).exclude(
        status__in=NON_FUNDABLE_ACTIVITY_STATUSES
    )
    if members.count() != batch.school_count:
        return True
    expected_type = (
        "secondary"
        if any(
            district_type_for_staff(batch.responsible_user, member_district(member))
            == "secondary"
            for member in members.select_related(
                "school__district", "cluster__district", "event_district"
            )
        )
        else "primary"
    )
    if expected_type != batch.district_type:
        return True
    # The day the traveller comes home has no night and no dinner (owner,
    # 2026-10-05); a day priced before that rule, or whose neighbours have
    # since changed, still carries them, or lacks them.
    if (
        expected_type == "secondary"
        and batch.school_count
        and priced_as_return_day(batch)
        != is_return_day(batch.responsible_user, batch.visit_date)
    ):
        return True
    snapshots = list(
        ActivityCostSnapshot.objects.filter(activity__in=members, is_current=True)
    )
    # A night priced before the accommodation rates were split (2026-10-05)
    # sits under the CCEO's rate whoever travelled.
    accommodation_key = accommodation_key_for_staff(batch.responsible_user)
    return len(snapshots) != batch.school_count or any(
        line.get("dailyAllocation", {}).get("policy") != "staff-day-v2"
        or line.get("dailyAllocation", {}).get("count") != batch.school_count
        or (
            line.get("key") in ACCOMMODATION_KEYS
            and line.get("key") != accommodation_key
        )
        for snapshot in snapshots
        for line in snapshot.operational_breakdown
        if line.get("key") in KEY_LABELS
    )


def resync_stale_batches(responsible_user: str, week_start, week_end) -> int:
    """Recompute this owner's unlocked week batches whose live member count no
    longer matches the priced split.

    A member cancelled while the week was LOCKED leaves the surviving schools
    priced for N schools with only N-1 active (the detach deliberately leaves
    frozen snapshots alone — audit L-7). The freeze lifting (a return) is the
    moment the pool can be made honest again; the return actions call this so
    the corrected week is what gets re-submitted."""
    repaired = 0
    for batch in DailyVisitBatch.objects.filter(
        responsible_user=responsible_user,
        visit_date__gte=week_start,
        visit_date__lte=week_end,
    ):
        if _is_locked(batch.responsible_user, batch.visit_date):
            continue
        if batch_needs_repricing(batch):
            with transaction.atomic():
                _recalculate_and_write_lines(batch, None, batch.responsible_user)
            repaired += 1
    return repaired


def _resolve_group(district_ids: set[str]):
    """The approved SecondaryDistrictGroup covering every one of these
    districts, if one exists. A label on the batch only — it never gates
    scheduling."""
    from apps.geography.models import SecondaryDistrictGroup

    if not district_ids:
        return None
    return (
        SecondaryDistrictGroup.objects.filter(status="approved")
        .annotate(
            n=Count(
                "members__district_id",
                distinct=True,
                filter=Q(members__district_id__in=district_ids),
            )
        )
        .filter(n=len(district_ids))
        .first()
    )


def schedule_visits(
    *,
    school_ids: list[str],
    scheduled_date: date,
    activity_common_fields: dict,
    reason: str | None,
    principal,
) -> dict:
    """Schedule N staff-conducted school visits for one staff member on one
    day, grouped into (or joining) that day's DailyVisitBatch."""
    from apps.schools.models import School
    from apps.activities.models import Activity
    from apps.activities.services import create as create_activity
    from apps.budget.costing_service import active_catalogue

    responsible_user_id = principal.user_id
    school_ids = list(school_ids)
    schools = list(
        School.objects.filter(
            school_id__in=school_ids, deleted_at__isnull=True
        ).select_related("district")
    )
    if len(schools) != len(set(school_ids)):
        raise NotFoundError("One or more schools not found.")

    # A district nobody has classified prices as a primary one, as it does
    # when a single visit is scheduled (`attach_activity_to_batch`). This
    # refused the whole day instead (owner, 2026-10-02: "lift that
    # restrictions"): planning waited on a master-data field.
    new_types: dict[str, str] = {}
    for s in schools:
        new_types[s.school_id] = (
            district_type_for_staff(responsible_user_id, s.district)
            if s.district_id
            else None
        ) or "primary"

    incoming_district_type = (
        "secondary" if "secondary" in new_types.values() else "primary"
    )

    with transaction.atomic():
        batch = (
            DailyVisitBatch.objects.select_for_update()
            .filter(responsible_user=responsible_user_id, visit_date=scheduled_date)
            .first()
        )

        if batch and _is_locked(responsible_user_id, scheduled_date):
            raise BadRequest(
                "This date's visits have already left draft status. To change the "
                "schools scheduled for this date, use Reschedule or Cancel on the "
                "individual visit instead."
            )

        existing_activities = (
            list(
                batch.activities.filter(deleted_at__isnull=True)
                .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
                .select_related(*_MEMBER_DISTRICT_RELATIONS)
            )
            if batch
            else []
        )
        # Guard against double-submission (e.g. a double-click on "Schedule
        # Activity"): if this staff member already has a live, non-cancelled
        # visit to one of these schools on this date — most likely the exact
        # same request landing twice — reject the repeat instead of silently
        # adding a second Activity for the same school/day into the batch.
        already_scheduled_pks = {
            a.school_id for a in existing_activities if a.school_id
        } & {s.id for s in schools}
        if already_scheduled_pks:
            dupe_names = ", ".join(
                s.name for s in schools if s.id in already_scheduled_pks
            )
            raise BadRequest(
                f"A visit is already scheduled for {dupe_names} on this date."
            )

        districts = [member_district(a) for a in existing_activities] + [
            school.district for school in schools if school.district_id
        ]
        all_district_ids = {
            d.id
            for d in districts
            if d and district_type_for_staff(responsible_user_id, d) == "secondary"
        }
        incoming_district_type = "secondary" if all_district_ids else "primary"

        catalogue = active_catalogue(activity_common_fields.get("fy"))
        target = catalogue.required_school_visits_per_day if catalogue else 5
        existing_count = len(existing_activities)
        total_after = existing_count + len(schools)

        if total_after > target:
            raise BadRequest(
                f"You can only schedule {target} for this date, please choose another date."
            )

        effective_reason = (reason or "").strip() or (batch.reason if batch else None)
        if total_after < target and not effective_reason:
            raise ReasonRequiredError(
                f"You scheduled {total_after} school(s). The CD target is {target} schools "
                f"per day. This will increase cost per school. Reason required."
            )

        if not batch:
            batch = DailyVisitBatch.objects.create(
                responsible_user=responsible_user_id,
                visit_date=scheduled_date,
                district_type=incoming_district_type,
                secondary_district_group=(
                    _resolve_group(all_district_ids)
                    if incoming_district_type == "secondary"
                    and len(all_district_ids) > 1
                    else None
                ),
            )
        if effective_reason and effective_reason != batch.reason:
            batch.reason = effective_reason
            batch.save(update_fields=["reason", "updated_at"])

        new_activities = []
        for s in schools:
            act_data = {
                **activity_common_fields,
                "schoolId": s.school_id,
                "scheduledDate": scheduled_date.isoformat(),
            }
            new_activities.append(
                create_activity(act_data, principal, skip_cost_snapshot=True)
            )

        Activity.objects.filter(id__in=[a["id"] for a in new_activities]).update(
            daily_visit_batch=batch
        )

        _recalculate_and_write_lines(batch, catalogue, responsible_user_id)

        # create() deliberately skipped costing. Return the saved allocations,
        # not the zero estimates from those pre-costing serialized objects.
        saved_costs = {
            a.id: a
            for a in Activity.objects.filter(id__in=[a["id"] for a in new_activities])
        }
        for item in new_activities:
            saved = saved_costs[item["id"]]
            item.update(
                estCostCents=saved.est_cost_cents, costMissing=saved.cost_missing
            )

        return {"batchId": batch.id, "activities": new_activities}


# What member_district() reads, for loading a day's members in one query.
_MEMBER_DISTRICT_RELATIONS = ("school__district", "cluster__district", "event_district")


def member_district(activity):
    """The district a member activity happens in: school first, then the
    cluster's district, then the event's own district. None means home —
    the activity runs in the owner's primary station and prices primary."""
    school = getattr(activity, "school", None)
    if school is not None and school.district_id:
        return school.district
    cluster = getattr(activity, "cluster", None)
    if cluster is not None and getattr(cluster, "district_id", None):
        return cluster.district
    if getattr(activity, "event_district_id", None):
        return activity.event_district
    return None


def batch_poolable(activity) -> bool:
    """Whether this activity's personal per-diems belong to the day pool.
    Multi-day field events keep their standalone per-day recipe — they own
    whole away-days by definition."""
    from apps.activities.pair_costing import is_uncosted_pair_training

    from .pricing import DAILY_BATCH_ELIGIBLE_TYPES, DAY_POOL_EXTRA_TYPES

    if activity.activity_type in DAILY_BATCH_ELIGIBLE_TYPES:
        # An in-school training's School Visit is the trip and shares the day
        # like any other visit; its Training is part of it and costs nothing.
        return bool(activity.school_id)
    if activity.activity_type not in DAY_POOL_EXTRA_TYPES:
        return False
    if is_uncosted_pair_training(activity):
        return False
    end = getattr(activity, "end_date", None)
    if end and activity.planned_date and end > activity.planned_date:
        return False
    return True


def attach_activity_to_batch(
    activity, *, responsible_user_id: str, reason: str | None = None
) -> bool:
    """Pool-price a just-created staff school visit by joining it to that
    day's DailyVisitBatch (creating one if needed), then recomputing the
    pooled split for every member.

    This is the create-time twin of ``reschedule_within_batch`` with the
    scheduling-policy rules deliberately relaxed: the generic scheduling
    funnel is permissive by design (no daily-target cap, no reason
    requirement), but the FINANCIAL treatment must still be the pooled 1/N
    share — otherwise each visit bills the entire day's transport/meal pool.

    Returns False only when the first day's pool rates are unavailable; the
    caller then records the missing-rate recipe. A locked request raises
    rather than silently bill another full daily pool.
    Must be called inside the caller's transaction.
    """
    district = member_district(activity)
    district_type = district_type_for_staff(responsible_user_id, district) or "primary"
    if district_type not in ("primary", "secondary"):
        return False

    batch = (
        DailyVisitBatch.objects.select_for_update()
        .filter(
            responsible_user=responsible_user_id,
            visit_date=activity.planned_date,
        )
        .first()
    )
    if _is_locked(responsible_user_id, activity.planned_date):
        raise BadRequest(
            "This week's request has already been sent for approval. "
            "Have it returned before changing the planned activities and daily cost shares."
        )

    existing_activities = (
        list(
            batch.activities.filter(deleted_at__isnull=True)
            .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
            .select_related(*_MEMBER_DISTRICT_RELATIONS)
        )
        if batch
        else []
    )
    districts = [member_district(a) for a in existing_activities] + [district]
    all_district_ids = {
        d.id
        for d in districts
        if d and district_type_for_staff(responsible_user_id, d) == "secondary"
    }
    district_type = "secondary" if all_district_ids else "primary"

    catalogue = _catalogue_for_batch_date(activity.planned_date)
    from apps.budget.costing_service import _rate_card

    rates, _by_key = _rate_card(catalogue)
    try:
        compute_daily_pool(
            rates, district_type, accommodation_key_for_staff(responsible_user_id)
        )
    except BadRequest:
        if batch:
            raise
        return False

    if not batch:
        batch = DailyVisitBatch.objects.create(
            responsible_user=responsible_user_id,
            visit_date=activity.planned_date,
            district_type=district_type,
            secondary_district_group=(
                _resolve_group(all_district_ids)
                if district_type == "secondary" and len(all_district_ids) > 1
                else None
            ),
        )
    effective_reason = (reason or "").strip()
    if effective_reason and effective_reason != batch.reason:
        batch.reason = effective_reason
        batch.save(update_fields=["reason", "updated_at"])

    activity.daily_visit_batch = batch
    activity.save(update_fields=["daily_visit_batch", "updated_at"])
    if not _price_when_the_save_ends(batch, catalogue, responsible_user_id):
        _recalculate_and_write_lines(batch, catalogue, responsible_user_id)
    return True


def remove_school(*, activity_id: str) -> dict:
    """Detach one Activity from its DailyVisitBatch and recompute the batch
    for the remaining schools. Used by cancel/defer/reschedule-away. Scope/
    permission checks are the caller's responsibility (the activity lifecycle
    functions already run _get_in_scope before calling this)."""
    from apps.activities.models import Activity

    with transaction.atomic():
        activity = Activity.objects.select_for_update().get(id=activity_id)
        batch = activity.daily_visit_batch
        if not batch:
            return {"batchId": None}
        if _is_locked(batch.responsible_user, batch.visit_date):
            raise BadRequest(
                "This date's visits have already left draft status. To remove this "
                "school, use Reschedule or Cancel on the individual visit instead."
            )
        activity.daily_visit_batch = None
        activity.save(update_fields=["daily_visit_batch", "updated_at"])
        catalogue = _catalogue_for_batch_date(batch.visit_date)
        _recalculate_and_write_lines(batch, catalogue, batch.responsible_user)
        return {"batchId": batch.id}


def reschedule_within_batch(
    *, activity, new_date: date, reason: str | None, principal
) -> None:
    """Move an already-persisted Activity (its scheduled_date/fy/quarter must
    already be saved by the caller — see activities.services.reschedule) into
    the new date's batch, subject to the same validation as fresh scheduling.
    Call this AFTER detaching the activity from its old batch."""
    school = activity.school
    if not school or not school.district_id:
        raise BadRequest(
            "This activity has no school/district on file — cannot batch-price it."
        )
    # REG-02 (restored by owner decision, 2026-09-22) — self-defending: do not
    # rely solely on the caller (activities.services.reschedule) having already
    # validated the date; no future call site may silently skip this gate.
    from apps.core.calendar_policy import (
        SchedulingPolicyService,
        resolve_scheduling_user,
    )

    staff_id = activity.responsible_staff_id or activity.monitored_by_staff_id
    avail = SchedulingPolicyService.check(
        resolve_scheduling_user(staff_id) if staff_id else None, new_date
    )
    if avail["status"] == "blocked":
        raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))

    from apps.activities.services import _funding_owner_id

    responsible_user_id = _funding_owner_id(activity, principal)
    # A district nobody has classified is not a reason to refuse the move
    # (owner, 2026-10-02: "lift that restrictions"). The visit was scheduled
    # there as a primary-district day (`attach_activity_to_batch`), and it
    # moves as one: the day's type is worked out below from the districts
    # that are classified secondary.

    with transaction.atomic():
        batch = (
            DailyVisitBatch.objects.select_for_update()
            .filter(responsible_user=responsible_user_id, visit_date=new_date)
            .first()
        )
        if batch and _is_locked(responsible_user_id, new_date):
            raise BadRequest(
                "This date's visits have already left draft status. Choose another date."
            )

        existing_activities = (
            list(
                batch.activities.filter(deleted_at__isnull=True)
                .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
                .select_related(*_MEMBER_DISTRICT_RELATIONS)
            )
            if batch
            else []
        )
        districts = [member_district(a) for a in existing_activities] + [
            school.district
        ]
        all_district_ids = {
            d.id
            for d in districts
            if d and district_type_for_staff(responsible_user_id, d) == "secondary"
        }
        incoming_type = "secondary" if all_district_ids else "primary"

        catalogue = _catalogue_for_batch_date(new_date)
        target = catalogue.required_school_visits_per_day if catalogue else 5
        total_after = len(existing_activities) + 1
        if total_after > target:
            raise BadRequest(
                f"You can only schedule {target} for this date, please choose another date."
            )

        effective_reason = (reason or "").strip() or (batch.reason if batch else None)
        if total_after < target and not effective_reason:
            raise ReasonRequiredError(
                f"You scheduled {total_after} school(s). The CD target is {target} schools "
                f"per day. This will increase cost per school. Reason required."
            )

        if not batch:
            batch = DailyVisitBatch.objects.create(
                responsible_user=responsible_user_id,
                visit_date=new_date,
                district_type=incoming_type,
                secondary_district_group=(
                    _resolve_group(all_district_ids)
                    if incoming_type == "secondary" and len(all_district_ids) > 1
                    else None
                ),
            )
        if effective_reason and effective_reason != batch.reason:
            batch.reason = effective_reason
            batch.save(update_fields=["reason", "updated_at"])

        activity.daily_visit_batch = batch
        activity.save(update_fields=["daily_visit_batch", "updated_at"])
        _recalculate_and_write_lines(batch, catalogue, responsible_user_id)


def _recalculate_and_write_lines(
    batch: DailyVisitBatch, catalogue, responsible_user_id: str
) -> None:
    """Recompute the batch's shared pool, split it across every active member
    activity, and re-price each one via the existing apply_to_activity writer
    (date derivation, catalogue provenance, advance-request sync — all reused
    unchanged), then resync the day's weekly fund request and monthly draft.

    The day before and the day after are re-priced with it when this day
    changed which of them is the day the traveller comes home."""
    from apps.budget.costing_service import rate_cards_held

    # Priced now, with whoever is on it: nothing is left for a save in hand
    # to price later (`each_day_priced_once`) unless another visit joins.
    days = _days_to_price.get()
    if days is not None:
        days.pop(batch.id, None)

    # Every member prices against the same published cards: read them once.
    with rate_cards_held():
        _write_day_lines(batch, catalogue, responsible_user_id)


#: A neighbouring day is re-priced only while it is still a plan: a day
#: already worked was slept and eaten as it was priced.
_PLANNED_DAY_STATUSES = ("planned", "scheduled", "rescheduled")


def _settle_neighbouring_days(batch: DailyVisitBatch, away) -> None:
    """Re-price the day before and the day after this one where it changed
    whether they are the day the traveller comes home.

    Friday is the return day of a Monday-to-Friday week until Saturday is
    planned; then Friday needs its night and dinner back. A neighbour whose
    week has left draft, whose money has moved or whose work is done is left
    as it was priced; `batch_needs_repricing` still reports it.
    """
    for neighbour in DailyVisitBatch.objects.filter(
        responsible_user=batch.responsible_user, visit_date__in=list(away)
    ):
        if priced_as_return_day(neighbour) == is_return_day(
            neighbour.responsible_user, neighbour.visit_date
        ):
            continue
        if _is_locked(neighbour.responsible_user, neighbour.visit_date):
            continue
        if (
            neighbour.activities.filter(deleted_at__isnull=True)
            .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
            .exclude(status__in=_PLANNED_DAY_STATUSES)
            .exists()
        ):
            continue
        try:
            with transaction.atomic():
                _write_day_lines(
                    neighbour, None, neighbour.responsible_user, settle_neighbours=False
                )
        except BadRequest:
            # Its money has moved (the cost writer's finance locks).
            continue


def _write_day_lines(
    batch: DailyVisitBatch,
    catalogue,
    responsible_user_id: str,
    *,
    settle_neighbours: bool = True,
) -> None:
    from apps.budget.costing import ActivityCost, CostLine
    from apps.budget.costing_service import (
        _rate_card,
        apply_to_activity,
    )
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activities
    from apps.fund_requests.weekly_service import trigger_generate_for_activities

    catalogue = catalogue or _catalogue_for_batch_date(batch.visit_date)
    rates, _settings_by_key = _rate_card(catalogue)

    # The districts come with the members: member_district() and the pricing
    # input read each one, and fetching them lazily cost two queries a member.
    activities = list(
        batch.activities.filter(deleted_at__isnull=True)
        .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .select_related(*_MEMBER_DISTRICT_RELATIONS)
        .order_by("id")
    )
    n = len(activities)
    # Where this day stood for its neighbours the last time it was priced.
    was_away = batch.district_type == "secondary" and bool(batch.school_count)
    district_types = {
        district_type_for_staff(responsible_user_id, member_district(member))
        or "primary"
        for member in activities
    }
    if district_types:
        batch.district_type = (
            "secondary" if "secondary" in district_types else "primary"
        )
    # The day the traveller comes home has no night and no dinner (owner,
    # 2026-10-05; apps.daily_visit_batches.return_day). Only a day in a
    # secondary district, now or as last priced, has neighbours to ask.
    is_away = batch.district_type == "secondary" and n > 0
    away = (
        away_on(
            batch.responsible_user,
            (batch.visit_date - ONE_DAY, batch.visit_date + ONE_DAY),
        )
        if was_away or is_away
        else set()
    )
    return_day = is_away and is_return_day(
        batch.responsible_user, batch.visit_date, away=away
    )
    # The night away is paid at the traveller's accommodation rate: the
    # CCEO's, or the one set for every other member of staff (owner,
    # 2026-10-05).
    pool = compute_daily_pool(
        rates,
        batch.district_type,
        accommodation_key_for_staff(responsible_user_id),
        return_day=return_day,
    )

    # Each member's own recipe, computed ONCE here because the day's pool
    # depends on it and the loop below needs it again.
    from apps.activities.services import _costing_input
    from apps.budget.costing import cost_for_activity
    from apps.budget.costing_service import _profiled_input, _with_linked_rates

    recipes: dict[str, tuple[dict, ActivityCost]] = {}
    for member in activities:
        member_input = {
            **_costing_input(member, {}),
            "plannedDate": batch.visit_date,
            "districtType": batch.district_type,
            "returnDay": return_day,
        }
        recipes[member.id] = (
            member_input,
            cost_for_activity(
                _with_linked_rates(_profiled_input(member_input), _settings_by_key),
                rates,
            ),
        )

    # The day always carries its lunch (session costing spec, 2026-09-26):
    # the participants' meals are each session's own line, the staff
    # member's lunch is the day's, and the two are priced apart. From
    # 2026-09-17 until then a day holding any catered session bought no
    # lunch at all — the owner's answer to a cluster training that had
    # fetched two meals for one lunchtime — which also took the lunch off an
    # ordinary school visit sharing that day.

    batch.cost_catalogue = catalogue
    batch.catalogue_version = catalogue.version if catalogue else None
    batch.rate_snapshot = pool
    batch.daily_pool_amount = sum(pool.values())
    batch.school_count = n
    batch.per_school_amount = (batch.daily_pool_amount // n) if n else 0
    batch.required_target_snapshot = (
        catalogue.required_school_visits_per_day if catalogue else 5
    )
    # §4/§5 Daily Field Cost analytics — the weighted School Visit Cost
    # Allocation and planned per-school figure. Never funding: the money is
    # the pool; this is the management lens over it.
    from .workload import actual_field_cost_per_school, allocate_mission_cost

    allocation = allocate_mission_cost(activities, batch.daily_pool_amount)
    batch.school_visit_allocation = allocation["school_visit_allocation"]
    batch.planned_field_cost_per_school = allocation["planned_field_cost_per_school"]
    batch.workload_snapshot = {
        "total_units": allocation["total_units"],
        "visit_units": allocation["visit_units"],
        "visit_count": allocation["visit_count"],
        "weights_used": allocation["weights_used"],
    }
    batch.save()
    batch.actual_field_cost_per_school = actual_field_cost_per_school(batch)
    batch.save(update_fields=["actual_field_cost_per_school", "updated_at"])

    # §9.1 — keep the transport company's obligation in step with the day.
    from apps.fund_requests.vendor_channel import ensure_transport_obligation

    ensure_transport_obligation(batch)

    if n == 0:
        _sync_route_batch(batch)  # day emptied → route twin cleans itself up
        if settle_neighbours and away:
            _settle_neighbouring_days(batch, away)
        return

    allocations = allocate_pool(pool, n)
    for index, (activity, alloc) in enumerate(zip(activities, allocations)):
        costing_input, own = recipes[activity.id]
        lines = [
            CostLine(
                label=KEY_LABELS.get(key, key.replace("_", " ").title()),
                key=key,
                unit=amount,
                qty=1,
                amount=amount,
                missing=False,
                allocation_count=n,
                allocation_index=index,
            )
            for key, amount in alloc.items()
        ]
        # Every member carries its activity-specific components ON TOP of its
        # per-diem pool share: a session's venue, facilitation and materials;
        # OneTest when the reason is OneTest, and any cost the Country
        # Director linked to its catalogue item (owner's catalogue,
        # 2026-09-06). A client, core or SSA visit by staff carries nothing
        # but its share (owner, 2026-09-12). Only the daily staff lines are shared;
        # the recipe's copies of those are replaced by the pool.
        lines.extend(line for line in own.lines if line.key not in KEY_LABELS)
        recipe_missing = [key for key in own.missing_items if key not in KEY_LABELS]
        cost = ActivityCost(
            amount=sum(line.amount for line in lines),
            lines=lines,
            cost_missing=bool(recipe_missing),
            missing_items=recipe_missing,
        )
        apply_to_activity(
            activity,
            costing_input,
            responsible_user_id=responsible_user_id,
            precomputed_cost=cost,
        )

    # The weekly request and the monthly draft follow the re-priced lines,
    # exactly as _apply_schedule_cost_snapshot does on the solo-pricing path.
    # Both are totals over the owner's week and month, which every member of
    # the day shares, so each is rebuilt once, after the last member is
    # priced. Rebuilt per member, the same two requests were regenerated once
    # for every school already on the day, and the fifth visit of a day took
    # twice as long to save as the first (2026-09-28).
    trigger_generate_for_activities(activities, responsible_user_id=responsible_user_id)
    sync_monthly_drafts_for_activities(activities)

    _sync_route_batch(batch)

    if settle_neighbours and away:
        _settle_neighbouring_days(batch, away)


def _sync_route_batch(batch: DailyVisitBatch) -> None:
    """Keep the route-feasibility twin (DailyVisitRouteBatch) in step with this
    costing batch. Advisory only — a route problem must never break pricing."""
    try:
        from apps.routes.engine import DailyVisitRouteBatchService

        DailyVisitRouteBatchService.rebuild_for(
            batch.responsible_user, batch.visit_date
        )
    except Exception:  # noqa: BLE001 — route intelligence is advisory
        pass


__all__ = [
    "schedule_visits",
    "attach_activity_to_batch",
    "each_day_priced_once",
    "remove_school",
    "reschedule_within_batch",
]
