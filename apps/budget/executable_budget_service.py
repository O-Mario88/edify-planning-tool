"""Canonical monthly executable need derived from operational cost snapshots."""

from __future__ import annotations

from django.db.models import Sum

from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES


def monthly_executable_budget(*, fy: str, month: int, country: str = "Uganda") -> dict:
    """Return payable need, explicitly separating forecasts and actual spend.

    Reference costs are never part of ``executableNeed``. Partner delivery is
    excluded because its contracted amount follows the Partner Payment Service.
    """
    from apps.activities.models import ActivityScheduleCostLine
    from apps.budget.models import ActivityCostSnapshot, ActivityCostStatus
    from apps.fund_requests.models import (
        MONEY_MOVED_ADVANCE_STATUSES,
        AdvanceRequest,
    )
    from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget

    base = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True,
        activity__scheduled_date__isnull=False,
        activity__cost_missing=False,
        activity__fy=str(fy),
        month=int(month),
    ).exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)

    partner_total = int(
        base.filter(activity__delivery_type="partner").aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    staff_lines = base.exclude(activity__delivery_type="partner")
    amendment_activity_ids = ActivityCostSnapshot.objects.filter(
        activity_id__in=staff_lines.values("activity_id"),
        is_current=True,
        cost_status=ActivityCostStatus.AMENDMENT_REQUIRED,
    ).values("activity_id")
    amendment_total = int(
        staff_lines.filter(activity_id__in=amendment_activity_ids).aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )
    eligible = staff_lines.exclude(activity_id__in=amendment_activity_ids)
    funded_line_ids = AdvanceRequest.objects.filter(
        budget_line_id__in=eligible.values("id"),
        status__in=MONEY_MOVED_ADVANCE_STATUSES,
    ).values("budget_line_id")
    already_funded = int(
        eligible.filter(id__in=funded_line_ids).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    scheduled_operational = int(eligible.aggregate(total=Sum("amount"))["total"] or 0)
    unfunded_operational = max(0, scheduled_operational - already_funded)

    calendar_year = int(fy) - 1 if int(month) >= 10 else int(fy)
    month_key = f"{calendar_year}-{int(month):02d}"
    fixed_commitments = int(
        AdminBudgetLine.objects.filter(
            monthly_budget__country_id=country,
            monthly_budget__month_key=month_key,
            status="active",
        ).aggregate(total=Sum("total_cost"))["total"]
        or 0
    )

    # Only accountant-verified returns are reusable. Potential avoidance and
    # raw under-spend are intentionally absent from this credit calculation.
    cleared_reusable = int(
        AdvanceRequest.objects.filter(
            return_verified_at__year=calendar_year,
            return_verified_at__month=int(month),
            returned_amount__gt=0,
        ).aggregate(total=Sum("returned_amount"))["total"]
        or 0
    )
    other_approved_credits = 0
    executable_need = max(
        0,
        unfunded_operational
        + fixed_commitments
        - cleared_reusable
        - other_approved_credits,
    )

    activity_ids = list(eligible.values_list("activity_id", flat=True).distinct())
    snapshots = ActivityCostSnapshot.objects.filter(
        activity_id__in=activity_ids, is_current=True
    )
    reference_forecast = int(
        snapshots.aggregate(total=Sum("reference_cost"))["total"] or 0
    )
    reference_missing_count = snapshots.filter(reference_cost__isnull=True).count()
    actual_accounted_spend = int(
        AdvanceRequest.objects.filter(
            budget_line_id__in=base.values("id"),
            accounted_amount__isnull=False,
        ).aggregate(total=Sum("accounted_amount"))["total"]
        or 0
    )

    return {
        "fy": str(fy),
        "month": int(month),
        "currency": "UGX",
        "scheduledOperationalCost": scheduled_operational,
        "approvedFixedCommitments": fixed_commitments,
        "activitiesAlreadyFunded": already_funded,
        "clearedReusableBalances": cleared_reusable,
        "otherApprovedFundingCredits": other_approved_credits,
        "executableNeed": executable_need,
        "eligibleActivityCount": len(set(activity_ids)),
        "partnerPaymentChannelExcluded": partner_total,
        "costAmendmentRequiredExcluded": amendment_total,
        "referenceForecast": reference_forecast,
        "referenceConfigurationMissingCount": reference_missing_count,
        "actualAccountedSpend": actual_accounted_spend,
        "potentialCostAvoidance": max(0, reference_forecast - scheduled_operational),
        "operationalPremium": max(0, scheduled_operational - reference_forecast)
        if reference_missing_count == 0
        else None,
    }


__all__ = ["monthly_executable_budget"]
