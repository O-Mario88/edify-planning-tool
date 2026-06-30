from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone

from apps.budget.services import board as get_budget_board
from apps.fund_requests.weekly_service import (
    list_weekly_requests,
    get_weekly_request,
    request_advance,
    disburse as disburse_weekly
)
from apps.core.fy import get_operational_fy

@login_required(login_url="/login")
def monthly_budget_view(request):
    fy = get_operational_fy()
    board_data = get_budget_board(request.user, {"fy": fy})
    context = {
        "board": board_data,
        "fy": fy,
    }
    return render(request, "pages/budgets/monthly.html", context)

@login_required(login_url="/login")
def weekly_fund_requests_view(request):
    fy = get_operational_fy()
    status_tab = request.GET.get("tab", "pending")
    
    all_requests = list_weekly_requests({"fy": fy}, request.user)
    
    # Calculate KPIs
    pending_total = sum(r["totalAmount"] for r in all_requests if r["status"] in ["pending_responsible_confirmation", "pending_pl_approval", "pending_cd_approval"])
    approved_total = sum(r["totalAmount"] for r in all_requests if r["status"] == "confirmed_for_advance")
    
    kpis = {
        "pending_approval": pending_total,
        "approved": approved_total,
        "available_balance": 4000000, # Placeholder until budget service supports user balance
    }
    
    # Filter for active tab
    if status_tab == "pending":
        filtered_requests = [r for r in all_requests if r["status"] in ["pending_responsible_confirmation", "pending_pl_approval", "pending_cd_approval", "not_requested"]]
    elif status_tab == "approved":
        filtered_requests = [r for r in all_requests if r["status"] == "confirmed_for_advance"]
    elif status_tab == "disbursed":
        filtered_requests = [r for r in all_requests if r["status"] in ["disbursed", "accounted", "self_funded"]]
    elif status_tab == "rejected":
        filtered_requests = [r for r in all_requests if r["status"] == "rejected"]
    else:
        filtered_requests = all_requests
        
    context = {
        "requests": filtered_requests,
        "kpis": kpis,
        "active_tab": status_tab,
        "fy": fy,
    }
    return render(request, "pages/fund_requests/weekly.html", context)

@login_required(login_url="/login")
def weekly_fund_request_detail_view(request, request_id):
    req = get_weekly_request(request_id, request.user)
    context = {
        "req": req,
    }
    return render(request, "pages/fund_requests/detail.html", context)

@login_required(login_url="/login")
def weekly_fund_request_confirm_action(request, request_id):
    if request.method == "POST":
        try:
            request_advance(request_id, request.user)
            messages.success(request, "Weekly fund request confirmed for advance successfully.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
    return redirect(f"/fund-requests/weekly/{request_id}")

@login_required(login_url="/login")
def weekly_fund_request_disburse_action(request, request_id):
    if request.user.active_role != "ProgramAccountant":
        messages.error(request, "Only the Program Accountant can disburse fund requests.")
        return redirect(f"/fund-requests/weekly/{request_id}")

    if request.method == "POST":
        amount = request.POST.get("amount", "")
        method = request.POST.get("method", "mobile_money")
        reference = request.POST.get("reference", "").strip()
        
        payload = {
            "method": method,
            "reference": reference,
        }
        if amount:
            payload["amount"] = int(amount)

        try:
            disburse_weekly(request_id, payload, request.user)
            messages.success(request, "Weekly fund request disbursed successfully.")
        except Exception as e:
            messages.error(request, f"Error disbursing funds: {e}")
            
    return redirect(f"/fund-requests/weekly/{request_id}")
