from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from .models import WeeklyFundRequest, WeeklyFundRequestLine

logger = logging.getLogger("edify.weekly_fund_request")


def parse_date(d_str: str) -> date:
    if isinstance(d_str, (date, datetime)):
        return d_str.date() if isinstance(d_str, datetime) else d_str
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception as exc:
        raise BadRequest(f"Invalid date format: {d_str}") from exc


def generate_weekly_fund_request(responsible_user_id: str, week_start_date_str: str) -> WeeklyFundRequest | None:
    """Generate or update the WeeklyFundRequest for a user and week start date.

    Finds all scheduled, non-cancelled activities for that week owned by the user,
    aggregates their budget lines, and writes/updates the WeeklyFundRequest."""
    week_start = parse_date(week_start_date_str)
    # Ensure it's a Monday to keep the database constraint stable
    week_start = week_start - timedelta(days=week_start.weekday())
    week_end = week_start + timedelta(days=6)

    # 1. Find all scheduled activities for the selected week that are not cancelled
    lines = ActivityScheduleCostLine.objects.filter(
        responsible_user=responsible_user_id,
        planned_date__gte=week_start,
        planned_date__lte=week_end,
        activity__scheduled_date__isnull=False,
    ).exclude(
        activity__status="cancelled"
    ).select_related("activity")

    total_amount = sum(line.amount for line in lines)
    fy = get_operational_fy(week_start)

    with transaction.atomic():
        # Check if request already exists
        wfr = WeeklyFundRequest.objects.filter(responsible_user=responsible_user_id, week_start_date=week_start).first()
        if not lines.exists():
            # If no lines exist, and there is a draft request, we delete it
            if wfr and wfr.status == "pending_responsible_confirmation":
                wfr.lines.all().delete()
                wfr.delete()
            return None

        # If a request exists and is already confirmed/disbursed, we shouldn't reset its status
        # but we can update the total amount.
        if wfr:
            wfr.total_amount = total_amount
            # Only update status if it is still a draft/pending
            if wfr.status == "pending_responsible_confirmation":
                wfr.status = "pending_responsible_confirmation"
            wfr.save()
        else:
            wfr = WeeklyFundRequest.objects.create(
                fy=fy,
                week_start_date=week_start,
                week_end_date=week_end,
                responsible_user=responsible_user_id,
                total_amount=total_amount,
                status="pending_responsible_confirmation",
            )

        # Sync lines
        wfr.lines.all().delete()
        WeeklyFundRequestLine.objects.bulk_create([
            WeeklyFundRequestLine(
                weekly_fund_request=wfr,
                activity_budget_line=line,
                line_item_type=line.line_item_type or "other",
                description=line.label,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                total_cost=line.amount,
                currency=line.currency,
            )
            for line in lines
        ])

    return wfr


def trigger_generate_for_activity(activity: Activity, responsible_user_id: str | None = None) -> None:
    """Convenience helper to auto-trigger weekly request generation on activity schedule/reschedule.

    responsible_user_id must be the SAME identifier stamped onto the activity's
    cost lines (User.id). Activity.responsible_staff_id may hold a StaffProfile
    id instead, in which case the generator's line filter matches nothing and
    the weekly request silently never materialises — so callers that know the
    scheduling principal should pass it explicitly.
    """
    owner = responsible_user_id or activity.responsible_staff_id
    if activity.scheduled_date and owner and activity.status != "cancelled":
        planned_date = activity.scheduled_date.date()
        week_start = planned_date - timedelta(days=planned_date.weekday())
        generate_weekly_fund_request(owner, week_start.isoformat())


def list_weekly_requests(query: dict, principal) -> list[dict]:
    """Retrieve a list of weekly fund requests scoped by user permissions."""
    scope = resolve_user_scope(principal)
    qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")

    # If accountant or has payment permissions, they see everything ready for disbursement
    if query.get("status"):
        qs = qs.filter(status=query["status"])

    # Scope checks:
    if not scope.country_scope and scope.staff_ids:
        q = Q(responsible_user=principal.user_id)
        if scope.supervised_staff_ids:
            from apps.accounts.models import StaffProfile
            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids,
            ).values_list("user_id", flat=True)
            q |= Q(responsible_user__in=supervised_user_ids)
        qs = qs.filter(q)

    return [_serialize_request(r) for r in qs]


def get_weekly_request(request_id: str, principal) -> dict:
    """Retrieve details and itemized lines of a single WeeklyFundRequest."""
    wfr = WeeklyFundRequest.objects.filter(id=request_id).first()
    if not wfr:
        raise NotFoundError("Weekly fund request not found.")

    # Authorization check
    scope = resolve_user_scope(principal)
    if not scope.country_scope and wfr.responsible_user != principal.user_id:
        if scope.supervised_staff_ids:
            from apps.accounts.models import StaffProfile
            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids,
            ).values_list("user_id", flat=True)
            if wfr.responsible_user not in supervised_user_ids:
                raise Forbidden("You are not authorized to view this request.")
        else:
            raise Forbidden("You are not authorized to view this request.")

    return _serialize_request(wfr, include_lines=True)


def request_advance(request_id: str, principal) -> dict:
    """Confirm the weekly request -> status confirmed_for_advance (Accountant may disburse)."""
    with transaction.atomic():
        wfr = WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(principal, "country_scope", False):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status not in ("pending_responsible_confirmation", "not_requested"):
            raise BadRequest(f"Cannot request advance in status '{wfr.status}'.")

        wfr.status = "confirmed_for_advance"
        wfr.confirmed_at = timezone.now()
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

        # Also update linked AdvanceRequests status to keep them in sync
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "confirmed_for_advance"
                adv.advance_type = "advance"
                adv.confirmed_at = timezone.now()
                adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])

    return _serialize_request(wfr)


