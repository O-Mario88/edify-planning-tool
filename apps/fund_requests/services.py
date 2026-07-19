"""Fund-requests service — submit/approve/disburse + accountability."""

from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, NotFoundError
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
    qs = _filter_period(qs, period, period_key, data).prefetch_related(
        "schedule_cost_lines"
    )

    activities = list(qs)
    # Cost blocker: any in-period activity flagged cost-missing, or with no lines.
    bad = [
        a for a in activities if a.cost_missing or not list(a.schedule_cost_lines.all())
    ]
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

    lens = (
        "country" if scope.country_scope else ("team" if scope.can_view_team else "own")
    )
    with transaction.atomic():
        # A re-submit must never silently reset a request that has moved past
        # the pending stage — rewriting an APPROVED or DISBURSED request back
        # to SUBMITTED (and rebuilding its items/total) would erase an
        # approval or, worse, a record of money already released. The weekly
        # path guards this; the period path did not.
        existing = (
            FundRequest.objects.select_for_update()
            .filter(
                submitted_by_user_id=principal.user_id,
                period=period,
                period_key=period_key,
                scope=lens,
            )
            .first()
        )
        resubmittable = {
            FundRequestStatus.DRAFT,
            FundRequestStatus.SUBMITTED,
            FundRequestStatus.RETURNED,
            FundRequestStatus.REJECTED,
            FundRequestStatus.RETURNED_BY_PL,
            FundRequestStatus.RETURNED_BY_CD,
            FundRequestStatus.RETURNED_BY_RVP,
            FundRequestStatus.RETURNED_BY_ACCOUNTANT,
        }
        if existing and existing.status not in resubmittable:
            raise BadRequest(
                f"A {period} request for {period_key} already exists in status "
                f"'{existing.status}' — it can no longer be re-submitted. Ask "
                "the approver to return it first if changes are needed."
            )
        fr, created = FundRequest.objects.update_or_create(
            submitted_by_user_id=principal.user_id,
            period=period,
            period_key=period_key,
            scope=lens,
            defaults={
                "fy": fy,
                "submitted_by_role": principal.active_role,
                "total_amount": total,
                "activity_count": len(activities),
                "status": FundRequestStatus.SUBMITTED,
            },
        )
        fr.items.all().delete()
        FundRequestItem.objects.bulk_create(
            [
                FundRequestItem(
                    fund_request=fr,
                    activity_id=activity.id,
                    activity_schedule_cost_line_id=line.id,
                    amount=line.amount,
                    period=period,
                    period_key=period_key,
                )
                for activity, line in request_items
            ]
        )
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
        # FY. Now it narrows by the reliable schedule-time month/week derived
        # from planned_date (planned_week/planned_month are a separate legacy
        # pair only populated when a caller happens to pass them explicitly,
        # so filtering on them silently dropped real scheduled activities).
        week = data.get("week")
        if not week:
            match = re.search(r"-W(\d+)$", period_key or "")
            week = int(match.group(1)) if match else None
        if week:
            week = int(week)
            # planned_week (like planned_month) is only populated when a caller
            # happens to pass it explicitly — derive week-of-month from the
            # reliably-set planned_date instead (same formula used throughout
            # the app, e.g. apps.my_plan.services / apps.activities.services).
            matching_ids = [
                a.id
                for a in qs.only("id", "planned_date")
                if a.planned_date and min(5, (a.planned_date.day - 1) // 7 + 1) == week
            ]
            qs = qs.filter(id__in=matching_ids)
        month = data.get("month")
        if month:
            qs = qs.filter(month=int(month))
    elif period == FundRequestPeriod.MONTHLY:
        month = data.get("month")
        if not month:
            match = re.search(r"-M(\d+)$", period_key or "")
            month = int(match.group(1)) if match else None
        if month:
            qs = qs.filter(month=int(month))
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


# Statuses a reviewer may act on. Approving an already-disbursed request (or
# re-approving an approved one) would rewrite financial history.
_REVIEWABLE_STATUSES = (
    FundRequestStatus.SUBMITTED,
    FundRequestStatus.SUBMITTED_TO_PL,
    FundRequestStatus.SUBMITTED_TO_CD,
    FundRequestStatus.SUBMITTED_TO_RVP,
    FundRequestStatus.SENT_TO_ACCOUNTANT,
    FundRequestStatus.HELD,
)


def _review(request_id: str, new_status: str, data: dict, principal) -> dict:
    with transaction.atomic():
        fr = FundRequest.objects.select_for_update().filter(id=request_id).first()
        if not fr:
            raise NotFoundError("Fund request not found.")
        # Self-approval is the one chain rule that must hold regardless of
        # which coarse permission the caller carries (the weekly path enforces
        # the same rule via _require_weekly_approver).
        if fr.submitted_by_user_id == principal.user_id:
            raise BadRequest("You cannot review your own fund request.")
        if fr.status not in _REVIEWABLE_STATUSES:
            raise BadRequest(
                f"A request in status '{fr.status}' can no longer be reviewed."
            )
        fr.status = new_status
        fr.reviewed_by_user_id = principal.user_id
        fr.reviewed_at = timezone.now()
        fr.review_note = data.get("note")
        fr.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "review_note",
            ]
        )
    _audit_fund_request(
        principal,
        f"fund_request.{new_status}",
        fr,
        {"note": data.get("note") or ""},
    )
    return _serialize(fr)


