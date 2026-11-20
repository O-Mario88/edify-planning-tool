"""The pricing that follows a school visit Go saved (docs/migration/27).

Go makes the first save, scheduling a school visit; money stays with this
application until M12 (27.2, 27.8). Two server-to-server doors, beside the
sign-in security-events relay and behind the same internal key:

* ``visit-day-check`` asks, before Go opens its transaction, what the
  existing save would refuse for money's sake: the cost preview's blockers
  (``apps.activities.services._create``; stage "preview", asked before the
  save's transaction) and, for the day the visit joins,
  ``attach_activity_to_batch``'s own refusals and ``_assert_days_can_follow``
  (stage "day", met inside it), with their own words. It plays the visit as
  Go will insert it inside a transaction it rolls back, so it writes nothing.
  A cluster Group Training (docs/migration/38) is played the same way, its
  preview asked with the cluster's district and the session's head count and
  materials, as ``_create`` asks it. A Group Training delivered online
  (``apps.activities.online_training``; docs/migration/48) asks no preview and
  joins no day: the probe answers instead the cost revision the existing
  save writes for it inside its transaction (``_price_activity``'s online
  branch: ``apply_to_activity`` at UGX 0), worked out by the same
  ``calculate_dual`` and read only.
* ``costs-to-follow`` settles the costs-to-follow rows Go wrote, once Go's
  save has committed, with the existing ``costs_follow.settle``, and then
  says ``plan.changed`` for the visit on the realtime stream exactly as the
  existing save's settling thread does (``live.after_costs``).

* ``visit-move-check`` (docs/migration/29) asks the same of a move of such a
  visit, before Go opens its transaction: whether the move would take a
  sent, unpaid week back (``take_back_for_plan_change``; Go hands such a move
  on), whether the day it leaves has left draft (left frozen; handed on), and
  what ``_reprice_moved_activity``'s day refusals and ``_assert_days_can_follow``
  would refuse, with their own words. It plays the move on the activity
  inside a transaction it rolls back, so it writes nothing.

* ``visit-cancel-check`` (docs/migration/30) asks the same of a cancel of
  such a visit, before Go opens its transaction: whether a submitted or
  approved week holds the visit's lines (its owner is told after commit; Go
  hands such a cancel on), whether a milestone credit would be reversed on
  commit (handed on), whether the day it leaves has left draft (the visit is
  then kept on it, as ``_detach_from_daily_visit_batch`` keeps it), what the
  costs to follow would keep (the days, owner-weeks and owner-months), and
  what ``_assert_days_can_follow`` would refuse, with its own words. It plays
  the cancel on the activity inside a transaction it rolls back, so it writes
  nothing.

* ``visit-group-check`` (docs/migration/33) plays a group reschedule or a
  group cancel of the ticked activities exactly as ``group_actions`` makes it
  (each activity in the group's order, each meeting what the ones before it
  left: a day the first made, a visit the first moved; then the group's
  pricing asked once over every day, ``together``; and, when that refuses,
  the group again one activity at a time), inside a transaction it rolls
  back, and answers what became of each activity, in which way, and the
  group's own refusal. It writes nothing.

* ``activity-changed`` (docs/migration/31) says ``plan.changed`` for an
  activity Go saved when no costs follow it (an edit of a visit's goal or
  expected outcome), as the existing save's commit says it.

None changes what any existing save does.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.security_event_relay import internal_key_refusal
from apps.core.exceptions import BadRequest

logger = logging.getLogger(__name__)

#: The activity fields Go sends for the probe: exactly the columns its save
#: inserts (platform/deploy/db/activities_roles.sql), as model field names.
PROBE_FIELDS = (
    "activity_type",
    "fy",
    "quarter",
    "delivery_type",
    "executor_type",
    "status",
    "school_id",
    "responsible_staff_id",
    "scheduled_date",
    "planned_date",
    "planned_month",
    "planned_week",
    "purpose_type",
    "purpose_intervention",
    "focus_intervention",
    "activity_purpose_text",
    "expected_outcome",
    "ssa_collection_expected",
    "salesforce_activity_type",
    "catalogue_item_id",
    "catalogue_version",
    "activity_name_snapshot",
    "activity_type_snapshot",
    "delivery_method_snapshot",
    "evidence_profile_snapshot",
    "costing_profile_snapshot",
    "salesforce_record_type_snapshot",
    "planning_source",
    "activity_context_type",
    # A cluster Group Training (docs/migration/38): the cluster, the head
    # count the save derived and the materials it validated.
    "cluster_id",
    "expected_participants",
    "participants_per_school",
    "cluster_school_count_snapshot",
    "schools_invited",
    "teachers_per_school",
    "leaders_per_school",
    "other_per_school",
    "printing_pages",
    "photocopy_pages",
    "photocopy_copies",
    # A Group Training delivered online (docs/migration/48).
    "programme_delivery_mode",
)

#: The materials the cost preview reads, by the activity's own column.
_MATERIAL_COLUMNS = (
    ("printingPages", "printing_pages"),
    ("photocopyPages", "photocopy_pages"),
    ("photocopyCopies", "photocopy_copies"),
)

#: How many rows one settle may name: one save writes one.
MAX_ROWS = 20


class _Probe(Exception):
    """Raised to leave the probe's transaction with its answer."""

    def __init__(self, answer: dict) -> None:
        super().__init__("probe")
        self.answer = answer