def self_funded(request_id: str, principal) -> dict:
    """Elect self-funded reimbursement -> status self_funded."""
    with transaction.atomic():
        wfr = WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(principal, "country_scope", False):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status in ("disbursed", "accounted"):
            raise BadRequest(f"Cannot change a disbursed request to self-funded.")

        wfr.status = "self_funded"
        wfr.confirmed_at = timezone.now()
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

        # Also update linked AdvanceRequests status
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "self_funded_pending_reimbursement"
                adv.advance_type = "self_funded"
                adv.confirmed_at = timezone.now()
                adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])

    return _serialize_request(wfr)


def not_requested(request_id: str, principal) -> dict:
    """Mark request as not requested yet."""
    with transaction.atomic():
        wfr = WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.responsible_user != principal.user_id and not getattr(principal, "country_scope", False):
            raise Forbidden("Only the owner can confirm this request.")
        if wfr.status in ("disbursed", "accounted"):
            raise BadRequest(f"Cannot cancel a disbursed request.")

        wfr.status = "not_requested"
        wfr.confirmed_at = timezone.now()
        wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

        # Also update linked AdvanceRequests status
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "not_requested"
                adv.advance_type = "not_requested"
                adv.confirmed_at = timezone.now()
                adv.save(update_fields=["status", "advance_type", "confirmed_at", "updated_at"])

    return _serialize_request(wfr)


def disburse(request_id: str, data: dict, principal) -> dict:
    """Accountant disburses a confirmed weekly request."""
    with transaction.atomic():
        wfr = WeeklyFundRequest.objects.select_for_update().filter(id=request_id).first()
        if not wfr:
            raise NotFoundError("Weekly fund request not found.")
        if wfr.status != "confirmed_for_advance":
            raise BadRequest("Only a confirmed request can be disbursed by the accountant.")

        disbursed_amount = int(data.get("amount", wfr.total_amount))
        now = timezone.now()

        wfr.status = "disbursed"
        wfr.disbursed_amount = disbursed_amount
        wfr.disbursed_at = now
        wfr.disbursed_by_user_id = principal.user_id
        wfr.disburse_method = data.get("method")
        wfr.disburse_reference = data.get("reference")
        wfr.save(update_fields=["status", "disbursed_amount", "disbursed_at", "disbursed_by_user_id", "disburse_method", "disburse_reference", "updated_at"])

        # Also update linked AdvanceRequests status to keep them in sync
        for line in wfr.lines.select_related("activity_budget_line"):
            adv = line.activity_budget_line.advance_requests.first()
            if adv:
                adv.status = "disbursed"
                adv.disbursed_amount = line.total_cost
                adv.disbursed_at = now
                adv.disbursed_by_user_id = principal.user_id
                adv.disburse_method = data.get("method")
                adv.disburse_reference = data.get("reference")
                adv.save(update_fields=["status", "disbursed_amount", "disbursed_at", "disbursed_by_user_id", "disburse_method", "disburse_reference", "updated_at"])

    return _serialize_request(wfr)


def accountant_weekly_queues() -> dict:
    """Return all weekly requests split by status for the accountant dashboard."""
    return {
        "pending_responsible_confirmation": _list_status("pending_responsible_confirmation"),
        "ready_for_disbursement": _list_status("confirmed_for_advance"),
        "self_funded": _list_status("self_funded"),
        "disbursed": _list_status("disbursed"),
        "not_requested": _list_status("not_requested"),
    }


def _list_status(status: str) -> list[dict]:
    qs = WeeklyFundRequest.objects.filter(status=status).order_by("-week_start_date")
    return [_serialize_request(r) for r in qs]


def _serialize_request(wfr: WeeklyFundRequest, include_lines: bool = False) -> dict:
    # Get the user name / details of the responsible owner
    from apps.accounts.models import StaffProfile
    profile = StaffProfile.objects.filter(user_id=wfr.responsible_user).select_related("user").first()
    owner_name = profile.user.name if (profile and profile.user) else wfr.responsible_user
    owner_initials = "".join([part[0].upper() for part in owner_name.split() if part])[:3]

    res = {
        "id": wfr.id,
        "fy": wfr.fy,
        "weekStartDate": wfr.week_start_date.isoformat(),
        "weekEndDate": wfr.week_end_date.isoformat(),
        "responsibleUser": wfr.responsible_user,
        "responsibleUserName": owner_name,
        "responsibleUserInitials": owner_initials,
        "responsibleRole": wfr.responsible_role,
        "totalAmount": wfr.total_amount,
        "status": wfr.status,
        "disbursedAmount": wfr.disbursed_amount,
        "disbursedAt": wfr.disbursed_at.isoformat() if wfr.disbursed_at else None,
        "confirmedAt": wfr.confirmed_at.isoformat() if wfr.confirmed_at else None,
    }

    if include_lines:
        res["lines"] = [
            {
                "id": line.id,
                "lineItemType": line.line_item_type,
                "description": line.description,
                "quantity": line.quantity,
                "unitCost": line.unit_cost,
                "totalCost": line.total_cost,
                "currency": line.currency,
                "activityId": line.activity_budget_line.activity_id,
            }
            for line in wfr.lines.select_related("activity_budget_line")
        ]

    return res
