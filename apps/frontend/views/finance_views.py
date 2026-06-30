"""
GROUP 2 — Finance & Budget Views
Disbursements, Budget Overview, Cost Catalogue, Fund Requests list
"""
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date

from apps.fund_requests.models import FundRequest, WeeklyFundRequest, AdvanceRequest, AdvanceRequestStatus
from apps.budget.models import CostCatalogue, CostSetting, MonthlyFundRequest
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy


@login_required(login_url="/login")
def fund_requests_list_view(request):
    """All fund requests list — finance overview."""
    fy = get_operational_fy()
    status_filter = request.GET.get("status", "")

    requests_qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)

    requests_list = list(requests_qs[:50])
    total_requested = sum(r.total_amount or 0 for r in requests_list)
    total_disbursed = sum(r.disbursed_amount or 0 for r in requests_list if r.disbursed_amount)

    STATUS_CHOICES = [
        "pending_responsible_confirmation",
        "pending_pl_approval",
        "pending_cd_approval",
        "pending_disbursement",
        "disbursed",
        "rejected",
    ]

    context = {
        "requests": requests_list,
        "total_requested": total_requested,
        "total_disbursed": total_disbursed,
        "status_filter": status_filter,
        "status_choices": STATUS_CHOICES,
    }
    return render(request, "pages/fund_requests/index.html", context)


@login_required(login_url="/login")
def disbursements_view(request):
    """Disbursement tracking — accountant view."""
    fy = get_operational_fy()

    ready = WeeklyFundRequest.objects.filter(status="pending_disbursement").order_by("-week_start_date")
    recent_disbursed = WeeklyFundRequest.objects.filter(status="disbursed").order_by("-disbursed_at")[:20]
    pending_accountability = WeeklyFundRequest.objects.filter(
        status="disbursed",
        accounted_amount__isnull=True,
    ).order_by("-disbursed_at")

    total_ready = ready.aggregate(total=Sum("total_amount"))["total"] or 0
    total_disbursed = recent_disbursed.aggregate(total=Sum("disbursed_amount"))["total"] or 0

    context = {
        "ready": ready,
        "recent_disbursed": recent_disbursed,
        "pending_accountability": pending_accountability,
        "total_ready": total_ready,
        "total_disbursed": total_disbursed,
    }
    return render(request, "pages/disbursements/index.html", context)


@login_required(login_url="/login")
def budget_overview_view(request):
    """Budget overview — CD/Accountant view."""
    fy = get_operational_fy()

    monthly_data = WeeklyFundRequest.objects.values("week_start_date__month").annotate(
        requested=Sum("total_amount"),
        disbursed=Sum("disbursed_amount"),
        count=Count("id"),
    ).order_by("week_start_date__month")

    total_budget = WeeklyFundRequest.objects.aggregate(
        total_requested=Sum("total_amount"),
        total_disbursed=Sum("disbursed_amount"),
        total_approved=Sum("total_amount", filter=Q(status__in=["pending_disbursement", "disbursed"])),
    )

    pending_approvals = WeeklyFundRequest.objects.filter(
        status__in=["pending_pl_approval", "pending_cd_approval"]
    ).count()

    context = {
        "monthly_data": monthly_data,
        "total_budget": total_budget,
        "pending_approvals": pending_approvals,
        "fy": fy,
    }
    return render(request, "pages/budget/index.html", context)


@login_required(login_url="/login")
def cost_settings_view(request):
    """CD Cost Catalogue management."""
    fy = get_operational_fy()

    catalogues = CostCatalogue.objects.filter(fy=fy).order_by("-version")
    active_catalogue = catalogues.filter(is_active=True).first()

    cost_items = []
    if active_catalogue:
        cost_items = list(CostSetting.objects.filter(
            catalogue=active_catalogue
        ).order_by("item_key"))

    context = {
        "catalogues": catalogues,
        "active_catalogue": active_catalogue,
        "cost_items": cost_items,
        "fy": fy,
    }
    return render(request, "pages/cost_settings/index.html", context)
