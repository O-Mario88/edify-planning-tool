"""Fund-requests service — submit/approve/disburse + accountability."""
from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.budget.costing import resolve_activity_cost
from apps.budget.models import CostSetting
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

from .models import FundRequest, FundRequestItem, FundRequestPeriod, FundRequestStatus


def submit(data: dict, principal) -> dict:
    """Submit a fund request.

    The fund request is generated FROM the persisted activity budget lines
    (ActivityScheduleCostLine) — they are the authoritative cost snapshot taken
    at schedule time, so the request total is provably the sum of its line items.
    Blocked if any in-period activity is cost-missing or has no budget lines.
    The cost lines are prefetched (one query) instead of queried per activity."""
    fy = data.get("fy") or get_operational_fy()
    period = data.get("period", "monthly")
    period_key = data.get("periodKey") or _period_key(fy, period, data)
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    qs = _filter_period(qs, period, period_key, data).prefetch_related("schedule_cost_lines")

    activities = list(qs)
    # Cost blocker: any in-period activity flagged cost-missing, or with no lines.
    bad = [a for a in activities if a.cost_missing or not list(a.schedule_cost_lines.all())]
    if bad:
        raise BadRequest(
            f"Cannot submit — {len(bad)} activity(ies) are missing a cost rate or budget lines."
        )

    request_items: list[tuple[Activity, object]] = []
    total = 0
    for a in activities:
        for line in a.schedule_cost_lines.all():
            request_items.append((a, line))
            total += line.amount

    lens = "country" if scope.country_scope else ("team" if scope.can_view_team else "own")
    with transaction.atomic():
        fr, created = FundRequest.objects.update_or_create(
            submitted_by_user_id=principal.user_id, period=period, period_key=period_key,
            defaults={
                "fy": fy, "scope": lens, "submitted_by_role": principal.active_role,
                "total_amount": total, "activity_count": len(activities),
                "status": FundRequestStatus.SUBMITTED,
            },
        )
        fr.items.all().delete()
        FundRequestItem.objects.bulk_create([
            FundRequestItem(
                fund_request=fr,
                activity_id=activity.id,
                activity_schedule_cost_line_id=line.id,
                amount=line.amount,
                period=period,
                period_key=period_key,
            )
            for activity, line in request_items
        ])
    return _serialize(fr)


def _period_key(fy: str, period: str, data: dict) -> str:
    if period == FundRequestPeriod.WEEKLY:
        week = data.get("week")
        month = data.get("month")
        if week and month:
            return f"{fy}-M{int(month)}-W{int(week)}"
        if week:
            return f"{fy}-W{int(week)}"
        return fy
    if period == FundRequestPeriod.MONTHLY:
        month = data.get("month")
        return f"{fy}-M{int(month)}" if month else fy
    if period == FundRequestPeriod.QUARTERLY and data.get("quarter"):
        return f"{fy}-{data['quarter']}"
    return fy


def _filter_period(qs, period: str, period_key: str, data: dict):
    if period == FundRequestPeriod.WEEKLY:
        # A weekly fund request is scoped to a specific week (and optionally a
        # month). Previously weekly had no filter — it silently matched the whole
        # FY. Now it narrows by planned_week (+ planned_month when given).
        week = data.get("week")
        if not week:
            match = re.search(r"-W(\d+)$", period_key or "")
            week = int(match.group(1)) if match else None
        if week:
            qs = qs.filter(planned_week=int(week))
        month = data.get("month")
        if month:
            qs = qs.filter(planned_month=int(month))
    elif period == FundRequestPeriod.MONTHLY:
        month = data.get("month")
        if not month:
            match = re.search(r"-M(\d+)$", period_key or "")
            month = int(match.group(1)) if match else None
        if month:
            qs = qs.filter(planned_month=int(month))
    elif period == FundRequestPeriod.QUARTERLY:
        quarter = data.get("quarter")
        if not quarter:
            match = re.search(r"-(Q[1-4])$", period_key or "")
            quarter = match.group(1) if match else None
        if quarter:
            qs = qs.filter(quarter=quarter)
    return qs


def list_requests(query: dict, principal) -> list[dict]:
    scope = resolve_user_scope(principal)
    qs = FundRequest.objects.all().order_by("-created_at")
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    if not scope.country_scope and scope.staff_ids:
        q = Q(submitted_by_user_id=principal.user_id)
        if scope.supervised_staff_ids:
            from apps.accounts.models import StaffProfile

            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids,
            ).values_list("user_id", flat=True)
            q |= Q(submitted_by_user_id__in=supervised_user_ids)
        qs = qs.filter(q)
    return [_serialize(fr) for fr in qs]


