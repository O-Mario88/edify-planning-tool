"""
GROUP 2 — Finance & Budget Views
Disbursements, Budget Overview, Cost Catalogue, Fund Requests list
"""
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse

from apps.fund_requests.models import WeeklyFundRequest, AdvanceRequest, AdvanceRequestStatus
from apps.budget.models import CostCatalogue, CostSetting
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.fund_requests.weekly_service import disburse as disburse_weekly
from apps.fund_requests.advance_service import (
    reimburse as process_reimburse
)


@require_page_permission("fund_requests")
def fund_requests_list_view(request):
    """All fund requests list — redirect to weekly."""
    return redirect("/fund-requests/weekly")


@require_page_permission("disbursements")
def disbursements_view(request):
    """Fully automated, investor-grade Accountant Dashboard."""
    if request.user.active_role != "Accountant":
        messages.error(request, "Access restricted to Program Accountants.")
        return redirect("/dashboard")

    fy = get_operational_fy()

    # 1. Ready for Advance Disbursement
    ready_disburse = WeeklyFundRequest.objects.filter(status="confirmed_for_advance").order_by("-week_start_date")

    # 2. Ready for Partner Payment
    ready_partner_payments = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        status="ia_verified",
        payment_status="ia_confirmed"
    ).order_by("-updated_at")

    # 3. Accountability Pending
    # Weekly fund requests that are disbursed and CCEO has submitted accountability
    pending_accountability = WeeklyFundRequest.objects.filter(
        status="disbursed",
        accounted_amount__isnull=False
    ).exclude(status="accounted").order_by("-accountability_submitted_at")

    # 4. Ready for Reimbursement
    # Advance requests where staff chose self-funded path and submitted reimbursement
    ready_reimbursement = AdvanceRequest.objects.filter(
        status="reimbursement_submitted"
    ).order_by("-accountability_submitted_at")

    # 5. Returned Finance Items
    returned_items = WeeklyFundRequest.objects.filter(
        status="returned_by_accountant"
    ).order_by("-updated_at")

    # 6. Cleared / Closed
    cleared_weekly = WeeklyFundRequest.objects.filter(
        status="accounted"
    ).order_by("-accountability_reviewed_at")[:10]

    cleared_partners = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        payment_status="paid"
    ).order_by("-updated_at")[:10]

    cleared_reimbursements = AdvanceRequest.objects.filter(
        status="reimbursed"
    ).order_by("-updated_at")[:10]

    context = {
        "ready_disburse": ready_disburse,
        "ready_partner_payments": ready_partner_payments,
        "pending_accountability": pending_accountability,
        "ready_reimbursement": ready_reimbursement,
        "returned_items": returned_items,
        "cleared_weekly": cleared_weekly,
        "cleared_partners": cleared_partners,
        "cleared_reimbursements": cleared_reimbursements,
        "fy": fy,
    }
    return render(request, "pages/disbursements/index.html", context)


