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
    """All fund requests list — redirect to weekly."""
    return redirect("/fund-requests/weekly")


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

@login_required(login_url="/login")
def fund_allocation_view(request):
    import csv
    from django.http import HttpResponse
    from apps.geography.models import Region, District
    from apps.budget.allocation_service import MonthlyFundAllocationService
    
    # 1. Parse filter inputs & parameters
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()
    region_id = request.GET.get("region", "").strip()
    district_id = request.GET.get("district", "").strip()
    search_q = request.GET.get("q", "").strip()
    
    try:
        page = int(request.GET.get("page", 1))
    except ValueError:
        page = 1
        
    try:
        per_page = int(request.GET.get("per_page", 10))
    except ValueError:
        per_page = 10
        
    MONTH_MAP = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
    month_num = MONTH_MAP.get(month_name.lower(), 4)
    
    # 2. Get Allocation Data & Calculations
    data = MonthlyFundAllocationService.get_monthly_allocation(
        month_num=month_num,
        fy=fy,
        region_id=region_id or None,
        district_id=district_id or None,
        search_q=search_q or None,
        page=page,
        per_page=per_page
    )
    
    # Check if CSV export is requested
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="consolidated_fund_allocation_{month_name}_{fy}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            "Staff", "Staff Visits Count", "Staff Visits Cost", "Staff Visits Total", 
            "Partner Visits Count", "Partner Visits Cost", "Partner Visits Total", 
            "SSA Count", "SSA Cost", "SSA Total", 
            "Cluster Training Count", "Cluster Training Cost", "Cluster Training Total", 
            "Partner In-School Training Count", "Partner In-School Training Cost", "Partner In-School Training Total", 
            "Total Monthly Allocation"
        ])
        for r in data["rows_all"]:
            writer.writerow([
                r["name"],
                r["staff_visits"]["count"], r["staff_visits"]["unit_cost"], r["staff_visits"]["total"],
                r["partner_visits"]["count"], r["partner_visits"]["unit_cost"], r["partner_visits"]["total"],
                r["ssa"]["count"], r["ssa"]["unit_cost"], r["ssa"]["total"],
                r["cluster_training"]["count"], r["cluster_training"]["unit_cost"], r["cluster_training"]["total"],
                r["partner_in_school_training"]["count"], r["partner_in_school_training"]["unit_cost"], r["partner_in_school_training"]["total"],
                r["total_allocation"]
            ])
        return response
        
    insights = MonthlyFundAllocationService.calculate_insights(
        rows_all=data["rows_all"],
        grand_totals=data["grand_totals"],
        total_staff_count=data["total_staff_count"]
    )
    
    # Pagination info
    total_pages = (data["total_staff_count"] + per_page - 1) // per_page
    pages_list = list(range(1, total_pages + 1))
    showing_start = (page - 1) * per_page + 1 if data["total_staff_count"] > 0 else 0
    showing_end = min(page * per_page, data["total_staff_count"])
    
    # 3. Filter Options Lists
    regions = Region.objects.all().order_by("name")
    districts = District.objects.all().order_by("name")
    
    # 4. Render context
    context = {
        "rows": data["rows"],
        "grand_totals": data["grand_totals"],
        "total_staff_count": data["total_staff_count"],
        "total_activities_count": data["total_activities_count"],
        "insights": insights,
        
        # Pagination
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "pages_list": pages_list,
        "showing_start": showing_start,
        "showing_end": showing_end,
        
        # Filters dropdown options
        "regions": regions,
        "districts": districts,
        
        # Selected states
        "selected_month": month_name,
        "selected_fy": fy,
        "selected_region": region_id,
        "selected_district": district_id,
        "search_q": search_q,
        
        # Dark sidebar indicator
        "use_dark_sidebar": True,
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
    }
    
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/finance/allocation_table.html", context)
        
    return render(request, "pages/finance/fund_allocation.html", context)
