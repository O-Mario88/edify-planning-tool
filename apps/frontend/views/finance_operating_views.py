from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.db import models
from django.utils import timezone

from apps.core.permissions import require_page_permission
from apps.activities.models import Activity
from apps.fund_requests.models import (
    ReimbursementClaim,
    AccountabilityRecord,
    FinanceReturn,
    VarianceReview,
    FinanceAuditLog,
    WeeklyFundRequest
)
from apps.fund_requests.finance_services import (
    FinanceBlockedReasonService,
    AdvanceDisbursementService,
    PartnerPaymentService,
    ReimbursementService,
    NetSuiteExpenseService
)

def _ugx_compact(val):
    """Format an integer UGX amount compactly (e.g. UGX 2.4B / 186.4M / 65K)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val:,}"


@require_page_permission("disbursements")
def accountant_dashboard_view(request):
    """Main Accountant Dashboard / Finance Command Center."""
    import json
    from apps.core.fy import get_operational_fy
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.accounts.models import User, StaffProfile

    fy = get_operational_fy()

    # 1. Real database queries for KPIs (WeeklyFundRequest lifecycle:
    # pending_responsible_confirmation -> confirmed_for_advance -> disbursed/paid/closed,
    # plus self_funded / not_requested / cancelled side paths).
    CONFIRMED_ONWARD = [
        "confirmed_for_advance", "disbursed", "paid", "closed", "cleared",
        "self_funded", "self_funded_pending_reimbursement",
    ]
    total_approved_db = WeeklyFundRequest.objects.filter(
        fy=fy, status__in=CONFIRMED_ONWARD
    ).aggregate(Sum("total_amount"))["total_amount__sum"] or 0

    total_disbursed_db = WeeklyFundRequest.objects.filter(fy=fy).aggregate(Sum("disbursed_amount"))["disbursed_amount__sum"] or 0

    # Let's query all WeeklyFundRequests
    wfrs_db = list(WeeklyFundRequest.objects.all().order_by("-week_start_date"))
    user_ids = [w.responsible_user for w in wfrs_db]
    users_by_id = {u.id: u for u in User.objects.filter(id__in=user_ids)}
    profiles_by_id = {p.user_id: p for p in StaffProfile.objects.filter(user_id__in=user_ids)}

    queue_items = []
    
    # Map real DB requests to queue items
    for w in wfrs_db:
        user_obj = users_by_id.get(w.responsible_user)
        profile_obj = profiles_by_id.get(w.responsible_user)
        user_name = user_obj.name if user_obj else "System User"
        role_name = w.responsible_role or "CCEO"
        
        # Serialize lines
        lines_list = []
        for l in w.lines.all():
            lines_list.append({
                "category": l.description or l.line_item_type,
                "quantity": l.quantity,
                "unit_cost": l.unit_cost,
                "total": l.total_cost
            })
            
        status_display = w.status.replace("_", " ").title()
        status_class = "bg-amber-50 text-amber-700 border-amber-250"
        if w.status == "disbursed":
            status_class = "bg-blue-50 text-blue-700 border-blue-250"
        elif w.status == "accounted":
            status_class = "bg-emerald-50 text-emerald-700 border-emerald-250"
        elif w.status == "returned_by_accountant":
            status_class = "bg-rose-50 text-rose-700 border-rose-250"

        queue_items.append({
            "id": w.id,
            "user_name": user_name,
            "role": role_name,
            "region": profile_obj.portfolio if profile_obj else "Central",
            "requested": w.total_amount,
            "approved": w.total_amount,
            "disbursed": w.disbursed_amount or 0,
            "balance": w.total_amount - (w.disbursed_amount or 0),
            "status": status_display,
            "status_class": status_class,
            "week_start": w.week_start_date.strftime("%d %b %Y"),
            "week_end": w.week_end_date.strftime("%d %b %Y"),
            "lines": lines_list,
            "pl_approved": True,
            "cd_approved": w.status in ["approved_by_cd", "sent_to_accountant", "disbursed", "accounted"],
            "rvp_approved": w.status in ["disbursed", "accounted"],
            "finance_completed": w.status in ["disbursed", "accounted"],
            "disbursed_completed": w.status in ["disbursed", "accounted"]
        })

    # KPIs are computed from the live fund-request tables only — no mock rows.
    fy_qs = WeeklyFundRequest.objects.filter(fy=fy)
    in_approval_statuses = ["pending_responsible_confirmation"]
    pending_disb_qs = fy_qs.filter(status="confirmed_for_advance")
    awaiting_qs = fy_qs.filter(status__in=in_approval_statuses)
    disbursed_qs = fy_qs.filter(status__in=["disbursed", "paid", "closed", "cleared"])
    accounted_count = fy_qs.filter(accounted_amount__isnull=False).count()
    disbursed_count = disbursed_qs.count()

    pending_disb_amount = sum(
        (w.total_amount or 0) - (w.disbursed_amount or 0) for w in pending_disb_qs
    )
    awaiting_amount = awaiting_qs.aggregate(Sum("total_amount"))["total_amount__sum"] or 0
    recon_rate = round(accounted_count / disbursed_count * 100) if disbursed_count else 0
    budget_util = round(total_disbursed_db / total_approved_db * 100) if total_approved_db else 0

    all_funds = queue_items
    all_funds_json = json.dumps(all_funds)

    # ── Right-rail + bottom-row live rollups ─────────────────────────────
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
    month_qs = fy_qs.filter(week_start_date__gte=month_start)

    def _sum(qs, field="total_amount"):
        return qs.aggregate(v=Sum(field))["v"] or 0

    month_overview = {
        "waiting": _ugx_compact(_sum(month_qs.filter(status="pending_responsible_confirmation"))),
        "pending_disb": _ugx_compact(sum(
            (w.total_amount or 0) - (w.disbursed_amount or 0)
            for w in month_qs.filter(status="confirmed_for_advance")
        )),
        "disbursed": _ugx_compact(_sum(month_qs, "disbursed_amount")),
        "accounted": _ugx_compact(_sum(month_qs.filter(accounted_amount__isnull=False), "accounted_amount")),
    }

    # Disbursement status donut over the FY's requests (share of request count)
    n_all = fy_qs.count()
    n_waiting = fy_qs.filter(status="pending_responsible_confirmation").count()
    n_confirmed = pending_disb_qs.count()
    n_disbursed = disbursed_qs.count()
    n_other = max(0, n_all - n_waiting - n_confirmed - n_disbursed)

    def _share(n):
        return round(n / n_all * 100) if n_all else 0

    disb_donut = {
        "total": _ugx_compact(_sum(fy_qs)),
        "confirmed": _share(n_confirmed),
        "waiting": _share(n_waiting),
        "disbursed": _share(n_disbursed),
        "other": _share(n_other),
        "waiting_offset": -_share(n_confirmed),
        "disbursed_offset": -(_share(n_confirmed) + _share(n_waiting)),
        "other_offset": -(_share(n_confirmed) + _share(n_waiting) + _share(n_disbursed)),
    }

    recent_disbursements = []
    for w in fy_qs.filter(status__in=["disbursed", "paid", "closed", "cleared"]).order_by("-updated_at")[:4]:
        u = users_by_id.get(w.responsible_user)
        p = profiles_by_id.get(w.responsible_user)
        recent_disbursements.append({
            "name": u.name if u else "—",
            "initials": (u.name[:2].upper() if u and u.name else "—"),
            "region": p.portfolio if p and p.portfolio else "—",
            "when": w.updated_at.strftime("%d %b, %I:%M %p") if w.updated_at else "—",
            "amount": _ugx_compact(w.disbursed_amount or w.total_amount),
            "status": w.status.replace("_", " ").title(),
        })

    awaiting_accountability_qs = fy_qs.filter(status__in=["disbursed", "paid"], accounted_amount__isnull=True)
    recon = {
        "awaiting_receipts": awaiting_accountability_qs.count(),
        "partially_accounted": fy_qs.filter(accounted_amount__isnull=False).exclude(accounted_amount=models.F("disbursed_amount")).count(),
        "closed": fy_qs.filter(status__in=["closed", "cleared"]).count(),
        "pending_confirmation": n_waiting,
    }
    recon_rows = []
    now_ts = timezone.now()
    for w in awaiting_accountability_qs.order_by("updated_at")[:3]:
        u = users_by_id.get(w.responsible_user)
        p = profiles_by_id.get(w.responsible_user)
        days = max(0, (now_ts - w.updated_at).days) if w.updated_at else 0
        recon_rows.append({
            "who": f"{u.name if u else '—'} • {p.portfolio if p and p.portfolio else '—'}",
            "amount": f"{(w.disbursed_amount or w.total_amount):,}",
            "days": days,
        })

    cash = {
        "confirmed": _ugx_compact(total_approved_db),
        "committed": _ugx_compact(pending_disb_amount),
        "pending": _ugx_compact(awaiting_amount),
        "disbursed": _ugx_compact(total_disbursed_db),
        "util": budget_util,
    }

    context = {
        "month_overview": month_overview,
        "disb_donut": disb_donut,
        "recent_disbursements": recent_disbursements,
        "recon": recon,
        "recon_rows": recon_rows,
        "cash": cash,
        "kpis": {
            "total_approved": _ugx_compact(total_approved_db),
            "total_disbursed": _ugx_compact(total_disbursed_db),
            "pending_disb": _ugx_compact(pending_disb_amount),
            "pending_disb_count": pending_disb_qs.count(),
            "awaiting_approval": _ugx_compact(awaiting_amount),
            "awaiting_count": awaiting_qs.count(),
            "disbursed_count": disbursed_count,
            "approved_count": fy_qs.filter(status__in=CONFIRMED_ONWARD).count(),
            "recon_rate": f"{recon_rate}%",
            "budget_util": f"{budget_util}%",
            "budget_util_pct": budget_util,
            "disbursed_raw": _ugx_compact(total_disbursed_db),
        },
        "all_funds": all_funds,
        "all_funds_json": all_funds_json,
        "fy": fy,
    }
    return render(request, "pages/accounts/dashboard.html", context)


@require_page_permission("disbursements")
def ready_for_advance_view(request):
    """Ready for Advance Disbursement Page."""
    advances = Activity.objects.filter(deleted_at__isnull=True, payment_status="pending", delivery_type="staff").select_related("school", "cluster")
    
    context = {
        "advances": advances,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"]
    }
    return render(request, "pages/accounts/ready_for_advance.html", context)


@require_page_permission("disbursements")
def mark_disbursed_action(request, activity_id):
    """POST to record a disbursement in the advance drawer."""
    activity = get_object_or_404(Activity, id=activity_id)
    
    if request.method == "POST":
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_disbursed", 0))
            AdvanceDisbursementService.disburse_advance(activity, amount, method, reference, request.user.user_id, notes)
            messages.success(request, f"Advance of {amount} UGX disbursed for Activity #{activity.id[:8]} successfully.")
        except Exception as e:
            messages.error(request, f"Disbursement failed: {e}")
            
    return redirect("/accounts/advances/")


@require_page_permission("disbursements")
def partner_payments_view(request):
    """Partner Payment Queue."""
    payments = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        status="ia_verified",
        payment_status__in=["pending", "ia_confirmed"]
    ).select_related("school", "cluster")
    
    context = {
        "payments": payments,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque"]
    }
    return render(request, "pages/accounts/partner_payments.html", context)


@require_page_permission("disbursements")
def pay_partner_action(request, activity_id):
    """POST to pay partner."""
    activity = get_object_or_404(Activity, id=activity_id)
    
    if request.method == "POST":
        partner_name = request.POST.get("partner_name", "").strip()
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_paid", 0))
            PartnerPaymentService.pay_partner(activity, partner_name, amount, method, reference, request.user.user_id, notes)
            messages.success(request, f"Partner payment of {amount} UGX processed successfully.")
        except Exception as e:
            messages.error(request, f"Partner payment failed: {e}")
            
    return redirect("/accounts/partner-payments/")


@require_page_permission("disbursements")
def reimbursements_view(request):
    """Reimbursement Queue."""
    claims = ReimbursementClaim.objects.filter(status="pending").select_related("activity", "activity__school")
    
    context = {
        "claims": claims,
        "methods": ["Mobile Money", "Bank Transfer"]
    }
    return render(request, "pages/accounts/reimbursements.html", context)


@require_page_permission("disbursements")
def pay_reimbursement_action(request, claim_id):
    """POST to disburse reimbursement claim."""
    claim = get_object_or_404(ReimbursementClaim, id=claim_id)
    
    if request.method == "POST":
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        
        try:
            ReimbursementService.disburse_reimbursement(claim, method, reference, request.user.user_id)
            messages.success(request, f"Reimbursement of {claim.reimbursement_amount} UGX paid successfully.")
        except Exception as e:
            messages.error(request, f"Reimbursement payout failed: {e}")
            
    return redirect("/accounts/reimbursements/")


@require_page_permission("disbursements")
def accountability_view(request):
    """Accountability Pending Page."""
    records = AccountabilityRecord.objects.all().select_related("activity", "activity__school").order_by("-submitted_at")
    
    context = {
        "records": records
    }
    return render(request, "pages/accounts/accountability.html", context)


@require_page_permission("disbursements")
def netsuite_id_action(request, activity_id):
    """POST to record NetSuite Expense ID."""
    activity = get_object_or_404(Activity, id=activity_id)
    
    if request.method == "POST":
        netsuite_id = request.POST.get("netsuite_expense_id", "").strip()
        expense_date = request.POST.get("expense_date")
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_entered", 0))
            NetSuiteExpenseService.enter_netsuite_id(activity, netsuite_id, amount, expense_date, request.user.user_id, notes)
            messages.success(request, f"NetSuite ID {netsuite_id} entered for Activity #{activity.id[:8]} successfully.")
        except Exception as e:
            messages.error(request, f"NetSuite ID entry failed: {e}")
            
    return redirect("/accounts/accountability/")


@require_page_permission("disbursements")
def blocked_view(request):
    """Finance Blocked Page."""
    activities = Activity.objects.filter(deleted_at__isnull=True).prefetch_related("schedule_cost_lines").select_related("school")
    
    # Fetch all active evidence activity IDs in one query
    from apps.evidence.models import EvidenceRecord
    activity_ids = [a.id for a in activities]
    evidence_activity_ids = set(
        EvidenceRecord.objects.filter(activity_id__in=activity_ids, quarantined=False)
        .values_list("activity_id", flat=True)
    )
    
    blocked_list = []
    for a in activities:
        # Check prefetch cache for budget lines
        has_budget = len(a.schedule_cost_lines.all()) > 0
        has_ev = a.id in evidence_activity_ids
        
        reasons = FinanceBlockedReasonService.get_blocked_reasons(
            a, has_evidence=has_ev, has_budget_lines=has_budget
        )
        if reasons:
            blocked_list.append({
                "activity": a,
                "reasons": reasons,
                "reasons_label": ", ".join(reasons)
            })
            
    context = {
        "blocked": blocked_list
    }
    return render(request, "pages/accounts/blocked.html", context)


@require_page_permission("disbursements")
def variance_review_view(request):
    """Variance Review Page."""
    reviews = VarianceReview.objects.filter(status="pending").select_related("activity", "activity__school")
    
    context = {
        "reviews": reviews
    }
    return render(request, "pages/accounts/variance_review.html", context)


@require_page_permission("disbursements")
def returned_view(request):
    """Returned Finance Items Page."""
    returns = FinanceReturn.objects.filter(status="pending").select_related("activity", "activity__school")
    
    context = {
        "returns": returns
    }
    return render(request, "pages/accounts/returned.html", context)


@require_page_permission("disbursements")
def cleared_view(request):
    """Cleared / Closed Finance Ledger."""
    closed_activities = Activity.objects.filter(deleted_at__isnull=True, status="closed").select_related("school", "cluster").order_by("-updated_at")
    
    context = {
        "closed": closed_activities
    }
    return render(request, "pages/accounts/cleared.html", context)


@require_page_permission("disbursements")
def activity_finance_detail_view(request, activity_id):
    """One complete finance view for a single activity."""
    a = get_object_or_404(Activity, id=activity_id)
    costs = a.schedule_cost_lines.all()
    disbursements = a.disbursements.all()
    partner_payments = a.partner_payments.all()
    reimbursements = a.reimbursement_claims.all()
    accountability = a.accountability_records.all()
    netsuite = a.netsuite_expenses.all()
    audit_logs = a.finance_audit_logs.all().order_by("-timestamp")
    blocked_reasons = FinanceBlockedReasonService.get_blocked_reasons(a)
    
    context = {
        "act": a,
        "costs": costs,
        "disbursements": disbursements,
        "partner_payments": partner_payments,
        "reimbursements": reimbursements,
        "accountability": accountability,
        "netsuite": netsuite,
        "audit_logs": audit_logs,
        "blocked_reasons": blocked_reasons,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"]
    }
    return render(request, "pages/accounts/activity_finance_detail.html", context)


@require_page_permission("disbursements")
def batch_payments_view(request):
    """Batch Payments Page."""
    advances = Activity.objects.filter(deleted_at__isnull=True, payment_status="pending", delivery_type="staff")
    partners = Activity.objects.filter(deleted_at__isnull=True, delivery_type="partner", status="ia_verified", payment_status__in=["pending", "ia_confirmed"])
    reimbursements = ReimbursementClaim.objects.filter(status="pending")
    
    context = {
        "advances": advances,
        "partners": partners,
        "reimbursements": reimbursements
    }
    return render(request, "pages/accounts/batch_payments.html", context)


@require_page_permission("disbursements")
def approval_history_view(request):
    """Finance Approval History Page."""
    requests = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    
    context = {
        "requests": requests
    }
    return render(request, "pages/accounts/approval_history.html", context)


@require_page_permission("disbursements")
def audit_log_view(request):
    """Finance Audit Log Page."""
    logs = FinanceAuditLog.objects.all().select_related("activity").order_by("-timestamp")
    
    context = {
        "logs": logs
    }
    return render(request, "pages/accounts/audit_log.html", context)


@require_page_permission("disbursements")
def monthly_request_view(request):
    """Monthly Country Finance Request Page."""
    # Gather sum of all cost lines grouped by type
    budget_lines = Activity.objects.filter(deleted_at__isnull=True, fy="FY25").aggregate(
        total=Sum("schedule_cost_lines__amount")
    )
    
    context = {
        "total_budget": budget_lines["total"] or 0,
        "monthly_allocation": "210,000,000 UGX",
        "quarter": "Q2"
    }
    return render(request, "pages/accounts/monthly_request.html", context)


@require_page_permission("disbursements")
def weekly_requests_view(request):
    """Weekly Fund Request Review Page."""
    requests = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    
    context = {
        "requests": requests
    }
    return render(request, "pages/accounts/weekly_requests.html", context)