@require_page_permission("disbursements")
def finance_action_drawer_view(request):
    """GET to render the floating drawer for various finance actions."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    action = request.GET.get("action")
    request_id = request.GET.get("request_id")
    activity_id = request.GET.get("activity_id")
    advance_id = request.GET.get("advance_id")

    item = None
    if request_id:
        # Load WeeklyFundRequest
        wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
        from apps.fund_requests.weekly_service import _serialize_request
        item = _serialize_request(wfr, include_lines=True)
        # Format field names to match template expectations
        item["accountedAmount"] = wfr.accounted_amount
        item["returnedAmount"] = wfr.returned_amount
        item["accountabilityNetsuiteId"] = wfr.accountability_netsuite_id
    elif activity_id:
        # Load Activity
        act = get_object_or_404(Activity, id=activity_id)
        from apps.activities.services import _serialize
        item = _serialize(act)
    elif advance_id:
        # Load AdvanceRequest
        adv = get_object_or_404(AdvanceRequest, id=advance_id)
        from apps.fund_requests.advance_service import _serialize as serialize_adv
        item = serialize_adv(adv)

    context = {
        "action": action,
        "item": item,
        "drawer_size": "md",
    }
    return render(request, "partials/finance/finance_action_drawer.html", context)


@require_page_permission("disbursements")
def disburse_advance_action(request):
    """POST to disburse weekly advance."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        amount = request.POST.get("amount")
        method = request.POST.get("method", "mobile_money")
        reference = request.POST.get("reference", "").strip()

        payload = {
            "method": method,
            "reference": reference,
        }

        try:
            if amount:
                payload["amount"] = int(amount)
            disburse_weekly(request_id, payload, request.user)
            response = HttpResponse('<script>window.location.reload();</script>')
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@require_page_permission("disbursements")
def clear_partner_payment_action(request):
    """POST to clear partner payment."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        activity_id = request.POST.get("activity_id")
        netsuite_id = request.POST.get("netsuite_id", "").strip()
        amount = request.POST.get("amount")
        reference = request.POST.get("reference", "").strip()

        activity = get_object_or_404(Activity, id=activity_id)

        try:
            from django.db import transaction
            with transaction.atomic():
                activity.payment_status = "paid"
                activity.status = "closed"
                activity.salesforce_sync_status = "synced"
                activity.save(update_fields=["payment_status", "status", "salesforce_sync_status", "updated_at"])
                
                # Log audit trail
                from apps.audit.services import log_event
                log_event(
                    user_id=request.user.user_id,
                    event_type="finance_partner_payment_clear",
                    description=f"Cleared payment for activity {activity.id}. NetSuite ID: {netsuite_id}",
                    metadata={"netsuite_id": netsuite_id, "amount": amount, "reference": reference}
                )

            response = HttpResponse('<script>window.location.reload();</script>')
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@require_page_permission("disbursements")
def process_reimbursement_action(request):
    """POST to disburse self-funded reimbursement."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        advance_id = request.POST.get("advance_id")
        netsuite_id = request.POST.get("netsuite_id", "").strip()
        amount = request.POST.get("amount")
        reference = request.POST.get("reference", "").strip()

        payload = {
            "method": "bank_transfer",
            "reference": reference,
            "netsuiteId": netsuite_id,
        }
        try:
            if amount:
                payload["amount"] = int(amount)
            adv = get_object_or_404(AdvanceRequest, id=advance_id)
            adv.accountability_netsuite_id = netsuite_id
            adv.save(update_fields=["accountability_netsuite_id"])

            process_reimburse(advance_id, payload, request.user)

            response = HttpResponse('<script>window.location.reload();</script>')
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@require_page_permission("disbursements")
def confirm_accountability_action(request):
    """POST to confirm and close advance accountability."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        netsuite_id = request.POST.get("netsuite_id", "").strip()

        try:
            from django.db import transaction
            with transaction.atomic():
                wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
                wfr.status = "accounted"
                wfr.accountability_netsuite_id = netsuite_id
                wfr.accountability_reviewed_at = timezone.now()
                wfr.save(update_fields=["status", "accountability_netsuite_id", "accountability_reviewed_at", "updated_at"])

                # Also confirm/approve accountability for linked AdvanceRequests
                for line in wfr.lines.select_related("activity_budget_line"):
                    adv = line.activity_budget_line.advance_requests.first()
                    if adv:
                        adv.status = AdvanceRequestStatus.ACCOUNTED
                        adv.accountability_netsuite_id = netsuite_id
                        adv.accountability_reviewed_at = timezone.now()
                        adv.save(update_fields=["status", "accountability_netsuite_id", "accountability_reviewed_at", "updated_at"])

            response = HttpResponse('<script>window.location.reload();</script>')
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@require_page_permission("disbursements")
def finance_return_action(request):
    """POST to return fund request for correction."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        reason = request.POST.get("reason", "").strip()

        try:
            from django.db import transaction
            with transaction.atomic():
                wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
                wfr.status = "returned_by_accountant"
                wfr.confirmed_at = None
                wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

                # Also return AdvanceRequests
                for line in wfr.lines.select_related("activity_budget_line"):
                    adv = line.activity_budget_line.advance_requests.first()
                    if adv:
                        adv.status = AdvanceRequestStatus.RETURNED
                        adv.last_note = reason
                        adv.save(update_fields=["status", "last_note", "updated_at"])

            response = HttpResponse('<script>window.location.reload();</script>')
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(f'<div class="p-3 bg-rose-50 text-rose-700 rounded-lg text-[12px] font-bold">Error: {str(e)}</div>', status=400)


