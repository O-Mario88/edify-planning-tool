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
    requests_list = list_weekly_requests({"fy": fy}, request.user)
    context = {
        "requests": requests_list,
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