def _audit_fund_request(principal, action: str, fr: FundRequest, payload: dict):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="FundRequest",
            subject_id=fr.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"period": fr.period, "period_key": fr.period_key, **payload},
        )
    except Exception:  # pragma: no cover — audit must never break the flow
        pass


def approve(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.APPROVED, data, principal)


def return_request(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.RETURNED, data, principal)


def reject(request_id: str, data: dict, principal) -> dict:
    return _review(request_id, FundRequestStatus.REJECTED, data, principal)


def disburse(request_id: str, data: dict, principal) -> dict:
    """Accountant clears an APPROVED request -> disbursed.

    select_for_update + the in-transaction status check close the double-click
    race, and the cross-channel guard refuses to release money for budget
    lines whose advances were already paid through the weekly/advance queues —
    the AdvanceRequest rows are the shared ledger all channels converge on."""
    with transaction.atomic():
        fr = FundRequest.objects.select_for_update().filter(id=request_id).first()
        if not fr:
            raise NotFoundError("Fund request not found.")
        if fr.status not in (
            FundRequestStatus.APPROVED,
            FundRequestStatus.SENT_TO_ACCOUNTANT,
        ):
            raise BadRequest("Only an approved request can be disbursed.")

        line_ids = list(
            fr.items.exclude(activity_schedule_cost_line_id="").values_list(
                "activity_schedule_cost_line_id", flat=True
            )
        )
        if line_ids:
            from .models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

            already = AdvanceRequest.objects.filter(
                budget_line_id__in=line_ids,
                status__in=MONEY_MOVED_ADVANCE_STATUSES,
            ).count()
            if already:
                raise BadRequest(
                    f"Cannot disburse — {already} of this request's budget lines "
                    "already had money released through the weekly/advance queue."
                )

        fr.status = FundRequestStatus.DISBURSED
        fr.disbursed_amount = data.get("amount", fr.total_amount)
        fr.disbursed_at = timezone.now()
        fr.disbursed_by_user_id = principal.user_id
        fr.disburse_method = data.get("method")
        fr.disburse_reference = data.get("reference")
        fr.save(
            update_fields=[
                "status",
                "disbursed_amount",
                "disbursed_at",
                "disbursed_by_user_id",
                "disburse_method",
                "disburse_reference",
            ]
        )
        # WRITE the shared advance ledger, not just read it. The weekly and
        # legacy channels both mark child advances DISBURSED when money moves;
        # this channel only checked — leaving the same cost line payable a
        # second time through the advance/weekly queue after a period-first
        # disbursement.
        if line_ids:
            AdvanceRequest.objects.filter(
                budget_line_id__in=line_ids,
                status__in=[
                    "pending_responsible_confirmation",
                    "confirmed_for_advance",
                    "submitted_to_accountant",
                ],
            ).update(
                status="disbursed",
                disbursed_at=fr.disbursed_at,
                disbursed_by_user_id=principal.user_id,
                disburse_method=fr.disburse_method,
                disburse_reference=fr.disburse_reference,
                updated_at=timezone.now(),
            )
    _audit_fund_request(
        principal,
        "fund_request.disburse",
        fr,
        {"amount": fr.disbursed_amount, "reference": fr.disburse_reference or ""},
    )
    return _serialize(fr)