@require_page_permission("consolidated_fund_allocation")
def budget_overview_view(request):
    """Budget overview — CD/Accountant view."""
    from apps.budget.services import fy_budget, monthly_budget
    fy = get_operational_fy()

    fy_data = fy_budget({"fy": fy})

    monthly_data = []
    for m in range(1, 13):
        m_data = monthly_budget({"fy": fy, "month": m})
        if m_data["plannedBudget"] > 0 or m_data["requestedBudget"] > 0:
            # Add helper display name for the month-of-fy (1=October, 2=November, ...)
            months_names = {
                1: "October", 2: "November", 3: "December", 4: "January",
                5: "February", 6: "March", 7: "April", 8: "May",
                9: "June", 10: "July", 11: "August", 12: "September"
            }
            m_data["display_name"] = months_names.get(m, f"Month {m}")
            monthly_data.append(m_data)

    pending_approvals = WeeklyFundRequest.objects.filter(
        status__in=["pending_pl_approval", "pending_cd_approval"]
    ).count()

    context = {
        "monthly_data": monthly_data,
        "fy_data": fy_data,
        "pending_approvals": pending_approvals,
        "fy": fy,
    }
    return render(request, "pages/budget/index.html", context)


@require_page_permission("consolidated_fund_allocation")
def cost_settings_view(request):
    """CD Cost Catalogue management."""
    fy = get_operational_fy()

    catalogues = CostCatalogue.objects.filter(fy=fy).order_by("-version")
    active_catalogue = catalogues.filter(is_active=True).first()

    cost_items = []
    if active_catalogue:
        cost_items = list(CostSetting.objects.filter(
            catalogue=active_catalogue
        ).order_by("key"))

    context = {
        "catalogues": catalogues,
        "active_catalogue": active_catalogue,
        "cost_items": cost_items,
        "fy": fy,
    }
    return render(request, "pages/cost_settings/index.html", context)

