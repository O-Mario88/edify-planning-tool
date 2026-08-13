"""
DailyVisitBatchService — the ONE path for scheduling staff-conducted school
visits. N=1 (a lone visit) and N>1 (bulk multi-school scheduling) both funnel
through `schedule_visits`, which is what makes "every school visit
creates/updates a DailyVisitBatch" true system-wide, not just for bulk
scheduling.

Validation order: unclassified district -> mixing primary/secondary -> locked
batch -> unapproved secondary grouping -> CD daily-target cap (hard) ->
CD daily-target floor (soft, needs a reason) -> create/attach -> recalculate.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Count, Q

from apps.core.exceptions import BadRequest, NotFoundError

from .exceptions import ReasonRequiredError
from .models import DailyVisitBatch
from .pricing import KEY_LABELS, allocate_pool, compute_daily_pool


def _catalogue_for_batch_date(visit_date: date):
    """Resolve the CD rate card effective for this batch's activity date.

    A batch has one visit date, so it must never borrow a catalogue from a
    different fiscal year merely because that catalogue has a higher version.
    """
    from apps.budget.costing_service import active_catalogue
    from apps.core.fy import get_operational_fy

    return active_catalogue(get_operational_fy(visit_date))


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
        live = (
            batch.activities.filter(deleted_at__isnull=True)
            .exclude(status="cancelled")
            .count()
        )
        if live != batch.school_count:
            with transaction.atomic():
                _recalculate_and_write_lines(batch, None, batch.responsible_user)
            repaired += 1
    return repaired


def _resolve_group(district_ids: set[str]):
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


def _assert_common_approved_group(district_ids: set[str]) -> None:
    if len(district_ids) <= 1:
        return
    if _resolve_group(district_ids) is None:
        raise BadRequest(
            "These secondary districts are not approved for same-day scheduling. "
            "Choose schools from one district or an approved nearby district group."
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

    new_types: dict[str, str] = {}
    for s in schools:
        dt = s.district.district_type if s.district_id else None
        if not dt:
            dname = s.district.name if s.district_id else "Unknown"
            raise BadRequest(
                f"District '{dname}' has not been classified as primary/secondary — "
                f"ask the CD/Admin to classify it first."
            )
        new_types[s.school_id] = dt

    if len(set(new_types.values())) > 1:
        raise BadRequest(
            "You cannot mix primary district and secondary district visits on the "
            "same day. Create a separate visit day."
        )
    incoming_district_type = next(iter(new_types.values()))

    with transaction.atomic():
        batch = (
            DailyVisitBatch.objects.select_for_update()
            .filter(responsible_user=responsible_user_id, visit_date=scheduled_date)
            .first()
        )

        if batch and batch.district_type != incoming_district_type:
            raise BadRequest(
                "You cannot mix primary district and secondary district visits on the "
                "same day. Create a separate visit day."
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
                .exclude(status="cancelled")
                .select_related("school")
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

        existing_district_ids = {
            a.school.district_id
            for a in existing_activities
            if a.school_id and a.school.district_id
        }
        new_district_ids = {s.district_id for s in schools if s.district_id}
        all_district_ids = existing_district_ids | new_district_ids

        if incoming_district_type == "secondary":
            _assert_common_approved_group(all_district_ids)

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

        return {"batchId": batch.id, "activities": new_activities}


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

    Returns True when the activity was pooled. Returns False (caller falls
    back to solo pricing) when pooling is impossible: unclassified district,
    a same-day batch of the other district type, an unapproved secondary
    district mix, a locked (post-draft) day, or missing pool rates.
    Must be called inside the caller's transaction.
    """
    school = activity.school
    if not school or not school.district_id:
        return False
    district_type = school.district.district_type
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
    if batch and batch.district_type != district_type:
        return False
    if _is_locked(responsible_user_id, activity.planned_date):
        return False

    existing_activities = (
        list(
            batch.activities.filter(deleted_at__isnull=True)
            .exclude(status="cancelled")
            .select_related("school")
        )
        if batch
        else []
    )
    all_district_ids = {
        a.school.district_id
        for a in existing_activities
        if a.school_id and a.school.district_id
    } | {school.district_id}
    if district_type == "secondary" and len(all_district_ids) > 1:
        if _resolve_group(all_district_ids) is None:
            return False

    catalogue = _catalogue_for_batch_date(activity.planned_date)
    from apps.budget.costing_service import _rate_card

    rates, _by_key = _rate_card(catalogue)
    try:
        compute_daily_pool(rates, district_type)
    except BadRequest:
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
    # REG-02 — self-defending: don't rely solely on the caller
    # (activities.services.reschedule) having already validated the date;
    # any future call site must not be able to silently skip this gate.
    from apps.core.calendar_policy import (
        SchedulingPolicyService,
        resolve_scheduling_user,
    )

    check_staff_id = activity.responsible_staff_id or activity.monitored_by_staff_id
    resp_user = resolve_scheduling_user(check_staff_id) if check_staff_id else None
    avail = SchedulingPolicyService.check(resp_user, new_date)
    if avail["status"] == "blocked":
        raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))

    school = activity.school
    if not school or not school.district_id:
        raise BadRequest(
            "This activity has no school/district on file — cannot batch-price it."
        )
    incoming_type = school.district.district_type
    if not incoming_type:
        raise BadRequest(
            f"District '{school.district.name}' has not been classified as primary/secondary "
            f"— ask the CD/Admin to classify it first."
        )

    responsible_user_id = principal.user_id
    with transaction.atomic():
        batch = (
            DailyVisitBatch.objects.select_for_update()
            .filter(responsible_user=responsible_user_id, visit_date=new_date)
            .first()
        )
        if batch and batch.district_type != incoming_type:
            raise BadRequest(
                "You cannot mix primary district and secondary district visits on the "
                "same day. Create a separate visit day."
            )
        if batch and _is_locked(responsible_user_id, new_date):
            raise BadRequest(
                "This date's visits have already left draft status. Choose another date."
            )

        existing_activities = (
            list(
                batch.activities.filter(deleted_at__isnull=True)
                .exclude(status="cancelled")
                .select_related("school")
            )
            if batch
            else []
        )
        existing_district_ids = {
            a.school.district_id
            for a in existing_activities
            if a.school_id and a.school.district_id
        }
        all_district_ids = existing_district_ids | {school.district_id}
        if incoming_type == "secondary":
            _assert_common_approved_group(all_district_ids)

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
    unchanged), then resync each activity's weekly fund request."""
    from apps.budget.costing import ActivityCost, CostLine
    from apps.budget.costing_service import (
        _rate_card,
        apply_to_activity,
    )
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
    from apps.fund_requests.weekly_service import trigger_generate_for_activity

    catalogue = catalogue or _catalogue_for_batch_date(batch.visit_date)
    rates, _settings_by_key = _rate_card(catalogue)
    pool = compute_daily_pool(rates, batch.district_type)

    activities = list(
        batch.activities.filter(deleted_at__isnull=True)
        .exclude(status="cancelled")
        .order_by("id")
    )
    n = len(activities)

    batch.cost_catalogue = catalogue
    batch.catalogue_version = catalogue.version if catalogue else None
    batch.rate_snapshot = pool
    batch.daily_pool_amount = sum(pool.values())
    batch.school_count = n
    batch.per_school_amount = (batch.daily_pool_amount // n) if n else 0
    batch.required_target_snapshot = (
        catalogue.required_school_visits_per_day if catalogue else 5
    )
    batch.save()

    if n == 0:
        _sync_route_batch(batch)  # day emptied → route twin cleans itself up
        return

    allocations = allocate_pool(pool, n)
    for activity, alloc in zip(activities, allocations):
        lines = [
            CostLine(
                label=KEY_LABELS.get(key, key.replace("_", " ").title()),
                key=key,
                unit=amount,
                qty=1,
                amount=amount,
                missing=False,
            )
            for key, amount in alloc.items()
        ]
        cost = ActivityCost(
            amount=sum(alloc.values()),
            lines=lines,
            cost_missing=False,
            missing_items=[],
        )
        apply_to_activity(
            activity,
            {"fy": activity.fy},
            responsible_user_id=responsible_user_id,
            precomputed_cost=cost,
        )
        trigger_generate_for_activity(activity, responsible_user_id=responsible_user_id)
        # The weekly request is only half the funding picture — the monthly
        # draft FundRequest must follow the re-priced lines too, exactly as
        # _apply_schedule_cost_snapshot does on the solo-pricing path.
        sync_monthly_drafts_for_activity(activity)

    _sync_route_batch(batch)


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
    "remove_school",
    "reschedule_within_batch",
]
