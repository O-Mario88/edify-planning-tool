from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse

from apps.core.donut import build_rings
from apps.core.permissions import (
    has_permission,
    require_export_permission,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.activities.models import Activity
from apps.fund_requests.models import (
    AdvanceRequestStatus,
    ReimbursementClaim,
    AccountabilityRecord,
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
from apps.fund_requests.disbursement_dashboard_service import (
    fy_totals_all_fund_types,
    month_overview_all_fund_types,
)
from apps.analytics.platform_engine import finance_health


from apps.core.metrics import format_ugx_compact  # noqa: F401  (re-exported)


def _lacks_payment_authority(request):
    """403 when the caller may not move money, else None.

    The disbursements PAGE is open to Admin (navigation.py maps it to
    {Accountant, Admin}) so the queue can be read, but seeing a payment queue
    is not authority to pay out of it — the rule
    disbursement_dashboard_service._require_accountant_action already records
    in prose. These two actions carried only the page gate (FIN-03); this is
    the same `payment.act` check the sibling
    finance_views.clear_partner_payment_action carries, read from the matrix
    the 2026-08 audit's AUD-004 configured rather than from a role tuple.
    The services assert it again at the money.
    """
    if not has_permission(request.user, Permission.PAYMENT_ACT.value):
        return HttpResponse("Unauthorized", status=403)
    return None


# This module previously defined its own `format_ugx_compact` with the
# docstring "same as apps/frontend/views/budget_views.py". It was not: that
# copy used two decimals at the million and thousand scales, so UGX 1,234,567
# read as "UGX 1.2M" here and "UGX 1.23M" there. Both now come from
# apps.core.metrics.money.


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

    # 1. FY KPIs across every fund type with a financial year — monthly fund
    # plans and weekly advances — through the canonical aggregate the queue
    # classifiers feed (fy_totals_all_fund_types).
    #
    # These tiles are named "Total Approved Funds", "Total Disbursed" and
    # "Budget Utilization": figures a reader takes as the country's. They were
    # built from WeeklyFundRequest alone, so monthly fund plans — which carry
    # most of the value — were missing from every one of them, and Budget
    # Utilization divided one fund type's disbursement by one fund type's
    # approvals while presenting itself as the organisation's rate.
    fy_totals = fy_totals_all_fund_types(fy)

    total_disbursed_db = fy_totals["disbursed"]
    total_accounted_db = fy_totals["accounted"]
    total_returned_db = fy_totals["returned"]

    # Approved but not yet disbursed (Held included: a hold pauses approved
    # money rather than rejecting it).
    pending_disb_sum = fy_totals["pending_disbursement"]
    pending_disb_count = fy_totals["pending_disbursement_count"]

    # Still travelling up the approval chain
    awaiting_sum = fy_totals["awaiting_approval"]
    awaiting_count = fy_totals["awaiting_approval_count"]

    returned_sum = fy_totals["returned"]

    # Every request that has ever been disbursed (still outstanding
    # reconciliation or already closed) vs. the reconciled subset.
    disbursed_count = fy_totals["disbursed_count"]
    accounted_count = fy_totals["accounted_count"]

    # "Approved" = passed approval and disbursable-or-beyond — the
    # denominator for the Budget Utilization ratio.
    total_approved_db = fy_totals["approved"]
    finance_analytics = finance_health(
        approved=total_approved_db,
        disbursed=total_disbursed_db,
        accounted=total_accounted_db,
        returned=total_returned_db,
        reconciled_count=accounted_count,
        disbursed_count=disbursed_count,
        record_count=fy_totals["record_count"],
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

    # This Month Overview — every fund type, through the canonical service the
    # Disbursement Dashboard uses.
    #
    # This card used to sum WeeklyFundRequest alone while carrying the same
    # five rows and the same title as the Disbursements workspace card, which
    # sums the consolidated queue: monthly fund plans, weekly advances, partner
    # payments and reimbursements. On the seed that was UGX 1.25M against UGX
    # 3.3M+ -- most of the month's money absent from the card an Accountant
    # lands on. Both now read one implementation, so they cannot diverge.
    #
    # Note this is deliberately broader than the FY KPI strip above, which
    # remains weekly-advance-scoped; the card names its own population.
    today = date.today()
    month_overview_raw = month_overview_all_fund_types(fy, today.month)
    month_overview = {
        key: format_ugx_compact(value) for key, value in month_overview_raw.items()
    }
    month_overview["held_raw"] = month_overview_raw["held"]

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

    # Concentric rings for the shared donut component. Money, so each ring is
    # a share of the FY total and the centre reads the total itself.
    donut_rings = build_rings(
        [
            {
                "key": "disbursed",
                "label": "Disbursed",
                "value": total_disbursed_db,
                "display": format_ugx_compact(total_disbursed_db),
                "color": "var(--edify-success)",
            },
            {
                "key": "approved",
                "label": "Approved",
                "value": pending_disb_sum,
                "display": format_ugx_compact(pending_disb_sum),
                "color": "var(--edify-accent)",
            },
            {
                "key": "pending",
                "label": "Pending",
                "value": awaiting_sum,
                "display": format_ugx_compact(awaiting_sum),
                "color": "var(--edify-warning)",
            },
            {
                "key": "returned",
                "label": "Returned",
                "value": returned_sum,
                "display": format_ugx_compact(returned_sum),
                "color": "var(--edify-danger)",
            },
        ],
        share_of=donut_total or None,
    )

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
        "donut_rings": donut_rings,
        "recent_activity": recent_activity,
        "recon_pending": recon_pending,
        "recon_stats": recon_stats,
        "analytics": finance_analytics,
        "fy": fy,
        "mobile_primary_action": {
            "label": "Open consolidated queue" if all_funds else "Create disbursement",
            "url": "/disbursements" if all_funds else "/accounts/advances",
        },
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
    """Partner Payment Queue — the MOU's two instalments.

    The MOU pays 50% of the planned partner activity cost up front, and
    clears the balance once the partner finishes the work and IA verifies
    it. So this page runs two queues: costed partner work awaiting its 50%
    advance, and verified work awaiting clearance of the balance.
    """
    from django.db.models import Sum as _Sum

    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.fund_requests.finance_models import PartnerPayment

    base = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
        )
        .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .select_related("school", "cluster")
    )

    # "none" covers activities verified through the live IA path before it
    # started stamping ia_confirmed (an ia_verified partner activity is by
    # definition awaiting payment); "disbursed" is the 50% advance already
    # out, balance pending.
    payments = list(
        base.filter(
            status="ia_verified",
            payment_status__in=PARTNER_PAYABLE_STATUSES,
        )
    )

    # Awaiting the MOU advance: costed, not yet verified (a verified activity
    # that never took its advance simply clears in full), no instalment yet.
    advance_queue = list(
        base.filter(payment_status="none", schedule_cost_lines__isnull=False)
        .exclude(status__in=["ia_verified", "closed", "accountant_confirmed"])
        .exclude(partner_payments__isnull=False)
        .distinct()
    )

    for act in advance_queue:
        planned = act.schedule_cost_lines.aggregate(s=_Sum("amount"))["s"] or 0
        act.planned_total = planned
        act.mou_advance = planned // 2
    for act in payments:
        planned = act.schedule_cost_lines.aggregate(s=_Sum("amount"))["s"] or 0
        paid = (
            PartnerPayment.objects.filter(activity=act).aggregate(
                s=_Sum("amount_paid")
            )["s"]
            or 0
        )
        act.planned_total = planned
        act.advance_paid = paid
        act.balance_due = max(planned - paid, 0)

    # §9.1 — the transport company's pending obligations, one per mission
    # day. Settled here, never combined with a staff allowance transfer.
    from apps.fund_requests.finance_models import TransportPayment

    transport_queue = list(
        TransportPayment.objects.filter(status="pending")
        .select_related("batch")
        .order_by("batch__visit_date")
    )
    staff_names = {}
    if transport_queue:
        from apps.accounts.models import User as _User

        staff_names = dict(
            _User.objects.filter(
                id__in={t.batch.responsible_user for t in transport_queue}
            ).values_list("id", "name")
        )
    for t_pay in transport_queue:
        t_pay.staff_name = staff_names.get(t_pay.batch.responsible_user, "Staff")

    # Partner-submitted invoices drive the MOU instalments now: the
    # accountant downloads each invoice and pays the system-derived payable.
    from apps.fund_requests.finance_models import PartnerInvoice
    from apps.partners.models import Partner as _Partner

    invoice_queue = list(
        PartnerInvoice.objects.filter(status="confirmed_by_pl")
        .prefetch_related("items__activity__school")
        .order_by("created_at")
    )
    partner_names = dict(
        _Partner.objects.filter(
            id__in={i.partner_id for i in invoice_queue}
        ).values_list("id", "name")
    )
    for inv in invoice_queue:
        inv.partner_name = partner_names.get(inv.partner_id, inv.partner_id)

    context = {
        "payments": payments,
        "advance_queue": advance_queue,
        "invoice_queue": invoice_queue,
        "transport_queue": transport_queue,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque"],
    }
    return render(request, "pages/accounts/partner_payments.html", context)


@require_page_permission("disbursements")
def pay_partner_action(request, activity_id):
    """POST to pay partner."""
    denied = _lacks_payment_authority(request)
    if denied:
        return denied
    activity = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        partner_name = request.POST.get("partner_name", "").strip()
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        notes = request.POST.get("notes", "").strip()
        netsuite_id = request.POST.get("netsuite_expense_id", "").strip()

        try:
            amount = int(request.POST.get("amount_paid", 0))
            payment_type = request.POST.get("payment_type", "clearance").strip()
            PartnerPaymentService.pay_partner(
                activity,
                partner_name,
                amount,
                method,
                reference,
                request.user.user_id,
                notes,
                netsuite_id=netsuite_id,
                payment_type=payment_type,
            )
            messages.success(
                request, f"Partner payment of {amount} UGX processed successfully."
            )
        except Exception as e:
            messages.error(request, f"Partner payment failed: {e}")

    return redirect("/accounts/partner-payments/")


@require_page_permission("disbursements")
def pay_transport_action(request, payment_id):
    """POST — settle one mission day's transport with the provider."""
    from apps.fund_requests.vendor_channel import pay_transport_provider

    denied = _lacks_payment_authority(request)
    if denied:
        return denied
    if request.method == "POST":
        try:
            result = pay_transport_provider(
                payment_id,
                {
                    "provider_name": request.POST.get("provider_name"),
                    "payment_method": request.POST.get("payment_method"),
                    "payment_reference": request.POST.get("payment_reference"),
                    "netsuite_expense_id": request.POST.get("netsuite_expense_id"),
                    "notes": request.POST.get("notes"),
                },
                request.user,
            )
            messages.success(
                request,
                f"Transport payment of {result['amount']} UGX recorded.",
            )
        except Exception as e:  # noqa: BLE001 — page-level error surface
            messages.error(request, f"Transport payment failed: {e}")
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
    """Redirect the retired queue to its canonical replacement."""
    messages.info(
        request,
        "Reimbursements are processed from the Disbursement Dashboard, where "
        "NetSuite verification and employee receipt confirmation remain linked.",
    )
    return redirect("/disbursements?queue=reimbursements")


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
    return redirect("/disbursements?queue=reimbursements")


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
    """Returned Finance Items Page.

    FIN-05: this read `FinanceReturn.objects.filter(status="pending")`, and
    nothing in this codebase writes a FinanceReturn — no service, no view, no
    command, not even a test. The queue was structurally empty while the
    Accountant dashboard row linking here carried a real, non-zero returned
    balance from the AdvanceRequest ledger, and the empty state announced
    "All corrections resolved."

    `returned_correction_queue` reads that same ledger, so the page now answers
    the question the click asked. See its docstring for why the queue is
    standing rather than month-scoped.
    """
    from apps.fund_requests.disbursement_dashboard_service import (
        returned_correction_queue,
    )

    context = {"returns": returned_correction_queue()}
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
    # CSV payout-file exports per tab.
    export = request.GET.get("export", "").strip()
    if export in ("advances", "partners"):
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
        return response

    context = {
        "advances": advances,
        "partners": partners,
    }
    return render(request, "pages/accounts/batch_payments.html", context)


@require_page_permission("disbursements")
def approval_history_view(request):
    """Finance Approval History Page.

    The approval columns are derived from each record's status, never assumed.
    They were previously three hardcoded green "Approved" cells on a page that
    calls itself a Traceability Ledger — so a request still awaiting its
    owner's confirmation displayed three sign-offs that had not happened
    (2026-08 UI/UX audit, UX-004).
    """
    from apps.fund_requests.disbursement_dashboard_service import _weekly_chain

    # Materialised before stamping: `{% paginate %}` re-evaluates a queryset,
    # which would rebuild the model instances and drop the attribute.
    requests = list(WeeklyFundRequest.objects.all().order_by("-week_start_date"))
    for req in requests:
        req.approval_chain = _weekly_chain(req)

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
    """Program Lead, CD, and RVP monthly request workspace."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests.monthly_request_service import get_monthly_request

    role = getattr(request.user, "active_role", None) or ""
    if (
        role
        in ("CountryDirector", "Admin", "RegionalVicePresident", "CD", "ADMIN", "RVP")
        and request.headers.get("HX-Target") != "monthly-request-root"
    ):
        from apps.frontend.views.finance_views import country_budget_view

        return country_budget_view(request)

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
    """Explicit monthly-budget fetch, PL → CD, and CD → RVP submission actions."""
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
        elif request.POST.get("action") == "submit_to_rvp":
            service.submit_to_rvp(request.user, fy, int(month))
            ok = "Monthly country budget submitted to the Regional Vice President (RVP) for approval."
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


@require_page_permission("disbursements")
def partner_invoice_download(request, invoice_id):
    """Finance downloads the partner's uploaded invoice document."""
    from django.http import FileResponse

    from apps.fund_requests.partner_invoices import invoice_file

    invoice, handle = invoice_file(invoice_id, request.user)
    return FileResponse(handle, as_attachment=True, filename=invoice.original_name)


@require_page_permission("disbursements")
def partner_invoice_pay_action(request, invoice_id):
    """POST — pay the invoice's instalment (delegates to pay_partner)."""
    from apps.fund_requests.partner_invoices import pay_invoice

    denied = _lacks_payment_authority(request)
    if denied:
        return denied
    if request.method == "POST":
        try:
            result = pay_invoice(
                invoice_id,
                {
                    "payment_method": request.POST.get("payment_method"),
                    "payment_reference": request.POST.get("payment_reference"),
                    "netsuite_expense_id": request.POST.get("netsuite_expense_id"),
                },
                request.user,
            )
            messages.success(
                request, f"Invoice paid — {result['paid']} UGX to the partner."
            )
        except Exception as e:  # noqa: BLE001 — page-level error surface
            messages.error(request, f"Invoice payment failed: {e}")
    return redirect("/accounts/partner-payments/")