@require_page_permission("consolidated_fund_allocation")
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
    export_mode = request.GET.get("export_mode", "full").strip()
    
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
        
        if export_mode == "admin_only":
            writer.writerow(["Line Item Description", "Cost Category", "Quantity", "Unit Cost (UGX)", "Total Cost (UGX)", "Status"])
            for line in data["admin_budget_data"]["lines"]:
                writer.writerow([line["description"], line["cost_category"], line["quantity"], line["unit_cost"], line["total_cost"], line["status"]])
        else:
            writer.writerow([
                "Staff", "Staff Visits Count", "Staff Visits Cost", "Staff Visits Total", 
                "Partner Visits Count", "Partner Visits Cost", "Partner Visits Total", 
                "SSA Count", "SSA Cost", "SSA Total", 
                "Cluster Training Count", "Cluster Training Cost", "Cluster Training Total", 
                "Partner In-School Training Count", "Partner In-School Training Cost", "Partner In-School Training Total", 
                "Admin Budget Planned", "Admin Budget Allocated", "Admin Budget Total",
                "Total Monthly Allocation"
            ])
            rows_to_export = data["rows_all"]
            if export_mode == "field_only":
                rows_to_export = [r for r in rows_to_export if r["user_id"] != "cd_admin_budget"]
                
            for r in rows_to_export:
                admin_p = r.get("admin_budget", {}).get("planned", 0) if "admin_budget" in r else 0
                admin_a = r.get("admin_budget", {}).get("allocated", 0) if "admin_budget" in r else 0
                admin_t = r.get("admin_budget", {}).get("total", 0) if "admin_budget" in r else 0
                
                writer.writerow([
                    r["name"],
                    r["staff_visits"]["count"], r["staff_visits"]["unit_cost"], r["staff_visits"]["total"],
                    r["partner_visits"]["count"], r["partner_visits"]["unit_cost"], r["partner_visits"]["total"],
                    r["ssa"]["count"], r["ssa"]["unit_cost"], r["ssa"]["total"],
                    r["cluster_training"]["count"], r["cluster_training"]["unit_cost"], r["cluster_training"]["total"],
                    r["partner_in_school_training"]["count"], r["partner_in_school_training"]["unit_cost"], r["partner_in_school_training"]["total"],
                    admin_p, admin_a, admin_t,
                    r["total_allocation"]
                ])
        return response
        
    insights = MonthlyFundAllocationService.calculate_insights(
        rows_all=data["rows_all"],
        grand_totals=data["grand_totals"],
        total_staff_count=data["total_staff_count"]
    )
    
    # Format UGX compact helper
    def format_ugx_compact(val):
        if not val:
            return "UGX 0"
        if val >= 1_000_000_000:
            return f"UGX {val / 1_000_000_000:.1f}B"
        if val >= 1_000_000:
            return f"UGX {val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"UGX {val / 1_000:.0f}K"
        return f"UGX {val}"

    grand_totals = data["grand_totals"]
    total_staff_count = data["total_staff_count"]
    total_activities_count = data["total_activities_count"]

    kpi_strip_items = [
        {
            "label": "Total Allocation",
            "value": format_ugx_compact(grand_totals.get("total_allocation", 0)),
            "raw_value": int(grand_totals.get("total_allocation", 0)),
            "helper": f"Across {total_staff_count} staff",
            "icon": "finance",
            "variant": "finance",
        },
        {
            "label": "Staff Included",
            "value": str(total_staff_count),
            "raw_value": total_staff_count,
            "helper": "Active staff",
            "icon": "users",
            "variant": "primary",
        },
        {
            "label": "Planned Activities",
            "value": str(total_activities_count),
            "raw_value": total_activities_count,
            "helper": "Across categories",
            "icon": "chart",
            "variant": "info",
        },
        {
            "label": "Staff Visits Cost",
            "value": format_ugx_compact(grand_totals.get("staff_visits", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("staff_visits", {}).get("total", 0)),
            "helper": f"{grand_totals.get('staff_visits', {}).get('count', 0)} visits",
            "icon": "school",
            "variant": "blue",
        },
        {
            "label": "Partner Visits Cost",
            "value": format_ugx_compact(grand_totals.get("partner_visits", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("partner_visits", {}).get("total", 0)),
            "helper": f"{grand_totals.get('partner_visits', {}).get('count', 0)} visits",
            "icon": "users",
            "variant": "purple",
        },
        {
            "label": "SSA Cost",
            "value": format_ugx_compact(grand_totals.get("ssa", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("ssa", {}).get("total", 0)),
            "helper": f"{grand_totals.get('ssa', {}).get('count', 0)} visits",
            "icon": "report",
            "variant": "warning",
        },
        {
            "label": "Cluster Training Cost",
            "value": format_ugx_compact(grand_totals.get("cluster_training", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("cluster_training", {}).get("total", 0)),
            "helper": f"{grand_totals.get('cluster_training', {}).get('count', 0)} schools",
            "icon": "target",
            "variant": "success",
        },
        {
            "label": "Admin Budget",
            "value": format_ugx_compact(grand_totals.get("admin_budget", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("admin_budget", {}).get("total", 0)),
            "helper": "CD Plan",
            "icon": "currency",
            "variant": "neutral",
        }
    ]

    # Pagination info
    total_pages = (data["total_staff_count"] + per_page - 1) // per_page
    from apps.core.pagination import make_pagination_window
    pages_list = make_pagination_window(page, total_pages)
    showing_start = (page - 1) * per_page + 1 if data["total_staff_count"] > 0 else 0
    showing_end = min(page * per_page, data["total_staff_count"])
    
    # 3. Filter Options Lists
    regions = Region.objects.all().order_by("name")
    districts = District.objects.all().order_by("name")
    
    # 4. Render context
    context = {
        "rows": data["rows"],
        "grand_totals": data["grand_totals"],
        "kpi_strip_items": kpi_strip_items,
        "total_staff_count": data["total_staff_count"],
        "total_activities_count": data["total_activities_count"],
        "insights": insights,
        "admin_budget_data": data["admin_budget_data"],
        
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
        return render(request, "partials/finance/fund_allocation_table.html", context)
        
    return render(request, "pages/finance/fund_allocation.html", context)


@require_page_permission("consolidated_fund_allocation")
def admin_budget_drilldown_view(request):
    """GET to render the admin budget breakdown floating drawer."""
    from apps.budget.admin_budget_service import AdminBudgetAllocationService
    
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()
    
    MONTH_MAP = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
    month_num = MONTH_MAP.get(month_name.lower(), 4)
    
    admin_data = AdminBudgetAllocationService.get_admin_budget_allocation(month_num, fy)
    
    context = {
        "admin_data": admin_data,
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "lg",
    }
    return render(request, "partials/finance/admin_budget_drilldown.html", context)


@require_page_permission("consolidated_fund_allocation")
def allocation_drilldown_view(request):
    """GET to render detailed activities list for a specific staff's cell."""
    staff_id = request.GET.get("staff_id", "").strip()
    category = request.GET.get("category", "").strip()
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()
    
    MONTH_MAP = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
    month_num = MONTH_MAP.get(month_name.lower(), 4)
    
    from apps.accounts.models import User
    staff_user = get_object_or_404(User, id=staff_id)
    
    # Query cost lines for this staff in the month & FY
    cost_lines = ActivityScheduleCostLine.objects.filter(
        fiscal_year=fy,
        month=month_num,
        responsible_user=staff_id
    ).select_related("activity", "activity__school", "activity__cluster")
    
    # Filter by category classification
    filtered_lines = []
    for line in cost_lines:
        act = line.activity
        act_type = act.activity_type
        delivery = act.delivery_type
        
        # Classification
        if act_type == "ssa_activity":
            cat = "ssa"
        elif act_type in ["cluster_training", "training", "school_improvement_training", "core_training", "cluster_meeting"]:
            cat = "cluster_training"
        elif act_type == "partner_activity" or (act_type in ["training", "school_improvement_training", "core_training"] and delivery == "partner"):
            cat = "partner_in_school_training"
        elif act_type in VISIT_TYPES and delivery == "partner":
            cat = "partner_visits"
        else:
            cat = "staff_visits"
            
        if cat == category:
            filtered_lines.append(line)
            
    context = {
        "staff_user": staff_user,
        "category_label": category.replace("_", " ").title(),
        "lines": filtered_lines,
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "lg",
    }
    return render(request, "partials/finance/allocation_drilldown_drawer.html", context)


@require_page_permission("consolidated_fund_allocation")
def export_drawer_view(request):
    """GET to render the CSV export settings floating drawer."""
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()
    
    context = {
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "sm",
    }
    return render(request, "partials/finance/export_drawer.html", context)


@require_page_permission("dashboard")
def cost_setting_row_view(request, key):
    from django.shortcuts import get_object_or_404
    from django.http import HttpResponse
    from apps.budget.models import CostSetting
    from apps.budget import services as budget_services
    
    if request.user.active_role not in ("CountryDirector", "Admin"):
        return HttpResponse("Forbidden", status=403)
        
    setting = get_object_or_404(CostSetting, key=key)
    mode = request.GET.get("mode", "view")
    
    if request.method == "POST":
        new_cost_str = request.POST.get("unit_cost", "").strip()
        reason = request.POST.get("reason", "").strip() or "Updated via CD Dashboard"
        try:
            new_cost = int(new_cost_str.replace(",", ""))
            budget_services.upsert_cost_setting({
                "key": setting.key,
                "label": setting.label,
                "unitCost": new_cost,
                "reason": reason,
                "fy": setting.fy,
            }, request.user)
            setting = CostSetting.objects.get(key=key)
            mode = "view"
        except ValueError:
            return HttpResponse("Invalid cost value", status=400)
            
    context = {
        "c": setting,
        "mode": mode,
    }
    return render(request, "partials/cost_settings/cost_setting_row.html", context)


@require_page_permission("dashboard")
def initialize_default_catalogue_view(request):
    from django.shortcuts import redirect
    from django.http import HttpResponse
    from apps.budget.models import CostCatalogue, CostSetting
    from apps.core.fy import get_operational_fy
    
    if request.user.active_role not in ("CountryDirector", "Admin"):
        return HttpResponse("Forbidden", status=403)
        
    fy = get_operational_fy()
    active = CostCatalogue.objects.filter(fy=fy, is_active=True).first()
    if not active:
        active = CostCatalogue.objects.create(
            country="Uganda",
            fy=fy,
            version=1,
            is_active=True,
            label=f"Uganda FY{fy} Country Cost Catalogue",
        )
    default_settings = [
        ("accommodation", "Accommodation per night", 40000, "per night"),
        ("breakfast", "Breakfast", 8000, "per head"),
        ("cluster_meeting_cost", "Cluster meeting participant meal cost", 10000, "per head"),
        ("dinner", "Dinner", 12000, "per head"),
        ("lunch", "Lunch", 12000, "per head"),
        ("meals_per_participant", "Group training participant meal cost", 5000, "per head"),
        ("mobilisation_per_participant", "Mobilisation cost per participant", 2000, "per head"),
        ("partner_training_lump_sum", "Partner training/facilitation rate", 16000, "per item"),
        ("partner_visit_lump_sum", "Partner visit rate", 40000, "per item"),
        ("staff_visit_transport_primary", "Staff visit transport (primary district)", 50000, "per item"),
        ("staff_visit_transport_secondary", "Staff visit transport (secondary district)", 25000, "per item"),
        ("training_session_fee", "Facilitation fee", 50000, "per session"),
        ("venue", "Venue cost", 30000, "per day"),
    ]
    for key, label, cost, unit in default_settings:
        CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": cost,
                "fy": fy,
                "catalogue": active,
                "version": 1,
            }
        )
    CostSetting.objects.filter(catalogue__isnull=True).update(catalogue=active)
        
    return redirect("/dashboard")


@require_page_permission("country_budget")
def country_budget_view(request):
    """Country Budget rollup dashboard view."""
    from apps.core.fy import get_operational_fy
    from apps.activities.models import ActivityScheduleCostLine
    from django.db.models import Sum
    from apps.accounts.models import User
    from apps.fund_requests.models import WeeklyFundRequest
    
    fy = get_operational_fy()
    
    # Base query for this FY
    cost_lines = ActivityScheduleCostLine.objects.filter(fiscal_year=fy)
    
    # Financial state values (Approved, Disbursed, Accounted, Variance)
    wfrs = WeeklyFundRequest.objects.filter(fy=fy)
    
    approved_total = wfrs.exclude(status__in=("draft", "rejected")).aggregate(s=Sum("total_amount"))["s"] or 0
    disbursed_total = wfrs.aggregate(s=Sum("disbursed_amount"))["s"] or 0
    accounted_total = wfrs.aggregate(s=Sum("accounted_amount"))["s"] or 0
    variance_total = disbursed_total - accounted_total
    
    # 1. Weekly activity budget totals
    weekly_totals = cost_lines.values("week_start_date").annotate(total=Sum("amount")).order_by("-week_start_date")[:12]
    
    # 2. Monthly rollups
    monthly_totals = cost_lines.values("month").annotate(total=Sum("amount")).order_by("month")
    month_names = {
        10: "October", 11: "November", 12: "December",
        1: "January", 2: "February", 3: "March",
        4: "April", 5: "May", 6: "June",
        7: "July", 8: "August", 9: "September"
    }
    monthly_rollups = []
    for m in monthly_totals:
        monthly_rollups.append({
            "label": month_names.get(m["month"], f"Month {m['month']}"),
            "total": m["total"] or 0
        })
        
    # 3. Quarterly rollups
    quarterly_totals = cost_lines.values("quarter").annotate(total=Sum("amount")).order_by("quarter")
    quarterly_rollups = []
    for q in quarterly_totals:
        quarterly_rollups.append({
            "label": f"Q{q['quarter']}" if not str(q['quarter']).lower().startswith("q") else str(q['quarter']).upper(),
            "total": q["total"] or 0
        })
        
    # 4. Annual rollup
    annual_rollup = cost_lines.aggregate(total=Sum("amount"))["total"] or 0
    
    # 5. Breakdown by staff
    user_map = {u.id: u.name for u in User.objects.all()}
    staff_totals = cost_lines.values("responsible_user").annotate(total=Sum("amount")).order_by("-total")
    staff_breakdown = []
    for st in staff_totals:
        user_id = st["responsible_user"]
        staff_breakdown.append({
            "name": user_map.get(user_id, f"User {user_id}" if user_id else "Unassigned"),
            "total": st["total"] or 0
        })
        
    # 6. Breakdown by PL (Program Lead)
    from apps.accounts.models import StaffSupervisorAssignment
    pl_breakdown = {}
    assignments = StaffSupervisorAssignment.objects.select_related("supervisor__user", "supervisee__user")
    supervisee_to_pl = {}
    for ass in assignments:
        if ass.supervisee and ass.supervisor:
            supervisee_to_pl[ass.supervisee.user.id] = ass.supervisor.user.name
            
    for cl in cost_lines:
        pl_name = supervisee_to_pl.get(cl.responsible_user, "Other / Direct")
        pl_breakdown[pl_name] = pl_breakdown.get(pl_name, 0) + cl.amount
    pl_rollups = [{"name": name, "total": total} for name, total in sorted(pl_breakdown.items(), key=lambda x: x[1], reverse=True)]
    
    # 7. Breakdown by activity type
    activity_totals = cost_lines.values("activity__activity_type").annotate(total=Sum("amount")).order_by("-total")
    activity_breakdown = []
    for act in activity_totals:
        act_type = act["activity__activity_type"]
        if act_type:
            label = act_type.replace("_", " ").title()
            activity_breakdown.append({
                "label": label,
                "total": act["total"] or 0
            })
            
    # 8. Breakdown by district/region
    district_totals = cost_lines.values("school__district__name").annotate(total=Sum("amount")).order_by("-total")
    district_breakdown = []
    for dt in district_totals:
        name = dt["school__district__name"] or "Regional / Unassigned"
        district_breakdown.append({
            "label": name,
            "total": dt["total"] or 0
        })
        
    # 9. Breakdown by partner
    partner_totals = cost_lines.values("partner__name").annotate(total=Sum("amount")).order_by("-total")
    partner_breakdown = []
    for pt in partner_totals:
        name = pt["partner__name"]
        if name:
            partner_breakdown.append({
                "label": name,
                "total": pt["total"] or 0
            })
            
    # 10. Breakdown by core schools
    school_type_totals = cost_lines.values("school__school_type").annotate(total=Sum("amount")).order_by("-total")
    school_type_breakdown = []
    for st in school_type_totals:
        type_name = st["school__school_type"]
        if type_name:
            label = "Core Schools" if type_name == "core" else "Client Schools" if type_name == "client" else type_name.title()
            school_type_breakdown.append({
                "label": label,
                "total": st["total"] or 0
            })
            
    # 11. Breakdown by project
    project_totals = cost_lines.values("project__name").annotate(total=Sum("amount")).order_by("-total")
    project_breakdown = []
    for pr in project_totals:
        name = pr["project__name"]
        if name:
            project_breakdown.append({
                "label": name,
                "total": pr["total"] or 0
            })

    context = {
        "fy": fy,
        "approved": approved_total,
        "disbursed": disbursed_total,
        "accounted": accounted_total,
        "variance": variance_total,
        
        "weekly_totals": weekly_totals,
        "monthly_rollups": monthly_rollups,
        "quarterly_rollups": quarterly_rollups,
        "annual_rollup": annual_rollup,
        
        "staff_breakdown": staff_breakdown[:10],
        "pl_breakdown": pl_rollups,
        "activity_breakdown": activity_breakdown,
        "district_breakdown": district_breakdown[:10],
        "partner_breakdown": partner_breakdown,
        "school_type_breakdown": school_type_breakdown,
        "project_breakdown": project_breakdown,
    }
    return render(request, "pages/finance/country_budget.html", context)

