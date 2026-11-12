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

Neither changes what any existing save does.
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