def get_one(request_id: str, principal) -> dict:
    fr = FundRequest.objects.filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    return _serialize(fr)


def _review(request_id: str, new_status: str, data: dict, principal) -> dict:
    fr = FundRequest.objects.filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    fr.status = new_status
    fr.reviewed_by_user_id = principal.user_id
    fr.reviewed_at = timezone.now()
    fr.review_note = data.get("note")
    fr.save(update_fields=["status", "reviewed_by_user_id", "reviewed_at", "review_note"])
    return _serialize(fr)


def approve(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.APPROVED, data, principal)


def return_request(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.RETURNED, data, principal)


def reject(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.REJECTED, data, principal)


def disburse(request_id: str, data: dict, principal) -> dict:
    """Accountant clears an APPROVED request -> disbursed."""
    fr = FundRequest.objects.filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    if fr.status not in (FundRequestStatus.APPROVED, FundRequestStatus.SENT_TO_ACCOUNTANT):
        raise BadRequest("Only an approved request can be disbursed.")
    fr.status = FundRequestStatus.DISBURSED
    fr.disbursed_amount = data.get("amount", fr.total_amount)
    fr.disbursed_at = timezone.now()
    fr.disbursed_by_user_id = principal.user_id
    fr.disburse_method = data.get("method")
    fr.disburse_reference = data.get("reference")
    fr.save(update_fields=["status", "disbursed_amount", "disbursed_at", "disbursed_by_user_id", "disburse_method", "disburse_reference"])
    return _serialize(fr)


def submit_accountability(request_id: str, data: dict, principal) -> dict:
    fr = FundRequest.objects.filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    fr.accounted_amount = data.get("amountSpent")
    fr.returned_amount = data.get("amountReturned")
    fr.accountability_netsuite_id = data.get("netsuiteId")
    fr.accountability_status = "submitted"
    fr.accountability_submitted_at = timezone.now()
    fr.save(update_fields=["accounted_amount", "returned_amount", "accountability_netsuite_id", "accountability_status", "accountability_submitted_at"])
    return _serialize(fr)


def review_accountability(request_id: str, decision: str, data: dict, principal) -> dict:
    fr = FundRequest.objects.filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    if decision == "approve":
        fr.accountability_status = "approved"
        fr.status = FundRequestStatus.CLOSED
    else:
        fr.accountability_status = "returned"
        fr.status = FundRequestStatus.RETURNED_BY_ACCOUNTANT
    fr.accountability_reviewed_at = timezone.now()
    fr.reviewed_by_user_id = principal.user_id
    fr.save(update_fields=["accountability_status", "status", "accountability_reviewed_at", "reviewed_by_user_id"])
    return _serialize(fr)


def regenerate(period: str, principal) -> dict:
    """Idempotent manual regeneration (weekly/monthly)."""
    data = {"period": period, "fy": get_operational_fy()}
    return submit(data, principal)


def _to_costable(a: Activity) -> dict:
    return {
        "activityType": a.activity_type, "deliveryType": a.delivery_type,
        "teachersAttended": a.teachers_attended, "leadersAttended": a.leaders_attended,
        "otherParticipants": a.other_participants, "projectId": a.project_id,
        "estCostCents": a.est_cost_cents, "costMissing": a.cost_missing,
    }


def _snapshot_lines(a: Activity) -> list[dict]:
    return [
        {
            "label": line.label,
            "costSettingKey": line.cost_setting_key,
            "unitCost": line.unit_cost,
            "quantity": line.quantity,
            "amount": line.amount,
            "costSettingVersion": line.cost_setting_version,
        }
        for line in a.schedule_cost_lines.all()
    ]


def _serialize(fr: FundRequest) -> dict:
    return {
        "id": fr.id,
        "fy": fr.fy,
        "period": fr.period,
        "periodKey": fr.period_key,
        "scope": fr.scope,
        "totalAmount": fr.total_amount,
        "activityCount": fr.activity_count,
        "status": fr.status,
        "reviewedByUserId": fr.reviewed_by_user_id,
        "reviewedAt": fr.reviewed_at.isoformat() if fr.reviewed_at else None,
        "reviewNote": fr.review_note,
        "disbursedAmount": fr.disbursed_amount,
        "disbursedAt": fr.disbursed_at.isoformat() if fr.disbursed_at else None,
        "accountabilityStatus": fr.accountability_status,
    }
