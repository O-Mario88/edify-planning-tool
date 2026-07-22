from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum

from apps.core.permissions import require_export_permission, require_page_permission
from apps.activities.models import Activity
from apps.fund_requests.models import (
    AdvanceRequestStatus,
    ReimbursementClaim,
    AccountabilityRecord,
    FinanceReturn,
    VarianceReview,
    FinanceAuditLog,
    WeeklyFundRequest,
)
from apps.fund_requests.finance_services import (
    PARTNER_PAID_STATUSES,
    PARTNER_PAYABLE_STATUSES,
    FinanceBlockedReasonService,
    PartnerPaymentService,
)
from apps.fund_requests.disbursement_dashboard_service import weekly_status_buckets
from apps.analytics.platform_engine import finance_health


def format_ugx_compact(val):
    """Compact UGX formatting helper (same as apps/frontend/views/budget_views.py)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val}"


@require_page_permission("disbursements")
def accountant_dashboard_view(request):
    """Main Accountant Dashboard / Finance Command Center."""
    from datetime import date
    from apps.core.fy import get_operational_fy
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.accounts.models import User, StaffProfile
    from apps.geography.models import District

    fy = get_operational_fy()
    fy_qs = WeeklyFundRequest.objects.filter(fy=fy)

    # 1. Real database queries for KPIs — bucketed through the same canonical
    # status classifier the Disbursement Dashboard uses (weekly_status_buckets)
    # so the two "current budget status" surfaces can never diverge. (The old
    # version filtered on payment/status literals like "approved_by_cd",
    # "sent_to_accountant" and "accountability_pending" that WeeklyFundRequest
    # never actually writes — see weekly_service.py — which silently excluded
    # "confirmed_for_advance" advances from the approved-funds denominator and
    # skewed Budget Utilization.)
    fy_wfrs = list(fy_qs)
    fy_buckets = weekly_status_buckets(fy_wfrs)

    def _bucket_sum(*labels):
        return sum(w.total_amount for w in fy_wfrs if fy_buckets[w.id] in labels)

    def _bucket_count(*labels):
        return sum(1 for w in fy_wfrs if fy_buckets[w.id] in labels)

    total_disbursed_db = (
        fy_qs.aggregate(Sum("disbursed_amount"))["disbursed_amount__sum"] or 0
    )
    total_accounted_db = (
        fy_qs.aggregate(Sum("accounted_amount"))["accounted_amount__sum"] or 0
    )
    total_returned_db = (
        fy_qs.aggregate(Sum("returned_amount"))["returned_amount__sum"] or 0
    )

    # Approved but not yet disbursed
    pending_disb_sum = _bucket_sum("Pending Disbursement")
    pending_disb_count = _bucket_count("Pending Disbursement")

    # Still travelling up the approval chain
    awaiting_sum = _bucket_sum("Pending Approval")
    awaiting_count = _bucket_count("Pending Approval")

    returned_sum = _bucket_sum("Returned")

    # Every request that has ever been disbursed (still outstanding
    # reconciliation or already closed) vs. the reconciled subset.
    disbursed_count = _bucket_count("Disbursed", "Awaiting Reconciliation", "Closed")
    accounted_count = _bucket_count("Closed")

    # "Approved" = passed approval and disbursable-or-beyond — the
    # denominator for the Budget Utilization ratio.
    total_approved_db = _bucket_sum(
        "Pending Disbursement", "Disbursed", "Awaiting Reconciliation", "Closed"
    )
    finance_analytics = finance_health(
        approved=total_approved_db,
        disbursed=total_disbursed_db,
        accounted=total_accounted_db,
        returned=total_returned_db,
        reconciled_count=accounted_count,
        disbursed_count=disbursed_count,
        record_count=len(fy_wfrs),
    )
    recon_rate = round(finance_analytics["reconciliation"]["rate"])
    budget_util = round(finance_analytics["utilization"]["utilization_rate"] or 0)

    # Keep the visible queue aligned with the FY shown in the header and KPIs.
    wfrs_db = list(fy_qs.prefetch_related("lines").order_by("-week_start_date"))
    user_ids = [w.responsible_user for w in wfrs_db]
    users_by_id = {u.id: u for u in User.objects.filter(id__in=user_ids)}
    profiles_by_id = {
        p.user_id: p for p in StaffProfile.objects.filter(user_id__in=user_ids)
    }
    district_ids = {
        p.primary_district_id for p in profiles_by_id.values() if p.primary_district_id
    }
    district_names_by_id = {
        d.id: d.name for d in District.objects.filter(id__in=district_ids)
    }

    queue_items = []

    # Map real DB requests to queue items
    for w in wfrs_db:
        user_obj = users_by_id.get(w.responsible_user)
        profile_obj = profiles_by_id.get(w.responsible_user)
        user_name = user_obj.name if user_obj else "System User"
        role_name = w.responsible_role or "CCEO"

        # Serialize lines
        lines_list = []
        for line in w.lines.all():
            lines_list.append(
                {
                    "category": line.description or line.line_item_type,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "total": line.total_cost,
                }
            )

        status_display = w.status.replace("_", " ").title()
        status_class = "bg-amber-50 text-amber-700 border-amber-250"
        if w.status == "disbursed":
            status_class = "edify-primary-soft edify-primary-text edify-primary-border"
        elif w.status == "accounted":
            status_class = "bg-emerald-50 text-emerald-700 border-emerald-250"
        elif w.status == "returned_by_accountant":
            status_class = "bg-rose-50 text-rose-700 border-rose-250"

        district_name = "—"
        if profile_obj and profile_obj.primary_district_id:
            district_name = district_names_by_id.get(
                profile_obj.primary_district_id, "—"
            )

        queue_items.append(
            {
                "id": w.id,
                "user_name": user_name,
                "role": role_name,
                "region": district_name,
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
                "cd_approved": w.status
                in ["approved_by_cd", "sent_to_accountant", "disbursed", "accounted"],
                "rvp_approved": w.status in ["disbursed", "accounted"],
                "finance_completed": w.status in ["disbursed", "accounted"],
                "disbursed_completed": w.status in ["disbursed", "accounted"],
            }
        )

    all_funds = queue_items

    # This Month Overview (current calendar month, by week start date) — same
    # bucket classifier as the FY-wide KPIs above, scoped to this month's rows.
    today = date.today()
    month_qs = fy_qs.filter(
        week_start_date__year=today.year, week_start_date__month=today.month
    )
    month_wfrs = list(month_qs)
    month_buckets = weekly_status_buckets(month_wfrs)

    def _month_sum(*labels):
        return sum(w.total_amount for w in month_wfrs if month_buckets[w.id] in labels)

    month_overview = {
        "waiting_for_approval": format_ugx_compact(_month_sum("Pending Approval")),
        "returned": format_ugx_compact(_month_sum("Returned")),
        "approved_not_disbursed": format_ugx_compact(
            _month_sum("Pending Disbursement")
        ),
        "disbursed": format_ugx_compact(
            month_qs.aggregate(Sum("disbursed_amount"))["disbursed_amount__sum"] or 0
        ),
        "reconciled": format_ugx_compact(
            month_qs.aggregate(Sum("accounted_amount"))["accounted_amount__sum"] or 0
        ),
    }

    # Disbursement Status donut (share of FY value per stage)
    donut_parts = {
        "approved": pending_disb_sum,
        "pending": awaiting_sum,
        "disbursed": total_disbursed_db,
        "returned": returned_sum,
    }
    donut_total = sum(donut_parts.values())
    donut = {"total": donut_total, "total_compact": format_ugx_compact(donut_total)}
    offset = 0.0
    for key, val in donut_parts.items():
        pct = round(val * 100 / donut_total, 1) if donut_total else 0
        donut[f"{key}_pct"] = pct
        donut[f"{key}_offset"] = round(offset, 1)
        offset += pct

    # Recent disbursement activity (latest real disbursements)
    recent_activity = []
    for w in sorted(
        [w for w in wfrs_db if w.disbursed_at],
        key=lambda w: w.disbursed_at,
        reverse=True,
    )[:4]:
        user_obj = users_by_id.get(w.responsible_user)
        profile_obj = profiles_by_id.get(w.responsible_user)
        district_name = "—"
        if profile_obj and profile_obj.primary_district_id:
            district_name = district_names_by_id.get(
                profile_obj.primary_district_id, "—"
            )
        recent_activity.append(
            {
                "name": user_obj.name if user_obj else "System User",
                "region": district_name,
                "when": w.disbursed_at.strftime("%d %b %Y, %I:%M %p"),
                "amount": format_ugx_compact(w.disbursed_amount or 0),
            }
        )

    # Reconciliation & proof tracker (disbursed, awaiting accountability)
    recon_pending = []
    for w in wfrs_db:
        if w.status in ["disbursed", "accountability_pending"] and w.fy == fy:
            user_obj = users_by_id.get(w.responsible_user)
            profile_obj = profiles_by_id.get(w.responsible_user)
            district_name = "—"
            if profile_obj and profile_obj.primary_district_id:
                district_name = district_names_by_id.get(
                    profile_obj.primary_district_id, "—"
                )
            days_outstanding = (
                (today - w.disbursed_at.date()).days if w.disbursed_at else 0
            )
            recon_pending.append(
                {
                    "name": user_obj.name if user_obj else "System User",
                    "region": district_name,
                    "amount": w.disbursed_amount or w.total_amount,
                    "days": days_outstanding,
                }
            )
    recon_pending = sorted(recon_pending, key=lambda r: r["days"], reverse=True)[:5]
    recon_stats = {
        "awaiting_receipts": len(
            [
                w
                for w in wfrs_db
                if w.fy == fy and w.status in ["disbursed", "accountability_pending"]
            ]
        ),
        "closed": accounted_count,
    }

    context = {
        "kpis": {
            "total_approved": format_ugx_compact(total_approved_db),
            "total_disbursed": format_ugx_compact(total_disbursed_db),
            "pending_disb": format_ugx_compact(pending_disb_sum),
            "pending_disb_count": pending_disb_count,
            "awaiting_approval": format_ugx_compact(awaiting_sum),
            "awaiting_count": awaiting_count,
            "disbursed_count": disbursed_count,
            "accounted_count": accounted_count,
            "recon_rate": f"{recon_rate}%",
            "budget_util": f"{budget_util}%",
            "budget_util_pct": budget_util,
        },
        "all_funds": all_funds,
        "month_overview": month_overview,
        "donut": donut,
        "recent_activity": recent_activity,
        "recon_pending": recon_pending,
        "recon_stats": recon_stats,
        "analytics": finance_analytics,
        "fy": fy,
    }
    context["topbar_search"] = {
        "placeholder": "Search funds, people, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/accounts",
        "hx_target": "#accounts-root",
        "hx_trigger": "keyup changed delay:250ms, search",
    }
    return render(request, "pages/accounts/dashboard.html", context)


@require_page_permission("disbursements")
def ready_for_advance_view(request):
    """Ready for Advance Disbursement Page.

    Queue criterion mirrors the gate the page's own Disburse button enforces
    (AdvanceDisbursementService.disburse_advance requires a responsible-user-
    confirmed AdvanceRequest): everything listed here is actually
    disbursable. The old payment_status="pending" filter matched a value no
    code ever writes — this queue was permanently empty."""
    advances = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="staff",
            advance_requests__status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )
        .exclude(payment_status__in=PARTNER_PAID_STATUSES)
        .select_related("school", "cluster")
        .distinct()
    )

    context = {
        "advances": advances,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"],
    }
    return render(request, "pages/accounts/ready_for_advance.html", context)


@require_page_permission("disbursements")
def mark_disbursed_action(request, activity_id):
    """RETIRED (2026-07-15 finance-unification mandate). This activity-level
    disburse path shared the same AdvanceRequest rows the canonical weekly/
    advance disburse queues (apps.fund_requests.weekly_service.disburse /
    advance_service.disburse) read from — two live entry points onto the
    same money was a genuine double-disbursement hazard the mandate
    explicitly forbids ("no parallel accountability workflows"). Disbursement
    now happens exclusively through /disbursements
    (disbursement_dashboard_service) and the weekly advance queue. This route
    is kept (rather than 404ing) only so old bookmarks/links redirect
    cleanly; it performs no mutation."""
    messages.info(
        request,
        "This disbursement path has been retired — use the Disbursement "
        "Dashboard to disburse advances.",
    )
    return redirect("/disbursements")


@require_page_permission("disbursements")
def partner_payments_view(request):
    """Partner Payment Queue."""
    # "none" covers activities verified through the live IA path before it
    # started stamping ia_confirmed (an ia_verified partner activity is by
    # definition awaiting payment); "pending" was never a real
    # PaymentStatus value and matched nothing.
    payments = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        status="ia_verified",
        payment_status__in=PARTNER_PAYABLE_STATUSES,
    ).select_related("school", "cluster")

    context = {
        "payments": payments,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque"],
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
        netsuite_id = request.POST.get("netsuite_expense_id", "").strip()

        try:
            amount = int(request.POST.get("amount_paid", 0))
            PartnerPaymentService.pay_partner(
                activity,
                partner_name,
                amount,
                method,
                reference,
                request.user.user_id,
                notes,
                netsuite_id=netsuite_id,
            )
            messages.success(
                request, f"Partner payment of {amount} UGX processed successfully."
            )
        except Exception as e:
            messages.error(request, f"Partner payment failed: {e}")

    return redirect("/accounts/partner-payments/")


@require_page_permission("disbursements")
def budget_amendments_view(request):
    """Accountant review queue for locked-activity budget amendments (§4.5)."""
    from apps.budget.models import BudgetAmendment

    amendments = BudgetAmendment.objects.select_related(
        "activity", "activity__school"
    ).order_by("-created_at")[:100]
    return render(
        request,
        "pages/accounts/budget_amendments.html",
        {"amendments": amendments},
    )


@require_page_permission("disbursements")
def budget_amendment_action(request, amendment_id):
    """POST approve/return/reject on a submitted amendment."""
    from apps.budget import amendment_service

    if request.method == "POST":
        verb = request.POST.get("action")
        note = {"note": request.POST.get("note", "").strip()}
        try:
            if verb == "approve":
                amendment_service.approve_amendment(amendment_id, note, request.user)
                messages.success(request, "Amendment approved and applied.")
            elif verb == "return":
                amendment_service.return_amendment(amendment_id, note, request.user)
                messages.info(request, "Amendment returned to the requester.")
            elif verb == "reject":
                amendment_service.reject_amendment(amendment_id, note, request.user)
                messages.info(request, "Amendment rejected.")
            else:
                messages.error(request, "Unknown amendment action.")
        except Exception as exc:
            messages.error(request, f"Amendment action failed: {exc}")
    return redirect("/accounts/budget-amendments")


@require_page_permission("disbursements")
def reimbursements_view(request):
    """Reimbursement Queue."""
    claims = ReimbursementClaim.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )

    context = {"claims": claims, "methods": ["Mobile Money", "Bank Transfer"]}
    return render(request, "pages/accounts/reimbursements.html", context)


@require_page_permission("disbursements")
def pay_reimbursement_action(request, claim_id):
    """RETIRED (ecosystem audit). This legacy System-A payout closed the
    activity directly (finance_services.disburse_reimbursement sets
    status="closed"), bypassing the canonical ActivityClosureService nine-check
    gate. No live workflow creates ReimbursementClaim rows any more —
    self-funded and over-spend reimbursements flow through the advance
    accountability queue (advance_service.reimburse), which respects closure.
    Kept as a redirect so old bookmarks fail safely; performs no mutation."""
    get_object_or_404(ReimbursementClaim, id=claim_id)
    messages.info(
        request,
        "This legacy payout path is retired. Reimbursements are paid from the "
        "advance accountability queue, which keeps closure checks intact.",
    )
    return redirect("/accounts/reimbursements/")


@require_page_permission("disbursements")
def accountability_view(request):
    """Accountability Pending Page."""
    records = (
        AccountabilityRecord.objects.all()
        .select_related("activity", "activity__school")
        .order_by("-submitted_at")
    )

    context = {"records": records}
    return render(request, "pages/accounts/accountability.html", context)


@require_page_permission("disbursements")
def netsuite_id_action(request, activity_id):
    """RETIRED (2026-07-15 finance-unification mandate). Letting the
    Accountant type the NetSuite Expense ID here directly contradicted the
    canonical rule: the RESPONSIBLE EMPLOYEE completes accountability in
    NetSuite and enters the resulting ID; the Accountant only verifies it
    (apps.fund_requests.advance_service.submit_accountability /
    approve_accountability). Kept as a redirect, not a 404, for old
    bookmarks/links; it performs no mutation."""
    messages.info(
        request,
        "Accountants no longer enter NetSuite IDs directly — the responsible "
        "employee submits accountability with their NetSuite Expense ID, and "
        "the Accountant reviews it from the Disbursement Dashboard.",
    )
    return redirect("/disbursements")


@require_page_permission("disbursements")
def blocked_view(request):
    """Finance Blocked Page."""
    activities = (
        Activity.objects.filter(deleted_at__isnull=True)
        .prefetch_related("schedule_cost_lines")
        .select_related("school")
    )

    # Fetch all active evidence activity IDs in one query
    from apps.evidence.models import EvidenceRecord

    activity_ids = [a.id for a in activities]
    evidence_activity_ids = set(
        EvidenceRecord.objects.filter(
            activity_id__in=activity_ids, quarantined=False
        ).values_list("activity_id", flat=True)
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
            blocked_list.append(
                {"activity": a, "reasons": reasons, "reasons_label": ", ".join(reasons)}
            )

    context = {"blocked": blocked_list}
    return render(request, "pages/accounts/blocked.html", context)


@require_page_permission("disbursements")
def variance_review_view(request):
    """Variance Review Page."""
    reviews = VarianceReview.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )

    context = {"reviews": reviews}
    return render(request, "pages/accounts/variance_review.html", context)


@require_page_permission("disbursements")
def returned_view(request):
    """Returned Finance Items Page."""
    returns = FinanceReturn.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )

    context = {"returns": returns}
    return render(request, "pages/accounts/returned.html", context)


@require_page_permission("disbursements")
def cleared_view(request):
    """Cleared / Closed Finance Ledger."""
    closed_activities = list(
        Activity.objects.filter(deleted_at__isnull=True, status="closed")
        .select_related("school", "cluster", "completed_snapshot")
        .order_by("-updated_at")
    )
    for a in closed_activities:
        snap = a.completed_snapshot if hasattr(a, "completed_snapshot") else None
        a.variance = (
            (snap.actual_spend_amount - snap.disbursed_amount) if snap else None
        )

    context = {"closed": closed_activities}
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
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"],
    }
    return render(request, "pages/accounts/activity_finance_detail.html", context)


@require_page_permission("disbursements")
@require_export_permission
def batch_payments_view(request):
    """Batch Payments Page."""
    from django.db.models import F

    advances = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="staff",
            advance_requests__status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
        )
        .exclude(payment_status__in=PARTNER_PAID_STATUSES)
        .select_related("school")
        # est_cost_cents holds plain UGX despite its name -- no /100 here.
        .annotate(amount_ugx=F("est_cost_cents"))
        .distinct()
    )
    partners = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
            status="ia_verified",
            payment_status__in=PARTNER_PAYABLE_STATUSES,
        )
        .select_related("school")
        .annotate(amount_ugx=F("est_cost_cents"))
    )
    reimbursements = ReimbursementClaim.objects.filter(status="pending").select_related(
        "activity"
    )

    # CSV payout-file exports per tab.
    export = request.GET.get("export", "").strip()
    if export in ("advances", "partners", "reimbursements"):
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="batch_{export}.csv"'
        writer = csv.writer(response)
        if export == "advances":
            writer.writerow(
                [
                    "Activity ID",
                    "Type",
                    "School",
                    "Responsible Staff ID",
                    "Amount (UGX)",
                ]
            )
            for a in advances[:5000]:
                writer.writerow(
                    [
                        a.id,
                        a.get_activity_type_display(),
                        a.school.name if a.school else "Cluster-wide",
                        a.responsible_staff_id,
                        a.amount_ugx or 0,
                    ]
                )
        elif export == "partners":
            writer.writerow(
                ["Activity ID", "Type", "School", "Partner ID", "Amount (UGX)"]
            )
            for a in partners[:5000]:
                writer.writerow(
                    [
                        a.id,
                        a.get_activity_type_display(),
                        a.school.name if a.school else "Cluster-wide",
                        a.assigned_partner_id,
                        a.amount_ugx or 0,
                    ]
                )
        else:
            writer.writerow(
                [
                    "Claim ID",
                    "Staff ID",
                    "Activity Type",
                    "Approved Budget (UGX)",
                    "Advanced (UGX)",
                    "Actual Spend (UGX)",
                    "Reimbursement (UGX)",
                ]
            )
            for c in reimbursements[:5000]:
                # These fields hold plain UGX despite the model's stale
                # "Cents" comments (see apps/fund_requests/finance_models.py)
                # -- no /100 here.
                writer.writerow(
                    [
                        c.id,
                        c.staff_id,
                        c.activity.get_activity_type_display(),
                        c.approved_budget,
                        c.amount_advanced,
                        c.actual_spend,
                        c.reimbursement_amount,
                    ]
                )
        return response

    context = {
        "advances": advances,
        "partners": partners,
        "reimbursements": reimbursements,
    }
    return render(request, "pages/accounts/batch_payments.html", context)


@require_page_permission("disbursements")
def approval_history_view(request):
    """Finance Approval History Page."""
    requests = WeeklyFundRequest.objects.all().order_by("-week_start_date")

    context = {"requests": requests}
    return render(request, "pages/accounts/approval_history.html", context)


@require_page_permission("disbursements")
def audit_log_view(request):
    """Finance Audit Log Page."""
    logs = (
        FinanceAuditLog.objects.all().select_related("activity").order_by("-timestamp")
    )

    context = {"logs": logs}
    return render(request, "pages/accounts/audit_log.html", context)


@require_page_permission("monthly_request")
def monthly_request_view(request):
    """Program Lead monthly request: fetch Team Budget, then submit to CD."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests.monthly_request_service import get_monthly_request

    if getattr(request.user, "active_role", None) != "Program Lead":
        context = {"not_program_lead": True}
        return render(request, "pages/accounts/monthly_request.html", context)
    try:
        context = get_monthly_request(
            request.user,
            {
                key: request.GET.get(key)
                for key in ("fy", "month")
                if request.GET.get(key)
            },
        )
    except (BadRequest, Forbidden) as exc:
        context = {"action_error": str(exc)}
    if request.headers.get("HX-Target") == "monthly-request-root":
        return render(request, "partials/finance/monthly_request/root.html", context)
    return render(request, "pages/accounts/monthly_request.html", context)