def _body(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _cluster_preview_inputs(activity) -> dict:
    """What `_create` hands the cost preview for a cluster session with no
    school (2423–2461, 2716–2725): the district type where the cluster is,
    for the officer running it; the head count it derived (per school x
    schools invited); the materials it validated, a blank read as 0."""
    from apps.clusters.models import Cluster
    from apps.daily_visit_batches.districts import district_type_for_staff

    cluster = (
        Cluster.objects.select_related("district")
        .filter(pk=activity.cluster_id)
        .first()
    )
    return {
        "districtType": (
            district_type_for_staff(activity.responsible_staff_id, cluster.district)
            if cluster is not None and cluster.district_id
            else None
        ),
        "expectedParticipants": activity.expected_participants,
        **{key: getattr(activity, column) or 0 for key, column in _MATERIAL_COLUMNS},
    }


def _preview_refusal(activity, catalogue) -> str:
    """The cost preview's refusal, worded as `_create` words it (3137–3165)."""
    from apps.activities.services import _accommodation_key_for
    from apps.budget.costing_service import preview
    from apps.daily_visit_batches.districts import district_type_for_staff

    school = activity.school
    district_type = (
        district_type_for_staff(activity.responsible_staff_id, school.district)
        if school is not None and school.district_id
        else None
    )
    inputs = {
        "districtType": district_type,
        "expectedParticipants": None,
        "printingPages": 0,
        "photocopyPages": 0,
        "photocopyCopies": 0,
    }
    if school is None and activity.cluster_id:
        inputs = _cluster_preview_inputs(activity)
    check = preview(
        {
            "activityType": activity.activity_type,
            "costingProfile": catalogue.costing_profile if catalogue else None,
            "catalogueItemId": catalogue.id if catalogue else None,
            "deliveryType": "staff",
            "districtType": inputs["districtType"],
            "accommodationKey": _accommodation_key_for(activity.responsible_staff_id),
            "teachersAttended": None,
            "leadersAttended": None,
            "otherParticipants": None,
            "expectedParticipants": inputs["expectedParticipants"],
            "printingPages": inputs["printingPages"],
            "photocopyPages": inputs["photocopyPages"],
            "photocopyCopies": inputs["photocopyCopies"],
            "projectId": None,
            "fy": activity.fy,
        }
    )
    if not check["blockers"]:
        return ""
    if "expectedParticipants" in check["missingItems"]:
        return (
            "Enter the planned participant count in the activity drawer before "
            "scheduling."
        )
    return (
        "Cannot schedule — "
        + " · ".join(check["blockers"])
        + " Ask the Country Director to set the missing rate in the "
        "Cost Catalogue first."
    )


def _online_cost(activity) -> dict:
    """The cost revision `_price_activity` writes for an online Group
    Training (`apply_to_activity` with `precomputed_cost=ActivityCost()`):
    what `apply_to_activities` reads for the snapshot and its "cost
    calculated" audit entry, from the same input `_costing_input` builds
    with what `_create` holds in `data` (the head count it derived, the
    materials it validated with a blank as 0). Read only."""
    from apps.activities.services import _costing_input, _funding_owner_id
    from apps.budget.costing import ActivityCost
    from apps.budget.costing_service import (
        _profiled_input,
        _reference_as_written,
        _serialize_line,
        calculate_dual,
    )

    data = {
        "expectedParticipants": activity.expected_participants,
        **{key: getattr(activity, column) or 0 for key, column in _MATERIAL_COLUMNS},
    }
    input = _profiled_input(_costing_input(activity, data))
    dual = calculate_dual({**input, "fy": input.get("fy") or activity.fy})
    cost = ActivityCost()
    card = dual["operationalCard"]
    reference_card = dual["referenceCard"]
    reference = (
        _reference_as_written(cost, dual["reference"], reference_card)
        if dual["reference"] is not None
        else None
    )
    return {
        "operationalCardId": card.id if card else None,
        "operationalCardVersion": card.version if card else None,
        "referenceCardId": reference_card.id if reference_card else None,
        "referenceCardVersion": reference_card.version if reference_card else None,
        "referenceCost": (
            int(reference.amount)
            if reference is not None and not reference.cost_missing
            else None
        ),
        "referenceBreakdown": (
            [_serialize_line(line) for line in reference.lines]
            if reference is not None
            else []
        ),
        "operationalCost": int(cost.amount),
        "operationalBreakdown": [_serialize_line(line) for line in cost.lines],
        "calculationInputs": dual["inputs"],
        "warnings": dual["warnings"],
        "missingConfiguration": cost.missing_items,
        "costMissing": bool(cost.cost_missing or card is None),
        "calculatedBy": _funding_owner_id(activity) or activity.responsible_staff_id,
    }


def _probe(fields: dict) -> dict:
    """Play the visit's join of its day as the existing save does, and say
    what the pricing would refuse. Always rolled back."""
    from apps.activities.models import Activity
    from apps.activities.online_training import is_online_training
    from apps.activities.services import _funding_owner_id
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.budget.costing_service import rate_cards_held

    from . import services
    from .costs_follow import _assert_days_can_follow

    try:
        with rate_cards_held(), transaction.atomic():
            activity = Activity.objects.create(**fields)
            catalogue = ActivityCatalogueItem.objects.filter(
                id=activity.catalogue_item_id
            ).first()
            if is_online_training(activity):
                # Free and outside every day pool: no preview is asked of it
                # (`_create` 3129–3135) and no day is joined (`_price_activity`).
                raise _Probe(
                    {
                        "refusal": "",
                        "stage": "",
                        "pooled": False,
                        "online": _online_cost(activity),
                    }
                )
            refusal = _preview_refusal(activity, catalogue)
            if refusal:
                raise _Probe({"refusal": refusal, "stage": "preview", "pooled": False})
            responsible = _funding_owner_id(activity)
            pooled = (
                bool(responsible)
                and activity.delivery_type == "staff"
                and services.batch_poolable(activity)
            )
            if not pooled:
                raise _Probe({"refusal": "", "stage": "", "pooled": False})
            days: dict = {}
            token = services._days_to_price.set(days)
            try:
                joined = services.attach_activity_to_batch(
                    activity, responsible_user_id=responsible
                )
            except BadRequest as refused:
                raise _Probe(
                    {"refusal": str(refused), "stage": "day", "pooled": True}
                ) from refused
            finally:
                services._days_to_price.reset(token)
            if not joined:
                raise _Probe({"refusal": "", "stage": "", "pooled": False})
            try:
                _assert_days_can_follow(days, together=False)
            except BadRequest as refused:
                raise _Probe(
                    {"refusal": str(refused), "stage": "day", "pooled": True}
                ) from refused
            raise _Probe({"refusal": "", "stage": "", "pooled": True})
    except _Probe as answer:
        return answer.answer


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def visit_day_check(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    if body is None or not isinstance(body.get("activity"), dict):
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)
    raw = body["activity"]
    unknown = sorted(set(raw) - set(PROBE_FIELDS))
    if unknown:
        return JsonResponse({"ok": False, "reason": "unknown_fields"}, status=400)
    fields = dict(raw)
    try:
        if fields.get("planned_date"):
            fields["planned_date"] = date.fromisoformat(str(fields["planned_date"]))
        if fields.get("scheduled_date"):
            from apps.activities.services import _parse_date

            fields["scheduled_date"] = _parse_date(str(fields["scheduled_date"]))
    except (ValueError, BadRequest):
        return JsonResponse({"ok": False, "reason": "bad_date"}, status=400)
    answer = _probe(fields)
    return JsonResponse({"ok": True, **answer}, status=200)


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def costs_to_follow(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    rows = body.get("rows") if body is not None else None
    if (
        not isinstance(rows, list)
        or not 0 < len(rows) <= MAX_ROWS
        or not all(isinstance(row, int) and row > 0 for row in rows)
    ):
        return JsonResponse({"ok": False, "reason": "bad_rows"}, status=400)
    from apps.activities import live
    from apps.activities.models import Activity

    from .costs_follow import settle

    done = settle(ids=rows)
    activity = Activity.objects.filter(id=str(body.get("activityId") or "")).first()
    if activity is not None:
        try:
            with live.after_costs() as named:
                named.extend(rows)
                live.announce_activity(activity)
        except Exception:  # noqa: BLE001 — a page left stale, no more
            logger.warning("Costs to follow: announcing failed", exc_info=True)
    return JsonResponse({"ok": True, "settled": done}, status=200)


#: The longest reason a move carries (the drawer's textarea, then the
#: schedule trail keeps 512 of it).
MAX_REASON = 2000


def _move_probe(activity_id: str, new_day: date, reason: str) -> dict:
    """Play the move's money as ``services.reschedule`` does for a visit of
    the first save's kind (5306–5393, then ``costs_follow._hand_over``), and
    say what it would meet. Always rolled back."""
    from apps.activities.models import Activity
    from apps.activities.services import (
        _parse_date,
        _reprice_moved_activity,
        _schedule_period,
    )
    from apps.budget.costing_service import rate_cards_held
    from apps.core.clock import local_day
    from apps.core.fy import get_operational_fy, get_quarter_for_date
    from apps.fund_requests.follow import fund_requests_kept
    from apps.fund_requests.plan_changes import planner_change, will_take_back

    from . import services
    from .costs_follow import _assert_days_can_follow
    from .pricing import DAILY_BATCH_ELIGIBLE_TYPES

    answer = {
        "refusal": "",
        "stage": "",
        "takesBack": False,
        "leftFrozen": False,
        "pooled": True,
    }
    try:
        with rate_cards_held(), transaction.atomic():
            activity = (
                Activity.objects.select_for_update().filter(id=activity_id).first()
            )
            if activity is None:
                raise _Probe({**answer, "pooled": False})
            old_day = activity.planned_date or (
                activity.scheduled_date and local_day(activity.scheduled_date)
            )
            if will_take_back(activity, days=(old_day, new_day)):
                raise _Probe({**answer, "takesBack": True})
            batch = activity.daily_visit_batch
            if batch is not None and services._is_locked(
                batch.responsible_user, batch.visit_date
            ):
                raise _Probe({**answer, "leftFrozen": True})
            if (
                activity.activity_type not in DAILY_BATCH_ELIGIBLE_TYPES
                or activity.delivery_type != "staff"
                or not activity.school_id
            ):
                raise _Probe({**answer, "pooled": False})
            data = {
                "scheduledDate": new_day.isoformat(),
                "reason": reason,
                "plannedMonth": new_day.month,
                "plannedWeek": min(5, (new_day.day - 1) // 7 + 1),
            }
            new_date = _parse_date(data["scheduledDate"])
            planned_date, planned_month, planned_week = _schedule_period(new_date, data)
            activity.scheduled_date = new_date
            activity.fy = get_operational_fy(new_date)
            activity.quarter = get_quarter_for_date(new_date)
            activity.planned_date = planned_date
            activity.planned_month = planned_month
            activity.planned_week = planned_week
            activity.status = "rescheduled"
            activity.last_reason = reason
            activity.save(
                update_fields=[
                    "scheduled_date",
                    "fy",
                    "quarter",
                    "planned_date",
                    "planned_month",
                    "planned_week",
                    "status",
                    "last_reason",
                    "updated_at",
                ]
            )
            days: dict = {}
            with planner_change(None, activity), fund_requests_kept():
                tokens = (
                    services._days_to_price.set(days),
                    services._after_pricing.set([]),
                )
                try:
                    _reprice_moved_activity(activity, data, None)
                except BadRequest as refused:
                    raise _Probe(
                        {**answer, "refusal": str(refused), "stage": "day"}
                    ) from refused
                finally:
                    services._after_pricing.reset(tokens[1])
                    services._days_to_price.reset(tokens[0])
            try:
                _assert_days_can_follow(days, together=False)
            except BadRequest as refused:
                raise _Probe(
                    {**answer, "refusal": str(refused), "stage": "follow"}
                ) from refused
            raise _Probe(answer)
    except _Probe as probed:
        return probed.answer


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def visit_move_check(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    if body is None:
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)
    activity_id = body.get("activityId")
    reason = body.get("reason", "")
    if (
        not isinstance(activity_id, str)
        or not 0 < len(activity_id) <= 30
        or not isinstance(reason, str)
        or len(reason) > MAX_REASON
    ):
        return JsonResponse({"ok": False, "reason": "bad_fields"}, status=400)
    try:
        new_day = date.fromisoformat(str(body.get("scheduledDate", "")))
    except ValueError:
        return JsonResponse({"ok": False, "reason": "bad_date"}, status=400)
    return JsonResponse({"ok": True, **_move_probe(activity_id, new_day, reason)})


#: The longest reason a cancel stores (activity.last_reason).
MAX_CANCEL_REASON = 512


def _cancel_probe(activity_id: str, reason: str) -> dict:
    """Play the cancel's money as ``services._cancel_or_defer`` does for a
    visit of the first save's kind (6600–6660, then ``costs_follow._hand_over``),
    and say what it would meet and keep. Always rolled back."""
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.activities.services import _detach_from_daily_visit_batch
    from apps.budget.costing_service import rate_cards_held
    from apps.fund_requests.follow import fund_requests_kept
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
    from apps.fund_requests.weekly_service import (
        REBUILDABLE_WEEKLY_STATUSES,
        sync_weekly_requests_for_activity,
    )
    from apps.hr.models import MilestoneProgressCredit

    from . import services
    from .costs_follow import _assert_days_can_follow, _Kept

    answer = {
        "found": True,
        "refusal": "",
        "frozenWeeks": False,
        "credited": False,
        "leftFrozen": False,
        "pricedHere": False,
        "days": [],
        "weeks": [],
        "months": [],
    }
    try:
        with rate_cards_held(), transaction.atomic():
            activity = (
                Activity.objects.select_for_update().filter(id=activity_id).first()
            )
            if activity is None:
                raise _Probe({**answer, "found": False})
            prior_buckets = list(
                ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
                    "responsible_user", "fiscal_year", "month", "week_start_date"
                )
            )
            frozen = (
                WeeklyFundRequest.objects.filter(
                    lines__activity_budget_line__activity=activity
                )
                .exclude(status__in=REBUILDABLE_WEEKLY_STATUSES)
                .exclude(status__in=("disbursed", "accounted"))
                .exists()
            )
            credited = MilestoneProgressCredit.objects.filter(
                activity=activity, reversed_at__isnull=True
            ).exists()
            batch = activity.daily_visit_batch
            left_frozen = batch is not None and services._is_locked(
                batch.responsible_user, batch.visit_date
            )
            activity.status = "cancelled"
            activity.last_reason = reason
            activity.save(update_fields=["status", "last_reason", "updated_at"])
            kept = _Kept(None)
            days: dict = {}
            afterwards: list = []
            with fund_requests_kept() as waiting:
                tokens = (
                    services._kept_for_later.set(kept),
                    services._days_to_price.set(days),
                    services._after_pricing.set(afterwards),
                )
                try:
                    _detach_from_daily_visit_batch(activity)
                    sync_weekly_requests_for_activity(
                        activity, prior_buckets=prior_buckets
                    )
                    sync_monthly_drafts_for_activity(
                        activity, prior_buckets=prior_buckets
                    )
                finally:
                    services._after_pricing.reset(tokens[2])
                    services._days_to_price.reset(tokens[1])
                    services._kept_for_later.reset(tokens[0])
            refusal = ""
            try:
                _assert_days_can_follow(days, together=kept.together)
            except BadRequest as refused:
                refusal = str(refused)
            raise _Probe(
                {
                    **answer,
                    "refusal": refusal,
                    "frozenWeeks": frozen,
                    "credited": credited,
                    "leftFrozen": left_frozen,
                    "pricedHere": kept.priced_here or bool(afterwards),
                    "days": [[day, owner] for day, (_c, owner) in days.items()],
                    "weeks": [
                        [owner, week.isoformat()] for owner, week in waiting["weeks"]
                    ],
                    "months": [list(period) for period in waiting["months"]],
                }
            )
    except _Probe as probed:
        return probed.answer


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def visit_cancel_check(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    if body is None:
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)
    activity_id = body.get("activityId")
    reason = body.get("reason", "")
    if (
        not isinstance(activity_id, str)
        or not 0 < len(activity_id) <= 30
        or not isinstance(reason, str)
        or len(reason) > MAX_CANCEL_REASON
    ):
        return JsonResponse({"ok": False, "reason": "bad_fields"}, status=400)
    return JsonResponse({"ok": True, **_cancel_probe(activity_id, reason)})


#: The two group actions the group check plays.
GROUP_KINDS = ("reschedule", "cancel")


def _group_picks(kind: str, ids: list, raw_day: str, reason: str, principal):
    """``group_actions.reschedule`` / ``cancel`` up to ``_apply``: the group's
    own refusals, the selection, and for a move the picks already on the day;
    with the act, skip and change they hand to ``_apply``."""
    from apps.activities import group_actions, services

    reason = str(reason or "").strip()
    if kind == "cancel":
        if not reason:
            raise BadRequest("Give the reason these activities are being cancelled.")

        def call_off(activity):
            services.cancel(activity.id, {"reason": reason}, principal)

        picks = group_actions.selection(ids, principal, action=group_actions.CANCEL)
        return picks, call_off, None, None
    try:
        day = date.fromisoformat(str(raw_day or "").strip())
    except ValueError:
        raise BadRequest("Choose the date these activities move to.") from None
    if not reason:
        raise BadRequest("Give the reason these activities are moving.")
    payload = {
        "scheduledDate": day.isoformat(),
        "reason": reason,
        "plannedMonth": day.month,
        "plannedWeek": min(5, (day.day - 1) // 7 + 1),
    }

    def move(activity):
        services.reschedule(activity.id, payload, principal)

    picks = group_actions.selection(ids, principal, action=group_actions.RESCHEDULE)
    by_id = {p.id: p for p in picks}
    for pick in picks:
        if not pick.refusal and all(by_id[i].day == day for i in pick.unit):
            pick.refusal = "Already on this date."

    def one_change(count: int):
        from apps.fund_requests.plan_changes import planner_change

        return planner_change(principal, what=f"{count} activities")

    return picks, move, (lambda pick: pick.day == day), one_change


def _group_probe(kind: str, ids: list, raw_day: str, reason: str, principal) -> dict:
    """Play the group as ``group_actions._apply`` plays it and say what it
    did: each pick done or left with its words, ``together`` when the group
    was changed in one transaction and priced once, ``groupRefusal`` when
    that pricing refused and the group was changed one activity at a time.
    Always rolled back."""
    from django.conf import settings

    from apps.activities import group_actions
    from apps.core.htmx_errors import error_message

    answer = {"refusal": "", "together": False, "groupRefusal": "", "picks": []}
    try:
        with transaction.atomic():
            try:
                picks, act, skip, within = _group_picks(
                    kind, ids, raw_day, reason, principal
                )
            except BadRequest as refused:
                raise _Probe({**answer, "refusal": error_message(refused)}) from refused
            changing = len(
                {
                    p.unit
                    for p in picks
                    if not any(m.refusal for m in group_actions._unit(p, picks))
                }
            )
            outcome = None
            together = changing > 1 and getattr(
                settings, "PRICE_A_DAY_ONCE_PER_SAVE", True
            )
            if together:
                said = {p.id: p.refusal for p in picks}
                try:
                    outcome = group_actions._together(
                        picks, act=act, skip=skip, within=within, count=changing
                    )
                except Exception as exc:  # noqa: BLE001 — as _apply answers for it
                    answer["groupRefusal"] = error_message(exc)
                    together = False
                    for pick in picks:
                        pick.refusal = said[pick.id]
            if outcome is None:
                outcome = group_actions._one_at_a_time(picks, act=act, skip=skip)
            done = {p.id for p in outcome.done}
            raise _Probe(
                {
                    **answer,
                    "together": together,
                    "picks": [
                        {
                            "id": p.id,
                            "done": p.id in done,
                            "refusal": "" if p.id in done else p.refusal,
                        }
                        for p in picks
                    ],
                }
            )
    except _Probe as probed:
        return probed.answer


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def visit_group_check(request):
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    if body is None:
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)
    kind, ids = body.get("kind"), body.get("activityIds")
    user_id, role = body.get("userId"), body.get("role")
    raw_day, reason = body.get("scheduledDate", ""), body.get("reason", "")
    if (
        kind not in GROUP_KINDS
        or not isinstance(ids, list)
        or not 0 < len(ids) <= MAX_GROUP
        or not all(isinstance(i, str) and 0 < len(i) <= 30 for i in ids)
        or not isinstance(user_id, str)
        or not 0 < len(user_id) <= 30
        or not isinstance(role, str)
        or not isinstance(raw_day, str)
        or len(raw_day) > 10
        or not isinstance(reason, str)
        or len(reason) > MAX_REASON
    ):
        return JsonResponse({"ok": False, "reason": "bad_fields"}, status=400)
    from apps.accounts.models import User

    principal = User.objects.filter(id=user_id, is_active=True).first()
    if principal is None or role not in (principal.roles or []):
        return JsonResponse({"ok": False, "reason": "bad_principal"}, status=400)
    # The role the person is working in, as their request carries it.
    principal.active_role = role
    return JsonResponse(
        {"ok": True, **_group_probe(kind, ids, raw_day, reason, principal)}
    )


#: The most activities a group takes (group_actions.MAX_SELECTION).
MAX_GROUP = 100


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def activity_changed(request):
    """Say ``plan.changed`` for an activity Go saved when no costs follow it
    (docs/migration/31: an edit of a visit's words), exactly as the existing
    save's own commit says it (``live`` on the activity's post_save)."""
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    activity_id = body.get("activityId") if body is not None else None
    if not isinstance(activity_id, str) or not 0 < len(activity_id) <= 30:
        return JsonResponse({"ok": False, "reason": "bad_fields"}, status=400)
    from apps.activities import live
    from apps.activities.models import Activity

    activity = Activity.objects.filter(id=activity_id).first()
    if activity is not None:
        try:
            live.announce_activity(activity)
        except Exception:  # noqa: BLE001 — a page left stale, no more
            logger.warning("Activity changed: announcing failed", exc_info=True)
    return JsonResponse({"ok": True}, status=200)


#: The status a completion Go made hands the work in at (docs/migration/183):
#: a CCEO's own school visit, routed to their Programme Lead.
HANDED_IN_STATUS = "submitted_to_pl"


@csrf_exempt  # A server's key, never a browser's session.
@require_POST
def visit_completed(request):
    """What follows a school visit's completion Go made (docs/migration/183),
    once Go's save has committed, exactly as the existing completion follows
    its own: ``services._handed_in`` (the reviewer told, or a lead's own work
    approved; the day it moves to, which Go only completes when it is the
    planned day), the overdue reminder closed, and ``plan.changed`` said. The
    notices are the existing application's until M11; none of it can undo the
    completion. Asked for a visit in any other state, it does nothing."""
    refusal = internal_key_refusal(request)
    if refusal is not None:
        return refusal
    body = _body(request)
    if body is None:
        return JsonResponse({"ok": False, "reason": "not_an_object"}, status=400)
    activity_id, user_id, role = (
        body.get("activityId"),
        body.get("userId"),
        body.get("role"),
    )
    if not all(
        isinstance(value, str) and 0 < len(value) <= 30
        for value in (activity_id, user_id)
    ) or not isinstance(role, str):
        return JsonResponse({"ok": False, "reason": "bad_fields"}, status=400)
    from apps.accounts.models import User

    principal = User.objects.filter(id=user_id, is_active=True).first()
    if principal is None or role not in (principal.roles or []):
        return JsonResponse({"ok": False, "reason": "bad_principal"}, status=400)
    # The role the person is working in, as their request carries it.
    principal.active_role = role
    from apps.activities import live, services
    from apps.activities.models import Activity

    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if activity is None or activity.status != HANDED_IN_STATUS:
        return JsonResponse({"ok": True, "handedIn": False}, status=200)
    services._handed_in(activity, HANDED_IN_STATUS, principal)
    services._resolve_overdue_reminder(activity)
    try:
        live.announce_activity(activity)
    except Exception:  # noqa: BLE001 — a page left stale, no more
        logger.warning("Visit completed: announcing failed", exc_info=True)
    return JsonResponse({"ok": True, "handedIn": True}, status=200)
