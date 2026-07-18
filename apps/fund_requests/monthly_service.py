"""Automatic draft monthly fund-request snapshots from scheduled cost lines.

Scheduling is the moment work becomes budget-bearing.  This service keeps a
per-owner, per-month *draft* FundRequest in sync with that work so monthly
finance views and the PL approval queue have a real record immediately.  It
never rewrites a request once it has been submitted or approved.
"""

from __future__ import annotations

from django.db import transaction

from apps.activities.models import Activity, ActivityScheduleCostLine

from .models import FundRequest, FundRequestItem, FundRequestPeriod, FundRequestStatus


def _period_key(fy: str, month: int) -> str:
    return f"{fy}-M{int(month)}"


def _fundable_lines(owner_id: str, fy: str, month: int):
    return list(
        ActivityScheduleCostLine.objects.filter(
            responsible_user=owner_id,
            fiscal_year=fy,
            month=month,
            activity__deleted_at__isnull=True,
            activity__scheduled_date__isnull=False,
            activity__cost_missing=False,
        )
        .exclude(activity__status__in=["cancelled", "rejected"])
        .select_related("activity")
    )


def sync_monthly_drafts_for_activity(activity: Activity, *, prior_buckets=()) -> None:
    """Refresh affected monthly draft requests after an activity is costed.

    ``prior_buckets`` is captured before the cost lines are rebuilt.  Including
    those buckets is what clears an old owner's/month's draft when a scheduled
    activity is reassigned or moved.
    """
    periods = {
        (owner, fy, int(month))
        for owner, fy, month, _week_start in prior_buckets
        if owner and fy and month
    }
    periods.update(
        (owner, fy, int(month))
        for owner, fy, month in ActivityScheduleCostLine.objects.filter(
            activity=activity
        ).values_list("responsible_user", "fiscal_year", "month")
        if owner and fy and month
    )
    if not periods:
        return

    with transaction.atomic():
        # Clear mutable snapshots first.  This avoids a unique-line collision
        # when the activity changed owner and its cost lines move between two
        # draft requests in the same month.
        existing = {}
        for owner_id, fy, month in periods:
            request = (
                FundRequest.objects.select_for_update()
                .filter(
                    submitted_by_user_id=owner_id,
                    period=FundRequestPeriod.MONTHLY,
                    period_key=_period_key(fy, month),
                )
                .first()
            )
            existing[(owner_id, fy, month)] = request
            if request and request.status == FundRequestStatus.DRAFT:
                request.items.all().delete()

        for owner_id, fy, month in periods:
            request = existing[(owner_id, fy, month)]
            lines = _fundable_lines(owner_id, fy, month)
            if not lines:
                if request and request.status == FundRequestStatus.DRAFT:
                    request.delete()
                continue

            total = sum(line.amount for line in lines)
            activity_count = len({line.activity_id for line in lines})
            if request is None:
                request = FundRequest.objects.create(
                    fy=fy,
                    period=FundRequestPeriod.MONTHLY,
                    period_key=_period_key(fy, month),
                    scope="own",
                    submitted_by_user_id=owner_id,
                    submitted_by_role="",
                    total_amount=total,
                    activity_count=activity_count,
                    status=FundRequestStatus.DRAFT,
                )
            elif request.status != FundRequestStatus.DRAFT:
                # A submitted/approved request is a finance snapshot. New work
                # remains in the live budget and weekly request, but cannot
                # silently alter a request already in the approval chain.
                continue
            else:
                request.fy = fy
                request.total_amount = total
                request.activity_count = activity_count
                request.save(
                    update_fields=[
                        "fy",
                        "total_amount",
                        "activity_count",
                        "updated_at",
                    ]
                )

            FundRequestItem.objects.bulk_create(
                [
                    FundRequestItem(
                        fund_request=request,
                        activity_id=line.activity_id,
                        activity_schedule_cost_line_id=line.id,
                        amount=line.amount,
                        period=FundRequestPeriod.MONTHLY,
                        period_key=_period_key(fy, month),
                    )
                    for line in lines
                ]
            )


__all__ = ["sync_monthly_drafts_for_activity"]