def submit_accountability(request_id: str, data: dict, principal) -> dict:
    with transaction.atomic():
        return _submit_accountability_locked(request_id, data, principal)


def _submit_accountability_locked(request_id: str, data: dict, principal) -> dict:
    fr = FundRequest.objects.select_for_update().filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    # Accountability exists only for money that actually left the account.
    if fr.status != FundRequestStatus.DISBURSED:
        raise BadRequest(
            f"Accountability can only be submitted for a disbursed request "
            f"(current status: '{fr.status}')."
        )
    fr.accounted_amount = data.get("amountSpent")
    fr.returned_amount = data.get("amountReturned")
    fr.accountability_netsuite_id = data.get("netsuiteId")
    fr.accountability_status = "submitted"
    fr.accountability_submitted_at = timezone.now()
    fr.save(
        update_fields=[
            "accounted_amount",
            "returned_amount",
            "accountability_netsuite_id",
            "accountability_status",
            "accountability_submitted_at",
        ]
    )
    return _serialize(fr)


def review_accountability(
    request_id: str, decision: str, data: dict, principal
) -> dict:
    with transaction.atomic():
        return _review_accountability_locked(request_id, decision, data, principal)


def _review_accountability_locked(
    request_id: str, decision: str, data: dict, principal
) -> dict:
    fr = FundRequest.objects.select_for_update().filter(id=request_id).first()
    if not fr:
        raise NotFoundError("Fund request not found.")
    # Only a disbursed request with submitted accountability is reviewable —
    # this path previously had NO state guard and could knock a DISBURSED
    # request back to a resubmittable status, letting submit() rewrite the
    # items of already-paid work.
    if fr.status != FundRequestStatus.DISBURSED:
        raise BadRequest(
            f"Accountability review requires a disbursed request "
            f"(current status: '{fr.status}')."
        )
    if fr.accountability_status != "submitted":
        raise BadRequest("No submitted accountability to review.")
    if decision == "approve":
        fr.accountability_status = "approved"
        fr.status = FundRequestStatus.CLOSED
    else:
        # Return the ACCOUNTABILITY for correction — the request itself stays
        # DISBURSED (money already moved; the request is not resubmittable).
        fr.accountability_status = "returned"
    fr.accountability_reviewed_at = timezone.now()
    fr.reviewed_by_user_id = principal.user_id
    fr.save(
        update_fields=[
            "accountability_status",
            "status",
            "accountability_reviewed_at",
            "reviewed_by_user_id",
        ]
    )
    return _serialize(fr)


def regenerate(period: str, principal) -> dict:
    """Idempotent manual regeneration (weekly/monthly)."""
    data = {"period": period, "fy": get_operational_fy()}
    return submit(data, principal)


def _to_costable(a: Activity) -> dict:
    return {
        "activityType": a.activity_type,
        "deliveryType": a.delivery_type,
        "teachersAttended": a.teachers_attended,
        "leadersAttended": a.leaders_attended,
        "otherParticipants": a.other_participants,
        "projectId": a.project_id,
        "estCostCents": a.est_cost_cents,
        "costMissing": a.cost_missing,
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