@require_page_permission("monthly_request")
def monthly_request_action_view(request):
    """Explicit monthly-budget fetch and PL → CD submission actions."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests import monthly_request_service as service

    if request.method != "POST":
        return render(
            request,
            "partials/finance/monthly_request/root.html",
            {"action_error": "Method not allowed."},
            status=405,
        )
    error = ok = None
    fy = request.POST.get("fy")
    month = request.POST.get("month")
    try:
        if request.POST.get("action") == "fetch_budget":
            service.refresh_draft(request.user, fy, int(month))
            ok = "Your latest Team Budget has been fetched into an editable monthly request."
        elif request.POST.get("action") == "submit_to_cd":
            service.submit_to_cd(request.user, fy, int(month))
            ok = "Monthly request submitted to the Country Director for review."
        else:
            error = "Unknown monthly request action."
    except (BadRequest, Forbidden, TypeError, ValueError) as exc:
        error = str(exc)

    try:
        context = service.get_monthly_request(request.user, {"fy": fy, "month": month})
    except (BadRequest, Forbidden, TypeError, ValueError) as exc:
        context = {"action_error": str(exc)}
    context["action_error"] = error or context.get("action_error")
    context["action_ok"] = ok
    return render(request, "partials/finance/monthly_request/root.html", context)


@require_page_permission("disbursements")
def weekly_requests_view(request):
    """Weekly Fund Request Review Page."""
    requests = (
        WeeklyFundRequest.objects.all()
        .order_by("-week_start_date")
        .prefetch_related("lines")
    )

    context = {"requests": requests}
    return render(request, "pages/accounts/weekly_requests.html", context)
