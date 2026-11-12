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
    check = preview(
        {
            "activityType": activity.activity_type,
            "costingProfile": catalogue.costing_profile if catalogue else None,
            "catalogueItemId": catalogue.id if catalogue else None,
            "deliveryType": "staff",
            "districtType": district_type,
            "accommodationKey": _accommodation_key_for(activity.responsible_staff_id),
            "teachersAttended": None,
            "leadersAttended": None,
            "otherParticipants": None,
            "expectedParticipants": None,
            "printingPages": 0,
            "photocopyPages": 0,
            "photocopyCopies": 0,
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


def _probe(fields: dict) -> dict:
    """Play the visit's join of its day as the existing save does, and say
    what the pricing would refuse. Always rolled back."""
    from apps.activities.models import Activity
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
